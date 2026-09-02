# JARVIS Web Console

> `feature/web-console` 实验分支：为 JARVIS Coding Agent 增加一个运行在本机的浏览器界面。`main` 和 `dev` 分支仍保留终端版。

JARVIS 是一个轻量级、Local-first 的 Coding Agent，可以理解为简易版 Claude Code。用户给出编程任务后，它会自主读取和搜索代码、修改文件、执行命令、观察测试结果并继续迭代，直到任务完成或触发明确的停止条件。

Web Console 不是单纯的聊天网页，也不是第二套 Agent。它复用 JARVIS 原有的 Agent Loop、上下文、工具、安全策略和验证机制，只把交互过程呈现在浏览器中；模型请求、文件操作和命令执行仍发生在本机。

## Web Console 功能

- **任务时间线**：按顺序展示用户任务、JARVIS 回复、工具调用、验证结果和停止原因。
- **流式回复**：模型生成内容会持续出现在页面中，无需等待整轮完成。
- **工具轨迹**：可看到 Agent 何时读取文件、搜索代码、修改内容或执行测试。
- **浏览器审批**：写文件、精确编辑和执行命令可在网页中逐项批准或拒绝。
- **多轮交互**：完成一个任务后，可以继续提出修改要求，沿用当前会话上下文。
- **运行状态**：页面显示 workspace、模型、会话状态、工具数量和当前任务阶段。
- **并发保护**：同一 workspace 同一时间只运行一个任务，避免两个 Agent 同时修改代码。
- **本地访问**：服务只监听 `127.0.0.1`，API 使用每次启动随机生成的 token。

## Coding Agent 核心能力

- 多轮自主 Coding：`读取 → 分析 → 修改 → 运行 → 观察 → 再修复`
- 七个本地工具：文件列表、代码搜索、单文件/批量读取、写入、精确编辑、命令执行
- 对话历史持久化，以及 `--continue`、`--resume`
- 自动读取 `JARVIS.md`、`AGENTS.md` 等项目约定
- workspace 路径隔离、敏感变量过滤、危险命令拒绝
- 修改源码后必须执行显式验证，取得测试或构建证据才能报告完成
- 模型超时、协议异常、工具失败和轮次耗尽等错误边界
- Spec 模式：`requirements → design → tasks → implement → verify`
- 稳定 JSON 输出，便于自动化脚本和评测调用

这些关键逻辑由项目自行实现，不依赖 LangChain、OpenAI Agents SDK 或 Claude Agent SDK。

## 快速开始

要求 Python 3.11 或更高版本。

```powershell
cd D:\path\to\JARVIS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
jarvis configure
jarvis doctor
```

DeepSeek 配置示例：

```text
Model: deepseek-v4-flash
Base URL: https://api.deepseek.com
```

API key 保存在仓库外的 `~/.jarvis/config.json`，不会写入项目或显示在运行日志中。

## 启动 Web Console

指定一个需要开发的项目目录：

```powershell
jarvis-web --workspace D:\path\to\your-project --allow-remote
```

JARVIS 会在 `127.0.0.1:8765` 启动服务并自动打开浏览器。进入页面后，直接输入任务，例如：

```text
阅读项目，定位失败测试的根因，修复问题并运行完整测试；不要修改无关文件。
```

推荐首次体验时保留默认审批模式。JARVIS 请求写入文件或执行命令时，页面会出现审批卡片，可确认 Agent 实际采取的每一步操作。

常用参数：

| 参数 | 说明 |
|---|---|
| `--workspace PATH` | 固定本次运行允许操作的项目目录 |
| `--allow-remote` | 允许将任务、Agent 选择的源码和命令输出发送给远程模型 |
| `--yes` | 自动批准普通操作，但不会解除危险命令限制 |
| `--no-session` | 不保存本次多轮对话历史 |
| `--no-open` | 不自动打开浏览器，只在终端打印访问地址 |
| `--port PORT` | 指定本地端口；使用 `0` 可自动选择空闲端口 |
| `--max-turns N` | 设置单个任务允许的最大模型轮次 |

更完整的运行机制、安全设计和测试方法见 [Web 控制台说明](docs/web-console.md)。

## 继续使用终端版

该分支没有替换原有 CLI。进入目标项目后仍可使用交互模式：

```powershell
cd D:\path\to\your-project
jarvis --allow-remote
```

也可以一次性执行任务：

```powershell
jarvis --allow-remote --yes "实现功能，补充测试并运行完整测试套件。"
```

远程模型会收到任务、Agent 主动读取的项目内容和命令输出，因此需要通过 `--allow-remote` 明确授权。本地模型不需要该参数。

## 安全边界

- Web 服务固定监听 localhost，不提供公网监听参数。
- 页面及 API 使用随机 token；token 从地址栏移除后仅保存在当前标签页。
- 所有文件工具都受 workspace 边界约束，不能通过相对路径越界访问。
- 工具事件不会在网页中完整回显待写入正文或精确编辑内容。
- `--yes` 只跳过普通操作审批，危险命令仍由安全策略拒绝。
- 本地命令最终拥有启动 JARVIS 的系统用户权限，因此使用前仍应检查 workspace 并做好 Git 版本管理。

请勿通过反向代理、端口转发或隧道把当前实验版暴露到公网。

## 当前限制

- 一个 Web Runtime 只处理一个 workspace，任务采用串行执行。
- 正在运行的任务暂不支持主动取消。
- 浏览器与本地服务使用增量轮询；模型侧仍使用 SSE 流式响应。
- Web Console 面向本机单用户场景，暂不包含登录、远程协作和多租户隔离。
- JARVIS 仍受所配置模型的能力、上下文窗口和 API 稳定性影响。

## Spec 模式

复杂需求可以先形成可审查的 Spec，再允许 Agent 修改业务代码：

```text
/spec new health-system 实现健康知识咨询原型，包含风险分流、RAG 和自动测试
/spec show requirements
/spec approve
/spec show design
/spec approve
/spec show tasks
/spec approve
/spec implement
/spec verify
```

规划阶段由工具策略禁止业务代码写入和命令执行，任务批准后才进入实现。完整说明见 [Spec 驱动开发](docs/spec-mode.md)。

## 文档

- [Web 控制台说明](docs/web-console.md)
- [安装、配置与日常使用](docs/getting-started.md)
- [CLI、工具、JSON 与安全参考](docs/cli-reference.md)
- [Spec 驱动开发](docs/spec-mode.md)
- [架构说明](docs/architecture.md)
- [工程韧性审查与极端场景测试](docs/engineering-resilience-review-2026-09-02.md)
- [外部审查问题复现与修复记录](docs/external-review-follow-up-2026-09-02.md)
- [Hermes 启发的演进路线与 TaskBoard 评测](docs/hermes-inspired-roadmap.md)

## 开发与测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

当前版本为 `1.1.0`，完整测试集共 89 项。

## License

MIT
