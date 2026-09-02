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
- `project_context.py`：按优先级加载有界的项目约定文件并注入初始 system prompt。
- `spec.py`：项目内 Spec 产物、阶段状态机、任务解析和阶段提示词。
- `tool_protocol.py`：工具 schema、注册表、参数验证和异常边界。
- `tools/`：工作区文件操作与本地命令执行。
- `policy.py`：路径隔离、写操作确认和危险命令拒绝。
- `terminal_ui.py`：无第三方依赖的启动页、角色分区、工具摘要、状态栏和 ANSI 降级。
- `config.py`：环境变量和运行限制。

配置优先级为环境变量、用户配置文件、内置默认值。`jarvis configure` 将凭据写入仓库外的 `~/.jarvis/config.json`，API key 使用隐藏输入且不作为命令参数。这样配置能跨终端和重启保留，同时环境变量仍可做临时覆盖。

会话默认保存到 `~/.jarvis/sessions`。每次追加 user、assistant 或 tool 消息后都会原子写入 checkpoint，因此正常结束、工具失败或后续轮次异常时已有轨迹仍可恢复。`--continue` 只选择当前 workspace 的最近会话，`--resume` 也会校验会话所属 workspace，避免把其它项目历史注入当前任务。

人类输出模式使用 OpenAI 兼容 SSE 流，逐段显示 assistant 文本，并按 tool-call index 拼接可能被拆分的函数名与 JSON 参数。收到 `[DONE]` 后才将完整响应写入历史。畸形 UTF-8、JSON、choice/delta、tool-call index 和非文本碎片都会转换为 `ModelResponseError`，不会让半截调用进入工具层。`--json` 保持非流式，确保 stdout 始终只有一个完整 JSON 对象；`--no-stream` 可为兼容性较差的网关回退到普通响应。

终端是 JARVIS 的主交互层。无位置参数的 `jarvis` 启动项目内 REPL，以启动页显示 workspace、模型、Git 分支、session、运行模式、工具数和审批策略，并使用 `YOU / JARVIS / TOOL / VERIFY` 分区展示轨迹。工具事件只展示有界参数和元数据，避免文件正文污染对话。颜色仅在支持的 TTY 中启用，`--no-color`、`NO_COLOR` 和重定向输出会退化为纯文本。带任务参数时走同一个 agent loop 做一次性执行；`--json` 提供稳定的自动化接口。这些入口只改变输入输出，不复制核心逻辑。

`jarvis-gui` 是早期 Tkinter 实验性薄启动层，保留用于目录选择和一次性任务启动，但不是项目主界面。它使用参数数组和当前虚拟环境的 Python 启动 `python -m jarvis_agent`，不使用 `shell=True`。GUI 不直接调用模型或工具，因此不会形成第二套 agent loop。可选 PowerShell 脚本可以为当前 Windows 用户注册文件夹和文件夹背景右键菜单，但程序本身不会自动修改注册表。

## Spec 驱动状态机

复杂任务可以通过 `/spec new <name> <goal>` 进入项目级 Spec 流程：

```text
requirements --approve--> design --approve--> tasks --approve--> implementing
                                                                    |
                                                              tasks 全部完成
                                                                    v
                                                               verifying
                                                          PASS /       \ FAIL
                                                   completed            implementing + TV 修复任务
```

每个 Spec 位于 `.jarvis/specs/<name>/`，包含 `requirements.md`、`design.md`、`tasks.md`、`verification.md` 和原子写入的 `state.json`。状态不依赖聊天历史，因此进程退出后仍可恢复。当前只允许一个未结束 Spec，完成或取消的 Spec 会保留供审计。

阶段约束由 `Policy` 强制执行，而不是依靠模型自律：

- 规划阶段只允许写当前产物的精确路径，并禁用 `run_command`。
- 实施阶段允许业务代码和 `tasks.md` 更新，但保护已批准的 requirements、design、verification 与 `state.json`。
- 验证阶段允许执行测试，但只允许写 `verification.md`。
- 自由文本任务在存在活跃 Spec 时被拒绝，必须通过 `/spec revise`、`/spec approve`、`/spec implement` 或 `/spec verify` 推进。

