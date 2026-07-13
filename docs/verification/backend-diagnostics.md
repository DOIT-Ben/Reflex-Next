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

## 5. 本地诊断包导出

- Host 注册 `diagnostic_bundle_export` 与 `diagnostic_bundle_cancel`，只授予主窗口；
- 前端领域桥固定使用空参数调用，不接受路径、上传地址、句柄、确认标记或扫描开关；
- 保存位置只能由系统原生保存对话框产生，目标固定为本地绝对 `.zip` 文件；
- 来源固定为 Host 与 Runtime 各 3 个 JSONL 文件，不递归枚举目录；
- 单文件上限 1 MB、总输入上限 6 MB、单行上限 64 KiB、最终 ZIP 上限 8 MB；
- 导出前重新解析严格字段白名单，未知字段、非 UTF-8、超限记录和不完整行统一拒绝；
- 导出内容主动删除 Runtime 请求 ID，再对未压缩规范化内容执行第二次凭据与高熵内容扫描；
- ZIP 只包含固定诊断文件和 `manifest.json`，清单不包含用户名、机器名、绝对路径、环境变量或配置；
- 相对路径、UNC、设备路径、父目录跳转、符号链接和 Windows reparse point 均拒绝；
- 临时文件在同目录创建，完成前 `flush` 与 `sync_all`，最后原子替换；取消或失败保留旧目标并清理临时文件；
- pending journal 仅用于异常退出后的启动清理，非法 journal 不跟随其引用路径删除文件；
- 诊断包只保存到用户选择的本地位置，不提供上传命令、网络客户端或自动上传。

前端领域桥已经冻结上述命令与返回值契约；具体按钮由前端负责人按当前界面设计接入，不改变后端权限和路径边界。

## 6. 验证范围

自动测试覆盖：

- 默认禁用和精确启用；
- 目录边界与 Sidecar 环境清理；
- Host/Runtime 轮转、总量、并发、损坏恢复和 fail-open；
- 错误事件与落盘记录共享诊断 ID；
- 优化完成、取消和错误终态；
- 配置备份恢复、无有效配置时的默认回退以及历史修复/恢复终态；
- 私有正文、输出分片、请求 ID、URL、密钥和未知字段不落盘。
- 诊断包固定来源、严格 schema、大小上限、路径与链接拒绝、取消清理和旧目标保护；
- API Key、私钥、Bearer/JWT、GitHub、Slack、AWS、Google、Stripe、凭据赋值/URL及高熵令牌二次扫描；
- ZIP 解包后二次扫描为 0，导出的 Runtime JSONL 不包含请求 ID；
- 主窗口最小 capability、历史窗口拒绝权限以及前端空参数桥接契约。

P3-005 的 Runtime/Host、配置恢复和历史恢复接入以及 P3-006 的本地诊断包安全导出均由本基线覆盖。
