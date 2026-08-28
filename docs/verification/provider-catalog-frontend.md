# 历史记录：Provider 动态目录前端接入验证（2026-07-15）

验证日期：2026-07-15

> 历史证据提示：本文记录旧分支的前端目录接入验证，不代表当前工作树的完整发布门禁。
验证分支：`codex/full-feature-parity`
验证范围：Tauri Host Domain Bridge、设置页 Provider/模型选择、Runtime 目录请求关联

## 实现边界

前端通过固定事件 `reflex://provider-catalog` 接收目录，通过 `runtime_list_providers` 发起请求。Rust Host 命令返回本次 Runtime 请求 ID，前端只接受同一 ID 的目录或安全错误事件，因此旧请求事件不会污染当前设置。

前端对目录执行独立的结构校验：

- 只接受协议版本 `1` 和固定字段集合；
- 限制 Provider、模型数量和公开文本长度；
- 校验 Provider ID、模型 ID、排序、唯一性、默认模型归属、发布状态和布尔配置状态；
- 拒绝额外字段、错误排序、重复项和控制字符；
- 底层错误、超时和 `provider_catalog_error` 统一转换为固定用户提示，不暴露协议内容、路径或凭据。

Runtime 目录成功后，设置页使用后端返回的 Provider 名称、模型列表和默认模型。浏览器预览没有 Tauri Runtime 时仍使用静态 Demo 目录；Tauri 目录暂不可用时保留可用回退并显示状态提示，不改变密钥或请求逻辑。

## 验证命令

```powershell
npm test -- --maxWorkers=2
npm run build
cargo test --locked --lib -- --test-threads=2
```

结果：

- Vitest：26 个测试文件、163 项通过；
- Vite：242 个模块构建通过；
- Rust Host：191 项通过，3 项 Windows Credential Manager 测试按平台条件忽略；
- `git diff --check`：通过；
- 测试结束后没有残留 Vitest、Node 或 Cargo 测试进程。

## 未覆盖

本记录证明前端协议接入和离线契约，不替代真实 Provider 成功/取消、Windows 10 发布验证、72 小时浸泡、跨版本官方安装包升级、代码签名、更新和回滚门禁。