`tasks.md` 使用标准 Markdown 复选框。JARVIS 每次只选取第一个 `- [ ]` 任务；只有模型完成验证并将其更新为 `[x]` 后才推进。最终验证要求 `verification.md` 包含独立一行 `Status: PASS`。失败时确定性地增加 `TV<n>` 修复任务并回到实施阶段，避免流程卡死或静默完成。

## 上下文策略

内部统一使用 `system/user/assistant/tool` 消息。工具结果必须带原始 `tool_call_id`。每次请求前先限制单个工具输出长度；仍超预算时，以完整轨迹为单位移除最旧的 assistant-tool 组合，永远保留 system 和 user 消息。如果 system 与用户消息本身已超限，则明确停止，不静默丢弃任务要求。

当前使用字符数作为与模型无关的保守预算，不声称它是精确 token 数。后续可以在模型适配层增加 tokenizer，而不改变 agent loop。

启动时会从 workspace 根目录选择第一份非空上下文文件：`.jarvis.md`、`JARVIS.md`、`AGENTS.override.md`、`AGENTS.md`、`CLAUDE.md`、`.cursorrules`。单文件限制 20,000 字符，超限时保留头尾。上下文文本被明确标记为仓库约定，不能覆盖安全策略和当前用户任务。首版只做根目录发现；按访问路径渐进加载子目录约定留在后续路线图中。

## 工具与执行

首版工具为：

- `list_files`
- `search_text`
- `read_file`
- `read_files`
- `write_file`
- `edit_file`
- `run_command`

`search_text` 在本地确定性地返回文件名、行号和短片段，支持 glob、大小写和正则选项，并限制文件大小与结果数。模型负责解释结果，但不负责伪造搜索过程。

`read_files` 用于在已经知道文件路径后批量读取 1～8 个相关 UTF-8 文件，统一使用相同的 offset/limit，并保留逐文件元数据。它不扩大路径权限：任意路径越界、凭据文件或 Git 元数据仍会使整个调用失败。写工具继续保持独立和串行，不提供批量覆盖。

每轮模型响应的 provider usage 会在一次 `Agent.run()` 内累加，最终结果同时返回 token 字段和 wall-clock 耗时；如果兼容网关不提供 usage，则明确显示为不可用，不使用字符数冒充精确 token。

结果同时包含按工具名汇总的 `tool_usage` 和 `verification_status`（`not_required`、`required`、`passed`），用于区分“模型说完成”和“修改后确有成功命令”的评测。CLI 启动时将 stdout/stderr 固定为 UTF-8，使 Windows 控制台、管道和 JSON 文件中的中文保持一致。

所有路径先相对 workspace 解析，再检查最终绝对路径仍位于 workspace 内。文件工具拒绝访问 `.git`、私钥和常见凭据文件。`edit_file` 只接受唯一的精确匹配，避免修改错误位置。工具注册表递归校验 object、array items、enum、长度和数值范围，不依赖模型遵守 schema。命令在 workspace 中运行，带超时和输出上限，并从子进程环境移除名称疑似 key、token、secret 或 password 的变量。`run_command` 还必须声明 `purpose=inspect|verify`，使探查动作与完成证据在轨迹中可区分。

这层策略是应用级护栏，不是操作系统沙箱。特别是 shell 命令仍可能主动访问 workspace 外的位置，因此 README 明确要求只在可信任务、允许修改的仓库中运行。

## 终止条件

- 模型返回文本且无工具调用：`model_final_answer`。
- 普通项目文件在最后一次有效验证后又发生写入：拒绝结束并注入验证提醒；只有后续 `purpose=verify` 的命令成功才可完成，成功的 `inspect` 命令不能通过该门。
- 达到模型轮次上限：`max_turns`。
- 达到工具调用上限：`max_tool_calls`。
- 连续三次相同工具错误：`repeated_tool_error`。
- 用户 Ctrl+C：进程退出码 130。
- 配置、认证、响应协议或上下文错误：以类型化错误停止。

每种停止都向调用者返回原因，不使用无法解释的静默退出。

## 错误恢复

429、连接错误和部分 5xx 最多重试两次，使用指数退避和抖动。401/403 立即作为认证错误停止；其它 4xx 作为请求错误停止；畸形 JSON、缺失消息或非法 tool call 参数作为响应协议错误停止。本地工具错误会作为结构化 tool result 回填给模型，使模型有机会重新读取和修正。
