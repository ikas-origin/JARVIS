# TaskBoard 端到端评测（2026-08-31）

## 结论

JARVIS 使用 DeepSeek `deepseek-v4-flash` 在原始 `testJARVIS` 上完成修复，随后从 Git 标签 `demo-bug-start` 创建三个互不共享修改的本地 clone。三轮均从固定的 9 项测试、3 项失败开始，最终测试退出码全部为 0，重复成功率为 3/3。

评测提示要求先复现、定位三个根因、做最小修改、补充边界测试、不得删除或弱化测试，并在完成后运行完整测试。

## 结果

| Run | 最终测试 | Turns | Tool calls | Total tokens | Elapsed |
|---|---:|---:|---:|---:|---:|
| 原始仓库真实修复 | 13/13 | 10 | 21 | 90,774 | 46.047s |
| 隔离评测 1 | 15/15 | 10 | 21 | 107,426 | 51.688s |
| 隔离评测 2 | 14/14 | 10 | 20 | 99,010 | 40.110s |
| 隔离评测 3 | 15/15 | 13 | 25 | 155,115 | 53.797s |
| 三轮平均 | — | 11.0 | 22.0 | 120,517 | 48.532s |

三轮 prompt cache hit token 合计 308,096，占三轮 prompt token 的约 89.5%。虽然缓存命中较高，小项目的累计 token 仍偏大，后续应根据新增的 `tool_usage` 指标定位重复读取和低效命令。

## 修改质量

四次运行都定位到相同的三个根因：

1. 标题搜索使用大小写敏感的子串判断。
2. 截止日期使用严格 `<`，遗漏“今天到期”。
3. `TaskNotFound` 被错误映射为 HTTP 500。

业务代码修改始终集中在 `taskboard/service.py` 和 `taskboard/api.py`，测试只新增、不删除。新增测试覆盖反向大小写、昨天/明天日期边界、已完成或无日期任务、成功状态更新以及非法状态等。三份隔离 diff 均未修改数据库、模型、前端或其它无关文件。

## 评测暴露并已修复的问题

- Windows 管道中的中文 JSON 曾按 GBK 输出、被 UTF-8 消费者错误解码。CLI 现会固定 stdout/stderr 为 UTF-8，真实单轮模型调用已验证返回 `中文编码正常。`。
- 原结果只有工具总数，无法分析具体成本。`AgentResult` 现增加 `tool_usage`。
- 原结果不能区分是否触发过写后验证。现增加 `verification_status`，值为 `not_required`、`required` 或 `passed`。
- 评测产物最初可能写入被测 clone。脚本现将 `workspace/` 与 artifacts 分离，Agent 看不到评测日志，失败 JSON 也能稳定汇总。

## 可复核产物

本次三轮原始产物位于被 Git 忽略的：

```text
.eval-runs/taskboard-20260831-105246/
```

每轮包含基线测试、最终测试、模型 JSON、完整 diff 和摘要；总报告为 `report.json`。自动化入口是 `scripts/evaluate-taskboard.ps1`。

## 下一步判断

当前优先级不应是继续增加界面或消息平台，而应降低相同任务的 token 与工具调用成本。下一轮候选是批量只读工具、项目内 todo 状态和 Git worktree 隔离；每项必须再次通过三轮固定基准，不能只依赖单元测试。
