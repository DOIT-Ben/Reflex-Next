# 2026-07-10 Core 与 Host Bridge 记录

## 目标

在前端原型基础上补齐第一段可验证的 Core 事件流，并让前端从直接演示数据源改为通过 bridge 消费事件。

## 已完成

- `packages\reflex-core` 新增 `OptimizeUseCase`。
- 新增 L0 `RuleSceneDetector`，未命中特定场景时回退 `general`。
- 新增输入校验、输出清洗和敏感信息脱敏。
- 新增 `python -m reflex_core.sidecar`，以 NDJSON 输出事件流。
- 新增 Core 测试，覆盖事件顺序、手动场景、回退场景、错误脱敏、sidecar 输出和禁用依赖导入。
- `apps\tauri-host` 新增 `CoreBridge` 抽象和 NDJSON 解析。
- 前端组件改为通过 bridge 消费事件流，取消时会中止当前运行。

## 验证

```powershell
cd packages\reflex-core
uv run --python 3.12 --with pytest pytest
```

结果：7 passed。

```powershell
cd apps\tauri-host
npm test
npm run build
npm audit --audit-level=moderate
```

结果：前端测试 7 passed，构建通过，审计 0 vulnerabilities。

浏览器验证：

- 桌面端完成一次优化并渲染事件时间线。
- 取消后无旧事件回写。
- 移动端无横向溢出。

截图：

- `D:\Desktop\reflex-next-core-bridge-desktop.png`
- `D:\Desktop\reflex-next-core-bridge-mobile.png`

## 下一步

1. 用 Tauri/Rust 实现真实 Core bridge。
2. 管理 Python sidecar 生命周期、取消和 stderr 错误。
3. 迁移 MiniMax Provider 插件并接入真实流式响应。
