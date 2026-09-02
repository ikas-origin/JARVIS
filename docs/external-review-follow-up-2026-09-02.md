# 外部审查问题复现与修复记录（2026-09-02）

## 审查结论

外部审查在 Linux、Python 3.11.15 的独立虚拟环境中完成了 68 项基线测试、CLI、Spec、本地模拟模型和安全策略验证。审查发现一个确定缺陷，并给出一个 Linux 使用注意点：

1. `--no-stream` 与 `--json` 的模型请求仍然携带 `stream: true`；普通 JSON 端点会因为没有 SSE `[DONE]` 而失败。
2. 未激活虚拟环境、直接执行 `.venv/bin/jarvis` 时，工具命令中的 `python` 可能不在 `PATH`。

## 流式开关缺陷

### 复现

CLI 已正确计算 `stream=False` 并传给 `Agent`，但模型客户端仍观察到非空回调，因此请求体为：

```json
{"stream": true, "stream_options": {"include_usage": true}}
```

普通 JSON 端点返回完整对象后，被错误地交给 SSE 解析器，最终报告缺少 `[DONE]`。

### 根因

原实现把条件写在 lambda 的函数体中：

```python
lambda delta: emit(delta) if self.stream else None
```

这段表达式无论 `self.stream` 为何值，传给客户端的参数始终是一个 lambda 对象。客户端使用 `on_text_delta is not None` 判断是否流式，因此始终得到 `True`。

### 修复

条件现在用于选择“回调或 None”：

```python
on_text_delta = (lambda delta: emit(delta)) if self.stream else None
```

协议行为变为：

| CLI 模式 | callback | 请求体 |
|---|---|---|
| 默认人类输出 | callable | `stream: true` + `stream_options` |
| `--no-stream` | `None` | `stream: false` |
| `--json` | `None` | `stream: false` |

## 未激活虚拟环境

工具子进程仍会继承经过敏感变量过滤的环境，但现在会把 `sys.executable` 所在目录放到 `PATH` 首位。Linux 下直接执行 `.venv/bin/jarvis` 时，`python` 因而解析为同一个 `.venv/bin/python`；Windows 下对应 `.venv\Scripts\python.exe`。

这不是操作系统沙箱，也不会改变 workspace、安全审批或危险命令规则。它只保证 Agent 自身与 Agent 启动的 Python 命令使用一致的解释器环境。

## 回归证据

新增自动化测试覆盖：

- `--json` 和 `--no-stream` 传给模型客户端的 callback 必须是 `None`；
- 非流式客户端请求必须包含 `stream: false` 且不包含 `stream_options`；
- 即使父进程 `PATH` 为空，`run_command` 仍可找到当前 JARVIS 的 Python；
- 原有流式 SSE 拼接、`[DONE]`、畸形事件和工具调用解析测试继续保留。

这个问题说明终端是否显示增量文本、Agent 是否传递回调、HTTP 请求是否使用 SSE 是三层不同状态，不能只通过 CLI 状态栏判断。测试需要一直验证到实际客户端请求体。
