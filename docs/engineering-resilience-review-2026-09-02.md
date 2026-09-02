# 工程韧性审查与极端场景测试（2026-09-02）

## 结论先行

JARVIS 已经具备题目要求的 Coding Agent 核心闭环：模型决策、上下文裁剪、本地工具、结果回传、循环终止、错误归一化、会话持久化和写后验证均为项目内自行实现。它不是只能生成单文件代码的聊天机器人，也没有把关键控制权交给 Agent 框架。

这些能力需要按产品边界评估。RAG、MCP、skills、长期记忆和 SFT 是可选能力，不是一个 Coding Agent 成立的必要条件；任务队列、线程池和模型并发闸门是多人 Web 服务的必要工程设施，但不是当前本地、单用户、单任务 CLI 的必需组件。工程成熟度不能简单用功能数量衡量。

本轮新增 14 项极端场景回归，完整测试从 71 项增加到 85 项，并修复了模型响应、工具上限、交互恢复、输出上限和进程树超时方面的确定缺陷。

## 能力对照

| 方向 | 当前状态 | 代码证据 | 判断 |
|---|---|---|---|
| Agent 循环 | 已实现 | [`Agent.run`](../src/jarvis_agent/agent.py) | 核心能力 |
| 对话历史与上下文 | 已实现 | [`context.py`](../src/jarvis_agent/context.py)、[`session.py`](../src/jarvis_agent/session.py) | 有界短期记忆与持久会话 |
| 工具定义和本地执行 | 已实现 | [`tool_protocol.py`](../src/jarvis_agent/tool_protocol.py)、[`tools/`](../src/jarvis_agent/tools/) | 7 个本地工具，递归 schema 校验 |
| 模型输出解析 | 已实现 | [`model_client.py`](../src/jarvis_agent/model_client.py) | 普通 JSON 与 SSE tool calling |
| 循环终止 | 已实现 | [`agent.py`](../src/jarvis_agent/agent.py) | turn、tool、重复错误和验证门 |
| 错误处理 | 已实现 | [`errors.py`](../src/jarvis_agent/errors.py) | 配置、模型、策略、工具错误分层 |
| Spec 开发 | 已实现 | [`spec.py`](../src/jarvis_agent/spec.py) | requirements → design → tasks → verify |
| RAG | 未实现 | 无向量库或检索器 | 当前 Coding Agent 不需要；领域问答才优先 |
| MCP client/server | 未实现 | 无 MCP 协议层 | 可扩展，但当前轻量版本不应为功能数量而堆协议 |
| skills | 部分近似 | [`project_context.py`](../src/jarvis_agent/project_context.py) | 支持项目规则注入，但不是可发现、可安装的 skill 系统 |
| 长期语义记忆 | 未实现 | 当前只有 session JSON | 后续应做“经用户确认的稳定事实沉淀”，不应自动保存源码和密钥 |
| SFT 微调 | 未实现 | 无训练代码 | 没有高质量轨迹数据与基准前不应先微调 |
| 服务端任务队列 | 未实现 | 当前无 HTTP 服务 | 对本地 CLI 合理；变成多人服务前必须增加 |

## 本轮极端场景

| 场景 | 修改前表现 | 当前结果 | 回归位置 |
|---|---|---|---|
| 单轮两个工具调用恰好撞上总上限 | 留下缺少 tool result 的非法历史 | 未执行调用写入结构化 limit 结果，历史仍满足协议 | `test_agent.py` |
| `message=[]`、`content=0`、`tool_calls=7` | 可能泄漏 `AttributeError`/`TypeError` | 统一转成 `ModelResponseError` | `test_model_client.py` |
| 重复 tool-call ID | 两个结果无法可靠对应 | 解析阶段拒绝 | `test_model_client.py` |
| SSE 将 tool-call ID 分片 | 后一片覆盖前一片 | 按 index 累积完整 ID | `test_model_client.py` |
| `usage=[]`、非法 finish reason | 可能进入 Agent 后再崩溃 | 在模型边界立即拒绝 | `test_model_client.py` |
| 429 连续两次后恢复 | 需验证重试次数 | 1、2 秒指数退避后第三次成功 | `test_model_client.py` |
| 401 鉴权失败 | 不应重试 | 只请求一次并立即失败 | `test_model_client.py` |
| 网络请求持续超时 | 不能无限重试 | 严格限制为 1 次请求 + 2 次重试 | `test_model_client.py` |
| 交互模式一次模型故障 | 整个 REPL 退出 | 报错后仍接受下一条命令 | `test_cli.py` |
| 工具输出远超上限 | 标记文本使结果反而超过上限 | 含截断标记仍不超过配置值 | `test_tools.py`、`context.py` |
| 命令超时后派生子进程 | 外层 shell 结束但子进程继续，1 秒超时实测约 11 秒返回 | Windows Job Object / POSIX process group 终止整棵进程树，约 1 秒返回 | `test_tools.py`、`shell.py` |
| 工具插件抛出未知异常 | 需验证边界 | 转为 `internal_tool_error`，不击穿 Agent | `test_tools.py` |
| 32 个独立会话并发保存 | 需验证原子 checkpoint | 全部 JSON 有效且可加载 | `test_session.py` |
| 一个会话文件损坏 | 可能影响会话列表 | 跳过损坏文件，保留其它有效会话 | `test_session.py` |

