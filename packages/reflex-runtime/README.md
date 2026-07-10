# reflex-runtime

`reflex-runtime` 是 Reflex Next 给桌面宿主调用的 Python Sidecar。

当前职责：

- 通过 stdin 接收 NDJSON 命令信封；
- 通过 stdout 输出机器可解析事件信封；
- 将诊断信息写入脱敏 stderr；
- 管理 `optimize`、`cancel`、`ping`、`shutdown` 命令；
- 通过私有 `configure_provider` 命令接收宿主进程内配置；
- 发现并校验 `reflex.providers` 插件，隔离单个插件加载失败；
- 根据请求显式选择已配置 Provider，不自动降级到 Mock；
- 在显式开发模式下提供无网络 Mock Provider；
- 用 `request_id` 隔离并发请求和取消。

当前不负责：

- Provider HTTP 协议适配；
- SecretStore；
- 剪贴板、托盘、全局快捷键；
- 历史数据库；
- 本地语义模型加载。

## 命令协议

输入示例：

```json
{"version":1,"request_id":"req-1","type":"optimize","payload":{"text":"请写一封邮件","style":"concise"}}
```

输出示例：

```json
{"version":1,"request_id":"req-1","event":{"type":"chunk","data":{"text":"..."}}}
```

`configure_provider` 只允许由桌面宿主在本地 Sidecar 通道中调用，不对前端 capability 开放。Runtime 不持久化密钥，也不在事件、诊断或对象表示中返回密钥。

## 本地验证

```powershell
cd packages\reflex-runtime
uv run --python 3.12 --with pytest --with httpx pytest -q
```

手工启动：

```powershell
cd packages\reflex-runtime
$env:PYTHONPATH = "src;..\reflex-core\src"
uv run --python 3.12 --with httpx python -m reflex_runtime.cli
```
