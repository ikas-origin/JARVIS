# JARVIS CLI 与安全参考

## 参数

| 参数 | 作用 |
|---|---|
| `--workspace PATH` | 指定允许操作的项目目录，默认当前目录 |
| `--yes` | 自动批准普通写入和命令；高风险命令仍拒绝 |
| `--max-turns N` | 最大模型循环轮数，默认 20 |
| `--continue` | 继续当前 workspace 最近会话 |
| `--resume ID` | 恢复指定会话 |
| `--no-session` | 不保存对话历史 |
| `--no-stream` | 禁用 SSE 流式输出 |
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
| `write_file` | 创建或完整写入文件 |
| `edit_file` | 唯一精确匹配后替换文本 |
| `run_command` | 在 workspace 中运行带超时和输出限制的命令 |

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
jarvis --yes "修复测试"
```

`--yes` 不解除危险命令限制。任务前后建议检查：

```powershell
git status
git diff
```

## JSON 输出

自动化调用：

```powershell
jarvis --json --no-session --yes "读取项目并报告测试命令，不修改文件。"
```

成功结果：

```json
{
  "ok": true,
  "status": "completed",
  "answer": "...",
  "turns": 3,
  "tool_calls": 2,
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
- 不要在不允许发送给模型供应商的仓库中运行。
- 文件工具拒绝 workspace 外路径、符号链接越界、`.git`、常见凭据和私钥。
- `run_command` 从子进程环境移除名称疑似 key、token、secret 或 password 的变量。
- 命令受到超时、输出上限和高风险规则限制。
- Spec 模式会进一步按阶段限制写入范围和命令执行。
- 这些是应用级护栏，不是操作系统沙箱；shell 仍拥有当前用户权限。
- 只在可信且可安全修改的 Git 仓库中使用，重要项目先提交或备份。

## 开发与测试

```powershell
cd D:\path\to\JARVIS
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

内部设计见 [architecture.md](architecture.md)。