## 当前已经具备的阻塞兜底

模型请求由 [`OpenAICompatibleClient`](../src/jarvis_agent/model_client.py) 设置单次超时，且只对 429、5xx、网络错误和超时做有界指数退避；401/403、其它 4xx 和畸形响应不会盲目重试。重试耗尽后抛出类型明确的 `ModelError`。一次失败不再关闭交互终端，用户可以重试、切换模型或继续其它任务。

本地命令同时受默认超时、单次最大 300 秒、危险命令策略和输出上限约束。超时终止的是进程树而不只是外层 shell：Windows 使用 kill-on-close Job Object，POSIX 使用新 session/process group。Agent 自身另有最大模型轮次、最大工具次数、三次相同工具错误停止和写后验证门，所以模型无法无限循环调用工具。

这些机制解决的是“有界失败”，不是高可用服务。默认配置下，模型最坏仍可能经历三次 90 秒请求以及退避时间；未来需要再增加覆盖整个任务的绝对 deadline 和主动取消令牌。

## 为什么当前没有任务队列

当前入口是一个用户在一个本地 workspace 中运行一个 Agent。此时强行增加服务端队列和线程池不会提高成功率，反而会引入同一仓库并发写、同一 session 丢更新、命令互相影响和更难解释的取消语义。

如果改成 Web 或多人版本，推荐的数据流是：

```text
HTTP 请求
   │
   ├─ 身份、配额、请求大小校验
   ▼
有界任务队列 ──队列满──> 429/503 + Retry-After
   │
   ▼
固定 worker pool
   │
   ├─ per-workspace mutex：同一仓库最多一个写任务
   ├─ per-provider semaphore：不超过模型网关并发额度
   ├─ task deadline / cancellation token
   └─ 独立工作副本或 worktree
   ▼
模型 API + 本地工具进程
```

关键点不是“用了线程池”，而是背压和隔离：

1. 队列必须有界；满载时明确拒绝，不能无限占内存。
2. worker 数不能等于前端并发数，应按 CPU、模型额度和工作区隔离能力确定。
3. 模型并发信号量应位于 provider adapter 层，让多个 worker 共享同一额度。
4. 同一 workspace 必须串行写；不同任务最好使用独立 clone/worktree。
5. API 任务要有 `queued/running/cancelling/succeeded/failed/timed_out` 状态和 request ID。
6. 只重试幂等的模型请求；工具写入不能被队列自动重放。
7. 保存指标：排队时间、首 token 延迟、模型重试、工具超时、任务成功率和验证成功率。

阻塞式 `urllib` 客户端可以暂时放在线程 worker 中，但命令执行更适合独立进程。若未来使用异步 HTTP 客户端，模型 I/O 可由 event loop 管理，本地命令仍应保留进程级取消和隔离。

## 仍然存在的工程边界

以下是尚未解决、需要在后续版本继续处理的工程边界：

1. **无任务级总 deadline。** 目前只有单次模型和单次命令超时；下一步应把剩余预算逐层传给模型与工具。
2. **命令输出先由 `communicate()` 收集再截断。** 能限制进入模型的内容，但极端输出仍可能占用较多内存；生产版应流式读取到固定大小 ring buffer 或临时文件。
3. **非流式 HTTP body 和单条 SSE event 没有字节级硬上限。** 应增加响应体上限。
4. **上下文按字符近似，不是 tokenizer。** 所有 user 消息被保护，超长多轮会明确报 `AgentLimitError`，但尚无自动摘要和稳定记忆沉淀。
5. **并发保存只验证了不同 session。** 同一个 session 多写者仍是 last-write-wins；服务版必须做版本号/CAS 或互斥。
6. **同一 workspace 没有跨进程锁。** 当前单实例 CLI 合理，服务版不允许多个写 Agent 直接共享目录。
7. **验证相关性主要依赖提示。** `purpose=verify` 且退出码为 0 就能解除验证门；未来应让 Spec requirement ID 映射到允许的验证命令和产物。
8. **正则搜索和超大目录遍历没有总时间预算。** 生产版应优先调用 `rg`、限制文件数，并为正则匹配设置可中断边界。
9. **没有熔断器和 `Retry-After` 支持。** 单用户 CLI 的有界重试足够；共享网关场景必须避免所有 worker 同时重试。

## 复现

```powershell
cd JARVIS
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
```

预期结果：`Ran 85 tests`，`OK`。其中命令进程树测试会真实启动并超时终止一个父子进程链，而不是只使用 mock。
