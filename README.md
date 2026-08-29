# JARVIS

JARVIS 是一个轻量级 Coding Agent（可以理解为简易版 Claude Code）：用户给出编程任务后，它会调用大语言模型，自主搜索和读取代码、修改文件、执行本地命令、观察测试结果并继续迭代，直到完成任务或触发明确的终止条件。

项目自行实现 agent loop、对话历史与上下文管理、工具定义与本地执行、模型输出解析、循环终止和错误处理，不使用 LangChain、OpenAI Agents SDK、Claude Agent SDK 等 agent 框架，也不依赖服务端代码执行工具。

## 1. 环境要求

- Python 3.11 或更高版本
- 支持 OpenAI Chat Completions 和原生 tool calling 的模型接口
- 当前已经使用 DeepSeek `deepseek-v4-flash` 完成真实联调

## 2. 安装

在 PowerShell 中进入 JARVIS 仓库：

```powershell
cd D:\develop\CodeX\test20260829020730\JARVIS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

安装后检查命令：

```powershell
jarvis --version
jarvis --help
```

如果 PowerShell 不允许激活虚拟环境，可以不修改执行策略，直接使用：

```powershell
.\.venv\Scripts\jarvis.exe --help
```

## 3. 配置模型

### 推荐：持久化交互配置

运行：

```powershell
jarvis configure
```

使用 DeepSeek 时依次填写：

```text
API key: 粘贴 DeepSeek API key（输入内容不会显示）
Model: deepseek-v4-flash
Base URL: https://api.deepseek.com
```

配置保存在用户目录，而不是 Git 仓库：

```text
C:\Users\你的用户名\.jarvis\config.json
```

关闭终端或重启电脑后仍然有效。JARVIS 不提供 `--api-key` 参数，避免 key 出现在命令历史或进程列表中。

### 手动配置文件

也可以手动创建 `C:\Users\你的用户名\.jarvis\config.json`：

```json
{
  "api_key": "填写你的 API key",
  "model": "deepseek-v4-flash",
  "base_url": "https://api.deepseek.com"
}
```

不要把真实 key 写入本仓库、README、截图或演示视频。

### 临时环境变量

环境变量只对当前终端及其子进程有效，优先级高于配置文件：

```powershell
$env:JARVIS_API_KEY = "your-api-key"
$env:JARVIS_MODEL = "deepseek-v4-flash"
$env:JARVIS_BASE_URL = "https://api.deepseek.com"
```

配置优先级：

```text
环境变量 > ~/.jarvis/config.json > 内置默认值
```

### 验证配置

```powershell
jarvis doctor
jarvis --json doctor
```

正常结果应包含：

```json
{
  "ok": true,
  "auth": {"available": true, "source": "config"},
  "model": "deepseek-v4-flash",
  "base_url": "https://api.deepseek.com",
  "transport_secure": true
}
```

`doctor` 只检查本地配置，不会打印 key，也不会发起模型请求或消耗额度。

## 4. 使用 JARVIS 进行 Coding

### 方式一：在目标项目目录进入交互终端（推荐）

这也是 JARVIS 的主界面：激活虚拟环境，进入需要修改的项目，再直接运行 `jarvis`：

```powershell
& D:\develop\CodeX\test20260829020730\JARVIS\.venv\Scripts\Activate.ps1
cd D:\path\to\your-project
git status
jarvis
```

当前目录自动成为 workspace。启动页会显示模型、Git 分支、session 和审批模式。在 `you>` 后直接描述任务：

```text
you> 阅读项目，定位失败的测试，修复问题并重新运行测试。不要修改无关文件。
```

| 命令 | 作用 |
|---|---|
| `/help` | 显示会话内命令 |
| `/status` | 显示 workspace、模型、Git、session 和上下文状态 |
| `/sessions` | 列出已保存会话 |
| `/clear` | 清空当前对话上下文，不修改项目文件 |
| `/exit` | 退出 JARVIS |

默认会在写文件和执行命令前询问。可信测试项目可用 `jarvis --yes` 启动，自动批准普通操作；危险命令仍会被拒绝。

### 方式二：一次性执行任务

适合脚本、评测或目标非常明确的任务：

```powershell
jarvis --yes "检查项目并修复失败的测试，完成后报告修改和验证结果。"
```

### 方式三：不激活虚拟环境

直接调用 JARVIS 的可执行文件，并显式指定目标项目：

```powershell
D:\develop\CodeX\test20260829020730\JARVIS\.venv\Scripts\jarvis.exe `
  --workspace D:\path\to\your-project `
  --yes `
  "检查项目并修复失败的测试，完成后报告修改和验证结果。"
```

