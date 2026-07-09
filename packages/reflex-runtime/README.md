# reflex-runtime

`reflex-runtime` 是 Reflex Next 给桌面宿主调用的 Python Sidecar。

当前职责：

- 通过 stdin 接收 NDJSON 命令信封；
- 通过 stdout 输出机器可解析事件信封；
- 将诊断信息写入脱敏 stderr；
- 管理 `optimize`、`cancel`、`ping`、`shutdown` 命令；
- 使用无网络 Mock Provider 跑通 Runtime 到 Core 的事件链；
- 用 `request_id` 隔离并发请求和取消。

当前不负责：

- 真实 Provider HTTP 请求；
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

## 本地验证

```powershell
cd packages\reflex-runtime
uv run --python 3.12 --with pytest pytest
```

手工启动：

```powershell
cd packages\reflex-runtime
$env:PYTHONPATH = "src;..\reflex-core\src"
python -m reflex_runtime.cli
```
