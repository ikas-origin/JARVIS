# JARVIS CLI 与安全参考

## 参数

| 参数 | 作用 |
|---|---|
| `--workspace PATH` | 指定允许操作的项目目录，默认当前目录 |
| `--yes` | 自动批准普通写入和命令；高风险命令仍拒绝 |
| `--allow-remote` | 确认本次可向远程模型发送任务、选中的项目内容与工具输出 |
| `--max-turns N` | 最大模型循环轮数，默认 20 |
| `--continue` | 继续当前 workspace 最近会话 |
| `--resume ID` | 恢复指定会话 |
| `--no-session` | 不保存对话历史 |
| `--no-stream` | 禁用 SSE 流式输出 |
| `--no-color` | 禁用人类输出中的 ANSI 颜色；`NO_COLOR` 环境变量具有相同作用 |
| `--json` | stdout 只输出一个稳定 JSON 对象 |
| `--version` | 显示版本 |

完整帮助：

```powershell
jarvis --help
```

## 本地工具

| 工具 | 作用 |
|---|---|
| `list_files` | 浏览 workspace 文件结构 |
| `search_text` | 按文本或正则搜索并返回文件、行号和片段 |
| `read_file` | 读取带行号的 UTF-8 文本 |
| `read_files` | 一次读取 1～8 个已知的小型相关文件，降低模型往返次数 |
| `write_file` | 创建或完整写入文件 |
| `edit_file` | 唯一精确匹配后替换文本 |
| `run_command` | 在 workspace 中运行带超时和输出限制的命令；必须声明 `purpose=inspect|verify` |

Agent 循环：

```text
用户任务 -> 模型分析 -> 工具调用 -> 本地执行 -> 回填结果
         -> 模型继续修改/测试 -> 最终回答或明确停止
```

最终结果包含轮数、工具调用数、token usage、耗时、停止原因和 session ID。

## 审批模式

默认行为：

- `list_files`、`search_text`、`read_file` 自动执行。
- 文件写入、精确编辑和本地命令逐次确认。
- 命中高风险规则的命令直接拒绝。

可信测试仓库可以使用：

```powershell
jarvis --allow-remote --yes "修复测试"
```

`--yes` 不解除危险命令限制。任务前后建议检查：

```powershell
git status
git diff
```

## JSON 输出

自动化调用：

```powershell
jarvis --allow-remote --json --no-session --yes "读取项目并报告测试命令，不修改文件。"
```

成功结果：

```json
{
  "ok": true,
  "status": "completed",
  "answer": "...",
  "turns": 3,
  "tool_calls": 2,
  "tool_usage": {"read_file": 1, "run_command": 1},
  "verification_status": "not_required",
  "stop_reason": "model_final_answer",
  "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200},
  "elapsed_seconds": 3.5,
  "session_id": null
}
```

错误使用非零退出码：

```json
{"ok": false, "error": {"type": "configuration_error", "message": "..."}}
```

JSON 模式禁用流式输出，stdout 只包含完整 JSON；进度和人类提示不会混入结果。

## 安全和隐私边界

- 模型会收到 system prompt、用户任务，以及工具读取或搜索到的代码和输出。
- 远程 Base URL 必须由用户通过 `--allow-remote` 逐次明确确认；本地模型无需确认。
- 不要在不允许发送给模型供应商的仓库中运行。
- 文件工具拒绝 workspace 外路径、符号链接越界、`.git`、常见凭据和私钥。
- `run_command` 从子进程环境移除名称疑似 key、token、secret 或 password 的变量。
- 命令受到超时、输出上限和高风险规则限制。
- Spec 模式会进一步按阶段限制写入范围和命令执行。
- 这些是应用级护栏，不是操作系统沙箱；shell 仍拥有当前用户权限。
- 只在可信且可安全修改的 Git 仓库中使用，重要项目先提交或备份。

## 完成与验证门

当 `write_file` 或 `edit_file` 成功修改普通项目文件后，JARVIS 不接受模型立即给出的“已完成”。Agent 必须在修改之后成功执行至少一次 `purpose="verify"` 的测试、构建、lint、类型检查或其它可执行验证。`purpose="inspect"` 的目录查看等探查命令和任何失败命令都不会解除验证门。`.jarvis/` 下的 Spec 状态和规划产物不触发该门，因此规划阶段仍然保持只写文档、不执行命令。

## 终端显示

交互模式启动时显示钢铁侠风格字符画和状态栏，包括 workspace、模型、Git 分支、session、运行模式、工具数、流式状态与审批策略。对话使用 `YOU` 和 `JARVIS` 分区，工具与验证事件使用独立标签输出到 stderr，避免和最终回答混在一起。

写入和编辑工具的 `content`、`old_text`、`new_text` 不会完整打印到终端事件流，只显示字符数；模型仍会收到完整结构化工具结果。终端不支持颜色、输出被重定向、设置 `NO_COLOR` 或使用 `--no-color` 时自动退化为纯文本。JSON 模式保持单一 JSON 对象，完全不包含字符画、ANSI 或状态栏。

## 开发与测试

```powershell
cd D:\path\to\JARVIS
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

内部设计见 [architecture.md](architecture.md)。
