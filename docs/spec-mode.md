# JARVIS Spec 驱动开发

Spec 模式适用于复杂、多模块或高风险功能。JARVIS 先把目标固化为需求、设计和任务，经过人工审批后才允许修改业务代码。

## 状态机

```text
requirements -> design -> tasks -> implementing -> verifying -> completed
```

每个 Spec 保存在项目中：

```text
.jarvis/specs/<name>/
├── requirements.md
├── design.md
├── tasks.md
├── verification.md
└── state.json
```

状态不依赖某个终端进程或聊天 session，可以跨进程恢复，也可以随项目提交到 Git。

## 完整流程

在目标项目启动：

```powershell
jarvis --yes
```

创建 Spec。名称只能包含小写字母、数字和连字符：

```text
/spec new health-consultation 实现健康知识咨询原型，包含风险分流、RAG、会话历史和自动测试
```

审查和修订需求：

```text
/spec show requirements
/spec revise 增加明确的非目标，并要求验收标准具有稳定 ID
/spec approve
```

审查设计与任务：

```text
/spec show design
/spec approve
/spec show tasks
/spec approve
```

逐项实现：

```text
/spec implement
/spec status
/spec implement
```

所有任务完成后执行最终验证：

```text
/spec verify
```

## 命令

| 命令 | 作用 |
|---|---|
| `/spec new NAME GOAL` | 创建 Spec 并生成 requirements |
| `/spec status` | 查看当前阶段、产物和下一个任务 |
| `/spec list` | 查看当前 workspace 的全部 Spec |
| `/spec show ARTIFACT` | 显示 requirements、design、tasks 或 verification |
| `/spec generate` | 当前阶段产物生成失败时重试 |
| `/spec revise FEEDBACK` | 修订当前规划产物 |
| `/spec approve` | 批准当前产物并进入下一阶段 |
| `/spec implement` | 实现并验证下一个未完成任务 |
| `/spec verify` | 执行最终验收并生成 verification.md |
| `/spec cancel` | 终止流程但保留产物 |

## 产物约定

`requirements.md` 描述范围、非目标、编号需求和可测试验收标准，不提前选择实现细节。

`design.md` 描述架构、模块、数据流、接口、错误处理、安全和测试策略，并映射需求 ID。

`tasks.md` 使用标准 Markdown 复选框：

```markdown
- [ ] T1 创建项目骨架
  - 对应：R1
  - 验证：应用健康检查返回 200
```

每次 `/spec implement` 只处理第一个未完成任务。Agent 必须执行验证，成功后才能把 `[ ]` 改为 `[x]`。

`verification.md` 包含需求追踪矩阵、执行命令、结果与限制。只有出现独立一行 `Status: PASS`，状态机才进入 completed。

## 强制约束

审批门由工具策略执行，不只是提示词：

- requirements、design 和 tasks 阶段禁止运行命令。
- 规划阶段只能写当前待审查的 Spec 文件。
- tasks 批准前禁止修改业务代码。
- 实施阶段保护已批准的 requirements、design、verification 和内部状态。
- `state.json` 对模型文件工具不可见。
- 活跃 Spec 期间拒绝流程外的自由任务。
- 最终验证失败会回到 implementing，并新增 `TV<n>` 修复任务。

当前每个 workspace 同时只允许一个未结束 Spec。完成或取消的 Spec 会保留，以便审计。

## 什么时候不需要 Spec

以下任务直接使用普通模式更高效：

- 修改拼写或文案
- 增加一个小测试
- 修复明确的局部 bug
- 解释代码而不修改

涉及多个模块、需求仍需讨论、验收严格或风险较高时，应使用 Spec 模式。