## 可选实验性图形启动器

JARVIS 以终端交互为主。仓库仍保留早期 Tkinter GUI，用于选择目录和启动一次性任务，但它不是推荐界面，也不计划在本次三天开发周期内扩展成完整桌面 IDE。

```powershell
cd D:\develop\CodeX\test20260829020730\JARVIS
.\.venv\Scripts\jarvis-gui.exe
```

也可以在资源管理器中双击：

```text
scripts\start-jarvis-gui.cmd
```

GUI 的使用顺序：

1. 点击 `Browse...` 选择需要开发的项目目录。
2. 在 `Coding task` 中输入任务和验收要求。
3. 可信测试项目可勾选“自动批准普通写入和命令”；不勾选时写入和命令会被拒绝，读取仍可执行。
4. 如需沿用该项目最近的上下文，勾选“继续当前项目最近会话”。
5. 点击 `Run JARVIS`，在下方实时查看模型和工具输出。
6. 需要中止时点击 `Stop`。

点击 `Check config` 可以运行配置诊断。GUI 不包含另一套 agent 实现，它通过参数列表启动同一个 `jarvis` CLI，因此工具、安全规则、会话和终止条件完全一致。

界面路线的调研与取舍见 [docs/interface-strategy.md](docs/interface-strategy.md)。

### 可选：资源管理器右键菜单

希望在文件夹上右键选择 `Open JARVIS here` 时，可手动运行：

```powershell
cd D:\develop\CodeX\test20260829020730\JARVIS
.\scripts\install-explorer-menu.ps1
```

脚本只修改当前用户的资源管理器菜单，不需要管理员权限。卸载：

```powershell
.\scripts\install-explorer-menu.ps1 -Uninstall
```

右键菜单安装是可选操作；阅读脚本并确认路径后再运行。JARVIS 不会自动修改注册表。

## 5. 如何写好 Coding 任务

任务最好同时说明目标、验收方式和禁止修改的范围。例如：

```powershell
jarvis --yes "修复 slugify 对连续空格和中文输入处理错误的问题；补充边界测试并运行完整测试套件，不要修改无关模块。"
```

```powershell
jarvis --yes "阅读 src/parser.py 和现有测试，为空输入增加明确错误处理；保持公开 API 兼容，运行所有测试。"
```

```powershell
jarvis --yes "找出这个项目为什么无法启动，先读取配置和错误日志，再做最小修改并运行启动检查。"
```

适合的任务包括：

- 定位并修复 bug
- 实现小型功能并补测试
- 根据测试或构建错误迭代修复
- 搜索调用关系并解释代码
- 小范围重构并运行回归测试
- 创建简单项目骨架

第一版不适合一次完成大型跨仓库迁移、多智能体任务或需要浏览器操作的工作。

## 6. 审批与安全模式

默认行为：

- `list_files`、`search_text`、`read_file` 自动执行
- 写文件、精确编辑和本地命令逐次请求确认
- 命中高风险规则的命令直接拒绝

在可信的测试仓库中，可以使用 `--yes` 自动批准普通写入和命令：

```powershell
jarvis --yes "修复测试"
```

`--yes` 不会解除危险命令拒绝。建议开始任务前确认 Git 工作区状态，任务结束后审查 diff：

```powershell
git status
git diff
```

## 7. 会话保存与恢复

会话默认保存在：

```text
~/.jarvis/sessions
```

查看会话：

```powershell
jarvis sessions
jarvis --json sessions
```

