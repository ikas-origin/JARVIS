# JARVIS

JARVIS 是一个轻量级、终端优先的 Coding Agent，可以理解为简易版 Claude Code。

用户给出编程任务后，JARVIS 会自主搜索和读取代码、修改文件、执行本地命令、观察测试结果并继续迭代，直到完成任务或触发明确的停止条件。

项目自行实现 agent loop、对话历史与上下文管理、本地工具、模型输出解析、循环终止、错误处理和 Spec 驱动状态机，不使用 LangChain、OpenAI Agents SDK 或 Claude Agent SDK。

## 核心能力

- 多轮自主 Coding：读取、搜索、修改、运行、观察、继续修复
- 七个本地工具：文件列表、代码搜索、单文件/批量读取、写入、精确编辑、命令执行
- 钢铁侠风格启动页，以及清晰分离的 `YOU / JARVIS / TOOL / VERIFY` 终端输出
- 基于路径规范化的 workspace 文件访问边界、会话与 workspace 绑定、敏感路径保护
- 子进程环境变量净化、Human-in-the-loop 操作审批、危险命令拒绝
- 流式输出、token/耗时统计、明确停止原因
- 对话持久化以及 `--continue`、`--resume`
- 自动加载 `JARVIS.md`、`AGENTS.md` 等项目约定
- 修改源码后必须通过显式 `verify` 命令取得可执行证据才能结束
- 稳定 JSON 输出，支持脚本和评测
- Spec 模式：`requirements → design → tasks → implement → verify`

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

API key 会保存在仓库外的 `~/.jarvis/config.json`，不会被 JARVIS 打印。

## 使用

进入需要开发的项目并启动：

```powershell
cd D:\path\to\your-project
jarvis --allow-remote
```

在交互终端中描述任务：

```text
you> 阅读项目，修复失败的测试并重新运行验证，不要修改无关文件。
```

一次性执行：

```powershell
jarvis --allow-remote --yes "实现用户登录接口，补充测试并运行完整测试套件。"
```

远程模型会收到任务、Agent 主动读取的项目内容和命令输出，因此必须使用 `--allow-remote` 明确确认；本地模型不需要该参数。默认情况下，JARVIS 会在写文件或执行命令前询问。`--yes` 自动批准普通操作，但不会解除危险命令限制。

这些机制构成 Defense-in-Depth 的应用级安全边界，并非操作系统级沙箱：文件工具不能越过 workspace，但本地 shell 仍以启动 JARVIS 的系统用户权限运行。建议只在可信任务和已纳入 Git 管理的项目中使用。

交互终端会在支持 ANSI 的 TTY 中自动启用颜色，并隐藏写入工具的长文本参数，只显示长度和关键元数据。需要纯文本时使用 `--no-color`，也可设置通用的 `NO_COLOR` 环境变量；`--json` 输出始终不含界面装饰。

Linux/macOS 建议先激活虚拟环境再启动。即使直接运行 `.venv/bin/jarvis`，JARVIS 也会把自身解释器目录加入工具子进程的 `PATH`，使 Agent 调用 `python` 时仍优先使用同一虚拟环境。

## Spec 模式

复杂功能建议先写 Spec，再实现：

```text
you> /spec new health-system 实现健康知识咨询原型，包含风险分流、RAG和自动测试
you> /spec show requirements
you> /spec approve
you> /spec show design
you> /spec approve
you> /spec show tasks
you> /spec approve
you> /spec implement
you> /spec verify
```

规划阶段由工具策略强制禁止业务代码写入和命令执行；任务批准后才进入实现。完整说明见 [Spec 驱动开发](docs/spec-mode.md)。

## 文档

- [安装、配置与日常使用](docs/getting-started.md)
- [Spec 驱动开发](docs/spec-mode.md)
- [CLI、工具、JSON 与安全参考](docs/cli-reference.md)
- [架构说明](docs/architecture.md)
- [Hermes 启发的演进路线与 TaskBoard 评测](docs/hermes-inspired-roadmap.md)
- [1.1 终端体验、可靠性增强与 1.2 优先级](docs/v1.1-design-notes.md)
- [外部审查问题复现与修复记录](docs/external-review-follow-up-2026-09-02.md)
- [工程韧性审查与极端场景测试](docs/engineering-resilience-review-2026-09-02.md)
- [2026-08-31 TaskBoard 三轮评测结果](docs/taskboard-evaluation-2026-08-31.md)
- [终端界面选型](docs/interface-strategy.md)

## 开发与测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

当前开发版本：`1.1.0`。

## License

MIT
