# JARVIS 架构说明

## 定位

JARVIS 是一个简易版 Claude Code 风格的 Coding Agent，而不是普通聊天机器人。用户给出编程任务后，它会让模型决定下一步动作，在本地读取或修改代码、执行测试命令、观察工具结果，并持续迭代到模型给出最终答案或触发明确的停止条件。

项目不使用 agent 框架、服务端代码执行或 Files API。普通模型请求之外的关键逻辑均由本项目实现。

## 主循环

```text
用户任务
   ↓
构造/裁剪消息历史
   ↓
调用 OpenAI 兼容 Chat Completions API
   ↓
解析 assistant 文本与 tool_calls
   ├── 无 tool_calls → 最终答案
   └── 有 tool_calls
          ↓
       校验工具名和 JSON 参数
          ↓
       本地串行执行工具
          ↓
       以 tool_call_id 回填结果
          └──────────────→ 下一轮模型调用
```

写入和命令工具采用串行执行，保证多次修改之间的观察顺序确定。未来即使增加只读并发，写操作也不应并发。

## 模块边界

- `cli.py`：参数、交互、JSON/人类输出和进程退出码。
- `agent.py`：唯一 agent loop、轮次与工具次数、重复错误终止。
- `model_client.py`：普通 HTTP 模型请求、有限重试、响应解析；不包含 agent 决策。
- `context.py`：确定性裁剪历史，保证 assistant tool call 与 tool result 不被拆散。
- `tool_protocol.py`：工具 schema、注册表、参数验证和异常边界。
- `tools/`：工作区文件操作与本地命令执行。
- `policy.py`：路径隔离、写操作确认和危险命令拒绝。
- `config.py`：环境变量和运行限制。

配置优先级为环境变量、用户配置文件、内置默认值。`jarvis configure` 将凭据写入仓库外的 `~/.jarvis/config.json`，API key 使用隐藏输入且不作为命令参数。这样配置能跨终端和重启保留，同时环境变量仍可做临时覆盖。

会话默认保存到 `~/.jarvis/sessions`。每次追加 user、assistant 或 tool 消息后都会原子写入 checkpoint，因此正常结束、工具失败或后续轮次异常时已有轨迹仍可恢复。`--continue` 只选择当前 workspace 的最近会话，`--resume` 也会校验会话所属 workspace，避免把其它项目历史注入当前任务。

## 上下文策略

内部统一使用 `system/user/assistant/tool` 消息。工具结果必须带原始 `tool_call_id`。每次请求前先限制单个工具输出长度；仍超预算时，以完整轨迹为单位移除最旧的 assistant-tool 组合，永远保留 system 和 user 消息。如果 system 与用户消息本身已超限，则明确停止，不静默丢弃任务要求。

当前使用字符数作为与模型无关的保守预算，不声称它是精确 token 数。后续可以在模型适配层增加 tokenizer，而不改变 agent loop。

## 工具与执行

首版工具为：

- `list_files`
- `read_file`
- `write_file`
- `edit_file`
- `run_command`

所有路径先相对 workspace 解析，再检查最终绝对路径仍位于 workspace 内。文件工具拒绝访问 `.git`、私钥和常见凭据文件。`edit_file` 只接受唯一的精确匹配，避免修改错误位置。命令在 workspace 中运行，带超时和输出上限，并从子进程环境移除名称疑似 key、token、secret 或 password 的变量。

这层策略是应用级护栏，不是操作系统沙箱。特别是 shell 命令仍可能主动访问 workspace 外的位置，因此 README 明确要求只在可信任务、允许修改的仓库中运行。

## 终止条件

- 模型返回文本且无工具调用：`model_final_answer`。
- 达到模型轮次上限：`max_turns`。
- 达到工具调用上限：`max_tool_calls`。
- 连续三次相同工具错误：`repeated_tool_error`。
- 用户 Ctrl+C：进程退出码 130。
- 配置、认证、响应协议或上下文错误：以类型化错误停止。

每种停止都向调用者返回原因，不使用无法解释的静默退出。

## 错误恢复

429、连接错误和部分 5xx 最多重试两次，使用指数退避和抖动。401/403 立即作为认证错误停止；其它 4xx 作为请求错误停止；畸形 JSON、缺失消息或非法 tool call 参数作为响应协议错误停止。本地工具错误会作为结构化 tool result 回填给模型，使模型有机会重新读取和修正。
