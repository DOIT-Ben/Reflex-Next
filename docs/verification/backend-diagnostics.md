# Reflex Next 本地脱敏诊断基线

更新时间：2026-07-14

## 1. 默认策略

- 默认禁用，不创建诊断目录，不写文件；
- 仅当启动 Host 前精确设置 `REFLEX_DIAGNOSTICS_ENABLED=1` 时启用；
- Host 固定使用 Tauri 应用数据目录下的 `diagnostics`，不接受前端或命令参数指定路径；
- Host 只向 Sidecar 传递固定目录和精确启用标记；相对路径、UNC、父目录跳转、错误目录名和控制字符路径均被拒绝；
- 所有文件只保存在本机，不自动上传。

Windows 支持模式启动示例：

```powershell
$env:REFLEX_DIAGNOSTICS_ENABLED = "1"
# 从同一终端启动 Reflex Host
```

停止新记录：

```powershell
Remove-Item Env:\REFLEX_DIAGNOSTICS_ENABLED -ErrorAction SilentlyContinue
# 重启 Reflex Host
```

## 2. 文件与上限

诊断目录包含两组互不共享写句柄的 JSONL 文件：

| 组件 | 活动文件 | 单文件 | 文件数 | 总量 |
|---|---|---:|---:|---:|
| Host | `host-diagnostics.jsonl` | 1 MB | 3 | 3 MB |
| Runtime | `runtime-diagnostics.jsonl` | 1 MB | 3 | 3 MB |

文件达到上限后轮转；损坏、非 UTF-8、非 JSON 对象或外部注入的超限文件在启动时丢弃。目录或磁盘失败只会停用诊断，不影响优化、取消或插件主流程。

## 3. 字段边界

Runtime 允许记录：

- 请求 ID、Provider ID、模型 ID；
- 请求阶段、固定状态和固定错误码；
- 分片计数、取消时延、总耗时；
- 随机诊断 ID。
- 插件 ID、操作和终态；插件终态不记录请求 ID。

Host 允许记录：

- Host 生命周期；
- Runtime/插件终态；
- 主配置失效后的备份恢复或默认回退；
- 固定错误码和 Runtime 生成的诊断 ID。

明确禁止：

- 请求正文和响应正文；
- 流式分片内容；
- 密钥、Authorization、Cookie 或配置私有字段；
- URL 查询、片段、账号和口令；
- Host 请求 ID 及协议中的未知字段。

## 4. 诊断 ID

当 Runtime 诊断目录真实可写时，错误事件会增加 `diagnostic_id`，格式为 `diag-` 加随机十六进制值。相同 ID 同时写入 Runtime 的 `request_failed` 记录，前端可以展示或复制该 ID 供支持定位。

诊断禁用、目录不可信或写盘失败时不生成 ID，避免向用户展示无法查询的标识；错误码、错误文案和恢复动作保持原协议。

## 5. 验证范围

自动测试覆盖：

- 默认禁用和精确启用；
- 目录边界与 Sidecar 环境清理；
- Host/Runtime 轮转、总量、并发、损坏恢复和 fail-open；
- 错误事件与落盘记录共享诊断 ID；
- 优化完成、取消和错误终态；
- 配置备份恢复、无有效配置时的默认回退以及历史修复/恢复终态；
- 私有正文、输出分片、请求 ID、URL、密钥和未知字段不落盘。

P3-005 的 Runtime/Host、配置恢复和历史恢复接入由本基线覆盖。用户显式导出、二次敏感扫描和支持包清单属于 P3-006，尚未由本文件宣称完成。
