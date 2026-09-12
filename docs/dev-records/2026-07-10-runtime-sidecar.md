# 2026-07-10 Runtime Sidecar 记录

## 目标

实现 Stage 2 的最小 Runtime Sidecar，让未来 Rust Host 可以通过 NDJSON stdin/stdout 与 Python Core 通信。

## 已完成

- 新增 `packages\reflex-runtime`。
- 新增 `CommandEnvelope`、`ProtocolError` 和 `parse_command`。
- 新增 `python -m reflex_runtime.cli`，支持 `optimize`、`cancel`、`ping`、`shutdown`。
- stdout 只输出 `version/request_id/event` 事件信封。
- stderr 只输出脱敏诊断。
- 新增无网络 `MockProvider`，支持正常 chunk、延迟 chunk、取消和模拟错误。
- 每个 optimize 请求在独立线程运行，取消通过 `CancellationToken` 协作完成。
- 前端 `CoreBridge` 新增 Runtime 命令信封创建、事件信封解析和 `request_id` 过滤。

## 验证

```powershell
cd packages\reflex-core
uv run --python 3.12 --with pytest pytest
```

结果：23 passed。

```powershell
cd packages\reflex-runtime
uv run --python 3.12 --with pytest pytest
```

结果：10 passed。

```powershell
cd apps\tauri-host
npm test
npm run build
npm audit --audit-level=moderate
```

结果：前端测试 10 passed，构建通过，审计 0 vulnerabilities。

浏览器验证：

- 桌面端完成一次优化并渲染事件时间线。
- 移动端无横向溢出。

截图：本机运行产物，不入库。

## 下一步

1. 在 `apps\tauri-host\src-tauri` 初始化 Tauri 2 Rust 宿主。
2. 用 Rust 启动 `reflex_runtime.cli`，写入命令信封并读取事件信封。
3. 将 Svelte 端 `DemoCoreBridge` 替换为真实 Tauri bridge。
4. 继续保持 Mock 模式，不接真实 MiniMax。
