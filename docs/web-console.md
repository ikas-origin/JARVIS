# 实验性本地 Web 控制台

## 定位

`jarvis-web` 是 JARVIS 的 localhost 界面，不是第二套 Agent，也不是云端代码执行服务。它直接复用 `Agent`、`ToolRegistry`、`Policy`、`SessionStore` 和模型客户端，因此终端版与 Web 版具有相同的工具、workspace 边界、验证门和停止条件。

浏览器负责展示用户任务、模型增量、工具轨迹、验证状态和审批请求；模型调用、文件访问和命令执行始终发生在启动 `jarvis-web` 的本机进程中。

## 启动

先安装当前开发版本并完成模型配置：

```powershell
cd D:\path\to\JARVIS
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
jarvis doctor
```

在指定项目上启动：

```powershell
jarvis-web --workspace D:\path\to\project --allow-remote
```

默认打开 `http://127.0.0.1:8765`。实际 URL 带有一次启动生成的随机 token，页面会将 token 保存到当前标签页的 `sessionStorage` 并从地址栏移除。

常用参数：

| 参数 | 作用 |
|---|---|
| `--workspace PATH` | 固定本次服务能够操作的项目目录 |
| `--port PORT` | localhost 端口，默认 `8765`；`0` 表示自动选择 |
| `--allow-remote` | 明确允许向远程模型发送任务、选定源码和工具输出 |
| `--yes` | 自动批准普通写入和命令；危险命令仍会拒绝 |
| `--no-session` | 不保存本次多轮历史 |
| `--no-open` | 只打印 URL，不自动打开浏览器 |
| `--max-turns N` | 单个任务最大模型轮次 |

不使用 `--yes` 时，写文件、编辑文件和执行命令会在时间线中显示审批卡片。批准只对当前动作有效；五分钟没有处理会按拒绝处理。

## 运行模型

一个 `WebRuntime` 只持有一个 Agent，并通过单 worker 串行执行任务。同一 workspace 有任务处于 `queued`、`running` 或 `waiting_approval` 时，第二个请求返回 HTTP 409，而不是并发修改项目。

```text
Browser
  │  token-protected localhost JSON API
  ▼
WebRuntime ── one active task ──> existing Agent.run
  │                                  │
  ├─ browser approval <── Policy     ├─ context/session
  └─ bounded event timeline <────────└─ model/tool/verify events
```

前端以 350 ms 间隔增量拉取带序号的事件。模型仍使用原有 SSE 客户端，所以生成文本会逐段出现在浏览器；Web API 自身暂时采用增量轮询，避免为首个实验版本复制复杂的断线重连协议。

## 安全边界

- 服务固定绑定 `127.0.0.1`，没有监听局域网或公网的参数。
- 所有 `/api/` 请求必须携带随机 `X-JARVIS-Token`。
- API 请求体上限为 64 KiB，任务文本上限为 20,000 字符。
- 静态文件只允许固定白名单，不接受任意磁盘路径。
- 页面设置 CSP、`nosniff`、`no-referrer` 和 `no-store`。
- 工具事件不会回显写入正文、旧文本或新文本，只显示字符数。
- `--yes` 不解除危险命令拒绝规则。
- 这些仍是应用级护栏；本地 shell 拥有启动 JARVIS 的用户权限。

不要把端口通过代理、端口转发或隧道暴露到公网。若未来需要远程访问，应先增加用户认证、TLS、CSRF/Origin 校验、任务级取消、workspace 隔离和审计日志。

## 为什么不把核心部署到 Netlify

Netlify 很适合部署静态界面、普通 API 和流式响应，但 JARVIS 的核心任务需要访问用户选定的本机 workspace，并启动本地测试、构建和 Git 命令。云端 Function 无法直接获得这些本机能力；同步 Function 的执行时长也不适合完整 Coding Agent 任务。

因此当前不添加 `netlify.toml` 或 Functions：部署一个只能聊天、不能修改本地项目的页面会改变产品定义。后续如需 Netlify，可把静态 UI 作为预览站点，同时设计经过认证的本地 daemon 协议；该协议不能在没有威胁模型和权限隔离的情况下临时开放。

## 测试

```powershell
python -m unittest tests.test_web -v
python -m unittest discover -s tests -v
```

专项测试覆盖：

- 状态接口不暴露 API key；
- 同一 workspace 只允许一个运行任务；
- 浏览器审批可以解除写入和验证动作；
- 写入后仍必须通过验证门；
- 静态页面包含 CSP；
- API 缺少或使用错误 token 时返回 401。
