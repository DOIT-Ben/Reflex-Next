# 历史记录：安全 Provider 主链验证（2026-07-11）

更新日期：2026-07-11

> 历史证据提示：本文记录旧工作树的离线主链与桌面接入验证，不代表当前工作树的完整发布门禁。

## 结论

离线主链、配置持久化、Windows 安全凭据状态读取、Provider 插件发现、MiniMax 协议适配、前端设置交互和 Tauri capability 已通过验证。

真实 MiniMax 付费请求尚未执行。当前应用显示密钥未配置，必须由用户在设置页手动录入后，再执行一次短流式请求和一次流式取消；该步骤不得从聊天记录、命令、环境变量或文件自动导入密钥。

## 自动化结果

| 范围 | 命令 | 结果 |
|---|---|---|
| Core | `uv run --python 3.12 --with pytest pytest -q` | 24 passed |
| Runtime | `uv run --python 3.12 --with pytest --with httpx pytest -q` | 31 passed |
| MiniMax Provider | `uv run --python 3.12 --with pytest --with httpx pytest -q` | 18 passed |
| 前端 | `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2` | 39 passed |
| 前端构建 | `npm run build` | 通过 |
| Rust Host | `cargo test -- --test-threads=2` | 29 passed，2 个 Windows 实机探针按默认忽略 |
| Windows 凭据探针 | `cargo test windows_backend_ -- --ignored --test-threads=1` | 2 passed |
| Rust 构建 | `cargo check`、`cargo build` | 通过 |
| 前端生产依赖 | `npm audit --omit=dev` | 0 vulnerabilities |
| Python 依赖 | `uv pip check` | 兼容 |

所有测试均按组件顺序执行，Vitest 最多 2 个 worker，Rust 最多 2 个测试线程。

## 安全检查

- Core 禁止依赖扫描只命中边界测试中的禁止名单，`src` 未发现 PyQt、PySide、torch、sentence-transformers、huggingface-hub 或 sqlite3。
- 仓库疑似凭据扫描只命中测试哨兵；生产代码未发现疑似凭据。
- Runtime 生命周期测试在同一 Sidecar 进程中覆盖配置、流式、取消、认证失败和关闭，并统一检查 stdout/stderr 不包含密钥、私有请求、取消后的私有分片或 Authorization 值。
- Provider 认证失败、限流、超时、网络、服务端和协议错误只返回稳定错误分类，不返回原始响应体。
- Tauri capability 只公开配置读取、配置保存和密钥状态/保存/删除命令；私有 Provider 配置命令不对 WebView 开放。
- ConfigStore 拒绝疑似密钥扩展字段，并使用临时文件、原子替换和上一份有效备份。

## 可见层检查

- 真实 Tauri 窗口可正常打开设置页，未再出现“设置加载失败”。
- 密钥未配置时显示明确状态，输入框保持空白，删除按钮不可用。
- 680×480 和 760×540 视口无页面级横向或纵向溢出。
- 125% 和 150% 设备缩放下设置页无重叠、截断或页面级溢出。
- 用户界面未出现 Mock、debug、test、TODO、生成器、验收、Tauri、Runtime 或 Sidecar 等内部制作信息。
- 浏览器控制台无 warning 或 error；截图仅用于本地复核，未加入仓库。

## 待完成的真实链路

1. 依据 MiniMax 官方文档核对当前 Endpoint 和模型。
2. 用户在运行中的设置页手动保存密钥，确认输入框清空且只显示已配置状态。
3. 通过完整 UI 路径执行一次最短流式请求，只记录状态分类、首包耗时和总耗时。
4. 流式开始后执行一次取消，确认界面回到可操作状态且旧请求不再产生分片。
5. 轮换曾出现在聊天中的密钥，并重新执行本记录中的完整自动化命令。

## 回退与恢复

- Provider 不可用：在设置中停用 MiniMax，开发环境可显式使用离线 Mock，不做自动降级。
- 配置写入异常：保留主配置文件，使用上一份有效备份恢复，不同时覆盖主文件和备份。
- 凭据异常：从设置页删除 MiniMax 密钥；不得回退到明文文件或环境变量。
- 插件加载异常：保持 Runtime 存活并返回未配置错误，不影响 Core 导入和离线能力。
- 代码回退：按提交逆序回退本阶段改动；本地 `resources\` 不属于提交范围，不参与回退。
