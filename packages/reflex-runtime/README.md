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

## 结构化诊断

`reflex_runtime.diagnostics.DiagnosticWriter` 已接入 Runtime 请求主链，并与 Tauri Host 的独立诊断文件协同工作：

- 默认禁用；只有启动 Host 前精确设置 `REFLEX_DIAGNOSTICS_ENABLED=1`，Host 才会在应用数据目录下创建 `diagnostics` 目录；
- Host 只记录生命周期、Runtime/插件终态、固定错误码和诊断 ID，不记录请求 ID、正文或分片；
- Runtime 记录请求阶段、Provider ID、模型 ID、分片计数、耗时、错误分类和诊断 ID；
- 诊断可用时，错误事件携带与 Runtime 记录一致的 `diag-...` ID；禁用或写盘不可用时，公开协议保持原行为；
- 仅保留固定允许字段，正文、输入、输出、密钥及未知字段不会落盘；
- 自动脱敏允许字段中的凭据文本，消息正文、URL 和未知字段不会落盘；
- Host 与 Runtime 分别使用独立文件；每个组件默认单文件上限 1 MB、最多 3 个文件、总量上限 3 MB；
- 同一实例支持并发写入，`close()` 后拒绝后续记录；
- 目录权限或磁盘写入异常只会关闭诊断写入；损坏日志会被丢弃后恢复，不阻塞 Runtime 主流程。

诊断默认只保存在本机，不会自动上传。关闭支持模式后重启应用即可停止新记录；已存在文件不会被自动删除。诊断包导出与导出前二次敏感扫描由 P3-006 单独提供。

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
