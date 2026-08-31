# JARVIS：Hermes 启发的演进路线

## 原则

JARVIS 的目标仍然是小型、可解释的 Coding Agent，不复制 Hermes 的消息平台、语音和个人助理功能。借鉴重点放在能提高代码任务成功率、可恢复性和持续学习能力的机制。

官方参考：

- [Hermes Agent 架构](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)
- [Agent Loop Internals](https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop)
- [Context Files](https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files)
- [Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [Persistent Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)
- [CLI / Worktree](https://hermes-agent.nousresearch.com/docs/user-guide/cli)

## 已落地：0.3～0.3.1

1. 项目上下文：兼容 JARVIS、AGENTS、Claude Code 和 Cursor 的根目录约定文件，按优先级、有界注入。
2. 验证闭环：源码写入后若没有成功命令，模型不能直接宣布完成；失败测试不会被当作验证成功。
3. 数据边界：远程模型调用要求显式 `--allow-remote`，`doctor` 标明 endpoint 是 local 或 remote，并解释可能发送的数据。
4. 原有能力保留：workspace 策略、危险命令拒绝、会话 checkpoint、上下文轨迹成组裁剪、Spec 阶段权限均继续生效。
5. 批量只读：`read_files` 在不扩大路径权限的前提下降低多文件检查的模型往返；TaskBoard 三轮对照保持 3/3，并将平均工具调用从 22.0 降到 17.7。

## 下一阶段：可靠 Coding

按优先级推进：

1. 可重复评测：固定仓库与 Git 标签、统一任务提示、记录成功率、轮次、工具调用、token 和耗时；连续运行至少三次再判断回归。
2. Git worktree 隔离：每个任务在独立 worktree 工作，保留用户工作区；清理必须只处理干净且无独有提交的 worktree。
3. 结构化任务状态：增加 Agent 内部 todo 工具，区分 pending、in progress、verified，避免长任务遗忘验收项。
4. 渐进式上下文：访问子目录时发现更具体的 `AGENTS.md`，一次会话中每个目录只检查一次，避免 prompt 膨胀。
5. 上下文压缩：保留最近轨迹和工具调用对，对中间历史做摘要；摘要前写 checkpoint，记录压缩次数。

## 再下一阶段：可审阅的学习

1. 会话检索：将会话从独立 JSON 迁移到 SQLite + FTS，按 workspace 检索历史问题和成功命令。
2. 项目记忆：仅保存稳定的测试命令、架构事实和用户明确偏好，设严格容量上限，不保存源码、密钥或一次性任务细节。
3. Skills：把可复用的多步开发流程存为按需加载的 Markdown；创建和修改先形成 diff，默认等待人工批准。
4. 后台复盘：主任务结束后用只读文件工具分析轨迹，提出 memory/skill 候选，不允许后台过程直接修改业务代码或执行任意命令。

## 暂不采用

- 消息平台 Gateway、Cron、语音、桌面应用：偏离三天考核中的 Coding Agent 核心。
- 默认并发写工具：会破坏修改顺序，首选串行写入；未来仅并发无副作用的读取。
- 无审批自我改写 Agent 源码：学习结果应先暂存并展示 diff，避免一次偶然成功永久污染行为。
- 用“生成了最终回答”代替任务完成：代码任务必须有可执行验证证据。

## 评测门槛

每项新机制至少满足：

- JARVIS 自身单元测试全部通过。
- 固定 TaskBoard 基准连续三次完成，初始 3 个失败最终变为 9 项通过。
- 不删除、跳过或弱化基准测试。
- 每次运行保留 JSON 结果和 Git diff；失败应有明确 stop reason，不能静默成功。
- 新增机制在关闭或不适用时不破坏 Spec 规划阶段和本地模型使用。

TaskBoard 自动评测：

```powershell
.\scripts\evaluate-taskboard.ps1 `
  -Repository ..\testJARVIS `
  -Runs 3 `
  -AllowRemote
```

脚本从 `demo-bug-start` 为每次运行创建独立本地 clone，并将 `agent-result.json`、修复前后测试、`changes.diff`、单次摘要和汇总报告保存到被 Git 忽略的 `.eval-runs/`。它不修改原始 `testJARVIS`；没有 `-AllowRemote` 时会在任何 clone 或模型调用前停止。
