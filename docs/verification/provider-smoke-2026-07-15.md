# MiniMax 实机冒烟证据

验证日期：2026-07-15

候选代码提交：`1789303`

Runtime 文件：`apps\tauri-host\src-tauri\resources\runtime\reflex-runtime.exe`

Runtime SHA-256：`3EE8C42D025D3B0AE036BDD5A9F1E7D4E3F07628490F03F9EF5BC029A4680009`

## 凭据边界

冒烟工具从 Windows Credential Manager 读取产品已保存的 MiniMax 凭据。凭据值、请求正文、响应正文、请求头和端点均未写入记录。

## 命令

```powershell
packages\reflex-runtime\.venv\Scripts\python.exe tools\provider_smoke.py --operation all --provider minimax --timeout-seconds 30 --cancel-after-ms 250
```

## 结果

```json
{"operation":"list","provider_id":"minimax","model_id":"MiniMax-M2.7-highspeed","classification":"catalog_ok","error_code":null}
{"operation":"stream","provider_id":"minimax","model_id":"MiniMax-M2.7-highspeed","classification":"success","first_chunk_ms":2969,"total_ms":2984,"chunk_count":1,"error_code":null}
{"operation":"cancel","provider_id":"minimax","model_id":"MiniMax-M2.7-highspeed","classification":"cancelled","total_ms":250,"chunk_count":0,"cancel_latency_ms":0,"error_code":null}
```

## 结论与边界

- MiniMax 目录、一次流式成功和一次流式取消均通过。
- 取消后未观察到文本分片或完成事件。
- 这是一台 Windows 机器上的一次受控冒烟，不代表长期 SLO，也不替代认证失败、限流、超时和断流矩阵。
- 72 小时浸泡、Windows 10 证据、配置/历史跨版本兼容、签名、更新和回滚仍属于独立发布门禁。
