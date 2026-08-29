# JARVIS 界面路线与产品对照

## 结论

JARVIS 采用“终端优先、一次性命令与 JSON 并存、GUI 仅作可选启动器”的路线。用户进入目标仓库后运行 `jarvis`，在同一个交互会话中让 Agent 读取、修改、执行和验证代码。

这不是把普通聊天框搬进终端，而是让交互界面贴近 Agent 真正工作的环境：当前目录、Git 状态、本地文件和命令行。

## 主流产品并非只有一种界面

| 入口 | 代表产品 | 更适合的工作 |
|---|---|---|
| CLI / TUI | Claude Code、Codex CLI、Aider、OpenCode | 直接操作本地仓库、shell、Git，连续迭代 |
| IDE / 编辑器 | Cursor、Cline、Copilot | 选区修改、内联补全、可视化 diff、编辑器上下文 |
| Web / 云端 | Codex web、Claude Code on the web 等 | 异步委派、远端沙箱、生成 PR |
| Desktop | Claude Desktop、OpenCode Desktop 等 | 多会话管理和更完整的图形工作台 |

同一产品经常同时提供多种入口。Claude Code 官方文档列出 terminal、IDE、desktop、web 和 CI/CD，但其本地工作流仍从项目目录运行；Codex 同样覆盖 terminal、IDE 和云端。OpenRouter 的 Coding Apps 页面是产品聚合与排行，不代表这些产品都使用 Web 界面。

参考资料：

- [OpenRouter Coding Apps](https://openrouter.ai/apps/category/coding)
- [Claude Code 工作原理](https://code.claude.com/docs/en/how-claude-code-works)
- [OpenAI Codex CLI](https://help.openai.com/en/articles/11096431)
- [Cursor 文档](https://cursor.com/docs) 与 [Cursor CLI](https://docs.cursor.com/en/cli/overview)
- [Cline 官方仓库](https://github.com/cline/cline)
- [Aider 官方文档](https://aider.chat/docs/)
- [OpenCode 官方仓库](https://github.com/anomalyco/opencode)

## 为什么 JARVIS 选择终端优先

1. 题目要求展示的核心是 Agent 自主循环、上下文、工具执行、输出解析、停止条件和错误处理。终端能最直接地展示每轮模型决策和工具轨迹。
2. JARVIS 的工具都运行在本地 workspace。Web 方案还需要本地守护进程、浏览器与本地桥接、鉴权和额外安全边界，三天内会稀释核心实现。
3. IDE 插件体验很好，但要处理编辑器 API、扩展打包、diff UI 和版本兼容。它适合作为后续入口，不适合作为当前交付的核心。
4. Qt/Tkinter 独立窗口不能天然获得比终端更多的代码上下文；如果不实现编辑器、diff、终端模拟器和会话工作台，它只是在 CLI 外再包一层表单。
5. 终端入口跨编辑器工作。VS Code、PyCharm、Windows Terminal 或其他 IDE 的集成终端都可以直接运行它。

## 本阶段仿照的交互原则

- 像 Claude Code/Aider 一样，在目标项目目录直接启动。
- 启动时明确展示 workspace、模型、Git 分支、session 和审批状态。
- 自然语言任务与 `/help`、`/status`、`/sessions`、`/clear`、`/exit` 控制命令共用一个 REPL。
- 工具执行轨迹可见，最终结果包含轮次、工具数、token、耗时和停止原因。
- 同一核心同时支持交互式、人类可读的一次性命令和机器可读 JSON，方便演示、测试和自动化。
- GUI 保留但降级为实验性入口，不在本阶段继续投入。

## 后续优先级

1. 终端中的多行输入、任务中断和更清晰的 diff 审批。
2. 项目级 `JARVIS.md` 指令与 `@文件` 显式上下文。
3. 非交互模式的事件流 JSON，方便 CI 或其它前端复用。
4. 复用 CLI/事件协议制作 VS Code 薄插件。
5. 只有在需要并行远端任务时，再设计 Web 服务与本地/云端执行隔离。
