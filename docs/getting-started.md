# JARVIS 安装与使用

## 环境要求

- Python 3.11 或更高版本
- 支持 OpenAI Chat Completions 与原生 tool calling 的模型接口
- Windows PowerShell；其它系统也可通过 Python console script 使用

项目已经使用 DeepSeek `deepseek-v4-flash` 完成真实联调。

## 安装

在 PowerShell 中进入 JARVIS 仓库：

```powershell
cd D:\path\to\JARVIS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

检查安装：

```powershell
jarvis --version
jarvis --help
```

如果 PowerShell 不允许激活虚拟环境，可以直接使用：

```powershell
.\.venv\Scripts\jarvis.exe --help
```

## 配置模型

推荐运行交互式持久化配置：

```powershell
jarvis configure
```

DeepSeek 示例：

```text
API key: 粘贴 DeepSeek API key（输入不会显示）
Model: deepseek-v4-flash
Base URL: https://api.deepseek.com
```

配置保存在仓库外的用户目录：

```text
C:\Users\你的用户名\.jarvis\config.json
```

关闭终端或重启电脑后仍然有效。JARVIS 不提供 `--api-key` 参数，避免凭据进入命令历史或进程列表。

也可以手动创建配置：

```json
{
  "api_key": "填写你的 API key",
  "model": "deepseek-v4-flash",
  "base_url": "https://api.deepseek.com"
}
```

临时环境变量优先于配置文件：

```powershell
$env:JARVIS_API_KEY = "your-api-key"
$env:JARVIS_MODEL = "deepseek-v4-flash"
$env:JARVIS_BASE_URL = "https://api.deepseek.com"
```

配置优先级：

```text
环境变量 > ~/.jarvis/config.json > 内置默认值
```

验证配置：

```powershell
jarvis doctor
jarvis --json doctor
```

`doctor` 只检查本地配置，不打印 API key，也不发起模型请求。

## 在项目中使用

激活 JARVIS 环境，进入需要修改的项目，然后启动交互终端：

```powershell
& D:\path\to\JARVIS\.venv\Scripts\Activate.ps1
cd D:\path\to\your-project
git status
jarvis
```

当前目录自动成为 workspace：

```text
you> 阅读项目，定位失败的测试，修复问题并重新运行测试。不要修改无关文件。
```

交互命令：

| 命令 | 作用 |
|---|---|
| `/help` | 显示命令 |
| `/status` | 显示 workspace、模型、Git、session 和上下文状态 |
| `/sessions` | 列出已保存会话 |
| `/clear` | 清空当前对话上下文，不修改项目文件 |
| `/spec` | 管理 Spec 驱动流程 |
| `/exit` | 退出 JARVIS |

一次性执行任务：

```powershell
jarvis --yes "检查项目并修复失败的测试，完成后报告修改和验证结果。"
```

不激活环境时可以使用完整路径：

```powershell
D:\path\to\JARVIS\.venv\Scripts\jarvis.exe `
  --workspace D:\path\to\your-project `
  --yes `
  "检查项目并修复失败的测试。"
```

## 编写任务

任务最好包含目标、验收方式与禁止修改范围：

```powershell
jarvis --yes "修复 slugify 对连续空格和中文输入的处理；补充边界测试并运行完整测试，不要修改无关模块。"
```

```powershell
jarvis --yes "阅读 src/parser.py 和现有测试，为空输入增加明确错误处理；保持公开 API 兼容，运行所有测试。"
```

普通模式适合修复 bug、小型功能、测试补充、小范围重构和代码解释。复杂多模块功能建议使用 [Spec 模式](spec-mode.md)。

## 会话保存与恢复

会话默认保存到 `~/.jarvis/sessions`，并严格绑定 workspace。

```powershell
jarvis sessions
jarvis --continue --yes "继续上次工作。"
jarvis --resume SESSION_ID --yes "继续指定会话。"
jarvis --no-session --yes "只执行这一次任务。"
```

## 可选 GUI

终端是推荐界面。仓库保留了实验性 Tkinter 启动器：

```powershell
.\.venv\Scripts\jarvis-gui.exe
```

或双击 `scripts\start-jarvis-gui.cmd`。GUI 只是同一 CLI 的薄启动层，没有第二套 Agent 实现。

使用步骤：

1. 选择需要开发的项目目录。
2. 输入任务和验收要求。
3. 按需启用普通写入和命令自动批准。
4. 如需沿用上下文，选择继续当前项目最近会话。
5. 启动 JARVIS，在输出区查看模型与工具过程。
6. 使用 Stop 中止运行，或用 Check config 检查模型配置。

资源管理器右键菜单为可选功能，确认脚本路径后手动安装：

```powershell
.\scripts\install-explorer-menu.ps1
.\scripts\install-explorer-menu.ps1 -Uninstall
```

JARVIS 不会自动修改注册表。界面路线见 [interface-strategy.md](interface-strategy.md)。

## 常见问题

### 找不到 `jarvis`

激活 `.venv`，或直接使用 `.venv\Scripts\jarvis.exe`。

### `doctor` 显示配置缺失

重新运行 `jarvis configure`，并确认配置文件没有被命名为 `config.json.txt`。

### 认证或余额错误

检查 API key、模型名、Base URL、账户余额和网络。不要在日志、截图、Issue 或仓库中暴露真实 key。

### 流式输出不兼容

```powershell
jarvis --no-stream --yes "你的任务"
```