继续当前 workspace 最近的会话：

```powershell
jarvis --continue --yes "继续上次工作，补充剩余边界测试。"
```

恢复指定会话：

```powershell
jarvis --resume SESSION_ID --yes "继续之前的任务。"
```

执行不保存历史的一次性任务：

```powershell
jarvis --no-session --yes "只检查测试失败原因，不修改文件。"
```

会话严格绑定 workspace，不能在另一个项目中误恢复。

## 8. 常用参数

| 参数 | 作用 |
|---|---|
| `--workspace PATH` | 指定允许操作的项目目录，默认是当前目录 |
| `--yes` | 自动批准普通写入和命令，高风险命令仍拒绝 |
| `--max-turns N` | 限制模型循环轮数，默认 20 |
| `--continue` | 继续当前 workspace 最近会话 |
| `--resume ID` | 恢复指定会话 |
| `--no-session` | 不保存本次对话历史 |
| `--no-stream` | 禁用 SSE 流式显示，等待完整响应 |
| `--json` | stdout 只输出一个稳定 JSON 对象 |

完整说明：

```powershell
jarvis --help
```

## 9. 工具与运行过程

JARVIS 当前提供六个本地工具：

- `list_files`：查看项目文件结构
- `search_text`：按文本或正则搜索代码，返回文件和行号
- `read_file`：读取带行号的 UTF-8 文本
- `write_file`：创建或完整写入文件
- `edit_file`：要求旧文本唯一匹配后精确替换
- `run_command`：在 workspace 中运行带超时和输出限制的命令

典型循环：

```text
用户任务 → 模型分析 → 调用本地工具 → 回填工具结果
        → 模型继续分析/修改/测试 → 最终回答或明确停止
```

任务完成后会显示模型轮数、工具调用数、token usage、耗时、停止原因和 session ID。

## 10. JSON 输出

脚本或自动化场景使用：

```powershell
jarvis --json --no-session --yes "读取项目并报告测试命令，不修改文件。"
```

`--json` 禁用流式输出，stdout 始终只有一个 JSON 对象。成功结果包含：

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

错误使用非零退出码和稳定结构：

```json
{"ok": false, "error": {"type": "configuration_error", "message": "..."}}
```

## 11. 隐私和安全边界

- 模型为了完成任务，会收到 system prompt、用户任务，以及通过工具读取或搜索到的相关代码和输出。不要在不允许发送给模型供应商的私有仓库中运行。
- 文件工具拒绝 workspace 外路径、符号链接越界、`.git` 元数据、常见凭据文件和私钥。
- `run_command` 会移除名称疑似 key、token、secret 或 password 的子进程环境变量。
- 命令有超时、输出上限和高风险拒绝规则。
- 这些措施是应用级护栏，不是容器或操作系统沙箱；shell 命令仍拥有当前用户的系统权限。
- 只在可信任务和可以安全修改的 Git 仓库中使用；重要项目先建立提交或备份。

## 12. 常见问题

### 找不到 `jarvis` 命令

先激活虚拟环境，或者直接使用完整路径：

```powershell
D:\develop\CodeX\test20260829020730\JARVIS\.venv\Scripts\jarvis.exe --help
```

### `doctor` 显示配置缺失

重新运行：

```powershell
jarvis configure
```

确认配置文件不是误命名为 `config.json.txt`。

### 认证失败

检查 API key 是否完整、是否已失效。不要把 key 粘贴到 issue、聊天或日志中，必要时在供应商控制台作废并重新生成。

### 请求失败或余额不足

检查模型名称、Base URL、账户余额和网络连接。DeepSeek 推荐配置为：

```text
model: deepseek-v4-flash
base_url: https://api.deepseek.com
```

### 流式输出不兼容

使用非流式回退：

```powershell
jarvis --no-stream --yes "你的任务"
```

## 13. 开发与测试

```powershell
cd D:\develop\CodeX\test20260829020730\JARVIS
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m unittest discover -s tests -v
```

架构说明见 [docs/architecture.md](docs/architecture.md)。

## License

MIT
