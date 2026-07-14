# Reflex Cloud Beta 发布与隐私审查

更新时间：2026-07-15

本文是朋友 Beta 和正式上线前的执行基线。当前服务可以在单实例 Docker Compose
环境运行；多实例部署前必须把并发、限流和任务取消状态迁移到共享基础设施。

## 1. 发布边界

Beta 包含：

- Reflex Cloud Provider 代理和 SSE 流式生成；
- 匿名安装身份、每日免费额度、IP 小时限流和并发闸门；
- 反馈、授权截图、分类、状态流转和版本质量分析；
- 改进计划的显式授权、脱敏保存、删除和保留期清理；
- 管理后台的近 7 日请求、完成率、预估成本和负反馈率。
- 服务端每日全局请求上限和预估成本预算护栏。

客户端自备 Provider 模式仍然可以离线于 Reflex Cloud 使用。客户端 API Key
永远不发送到云端。

## 2. 生产配置

生产环境必须从密钥管理系统注入以下变量，不要把真实值写入 `.env`、镜像或
提交记录：

```text
REFLEX_POSTGRES_PASSWORD
REFLEX_CLOUD_ADMIN_TOKEN
REFLEX_CLOUD_TOKEN_PEPPER
REFLEX_CLOUD_PROVIDER_API_KEY
REFLEX_CLOUD_PROVIDER_PRICING_VERSION
REFLEX_CLOUD_PROVIDER_INPUT_USD_PER_MILLION_TOKENS
REFLEX_CLOUD_PROVIDER_OUTPUT_USD_PER_MILLION_TOKENS
REFLEX_CLOUD_GLOBAL_DAILY_REQUEST_LIMIT
REFLEX_CLOUD_GLOBAL_DAILY_COST_BUDGET_MICROUSD
```

价格字段是成本估算所需的服务端配置，必须与 Provider 账单的价格版本一致。
系统按字符估算 Token，管理后台必须把成本称为“预估成本”，不能当作 Provider
最终账单。价格变更时递增 `PRICING_VERSION`。

预算成本单位为微美元（`1 USD = 1,000,000`）。请求进入 Provider 前按
`BUDGET_MAX_OUTPUT_CHARS_PER_REQUEST` 的保守输出上限预占，完成或失败后按实际
输入/输出字符成本结算。管理接口的 `daily_cost_committed_microusd` 包含已结算和
仍在进行中的预占，`daily_cost_remaining_microusd` 是允许继续接收请求的剩余额度。

需要公网入口时使用 Caddy profile，并先把域名解析到服务器：

```powershell
$env:REFLEX_CLOUD_DOMAIN = "cloud.example.com"
docker compose --profile public up -d
```

默认 API 仍只绑定宿主机回环地址，Caddy 才是公网入口。Caddy 自动申请证书，
生产环境仍需确认 DNS、80/443 入站规则和密钥管理符合部署方制度。

启动：

```powershell
cd services\reflex-cloud
docker compose up -d
curl https://cloud.example.com/health/ready
```

API 容器默认只绑定宿主机 `127.0.0.1:8787`。公网入口必须由反向代理提供：

- HTTPS 和 HSTS；
- 请求体上限至少 16 MB，超时和连接数上限；
- 只信任反向代理写入的 `X-Forwarded-For`；
- 对安装、优化、反馈和管理接口分别限流；
- 不把 Postgres 或 API 容器端口直接暴露到公网。

Compose 默认只信任回环地址和 Docker 私有 `172.16.0.0/12` 网段传入的代理头，
不得把 `FORWARDED_ALLOW_IPS` 改成 `*`。

## 3. 数据清单

| 数据 | 默认状态 | 用途 | 删除/保留 |
|---|---|---|---|
| 安装令牌哈希 | 必要 | 识别匿名安装 | 用户删除时级联删除 |
| 授权记录 | 关闭可选项 | 记录授权版本和撤回 | 随安装身份删除 |
| 每安装额度 | 必要 | 免费额度和防滥用 | 随安装身份删除 |
| IP 小时 HMAC | 必要 | 跨安装限流 | 按小时窗口失效 |
| 反馈正文/联系方式 | 用户提交 | 问题复现和联系 | 90 天清理，用户可删除 |
| 截图 | 单次明确勾选 | 复现界面问题 | 90 天清理，用户可删除 |
| 改进样本 | 改进计划开启 | 质量分析和模板迭代 | 90 天清理，用户可删除 |
| 日成本聚合和预算账本 | 无用户关联 | 成本监控和预算护栏 | 只保留匿名日聚合 |

提示词、结果和截图三类内容默认关闭。服务端再次校验附件一致性并脱敏，不能
因为客户端篡改布尔字段而绕过单次提交授权。删除安装身份时，反馈、附件、授权、
额度和改进样本级联删除；成本聚合不含安装 ID、请求 ID 或正文，无法回溯到用户。

## 4. Beta 验收清单

1. 使用测试密钥启动一套独立 Compose 项目，确认 Postgres 和 API 均为 healthy。
2. 调用 `/health/ready`，确认数据库、Provider 和预算都是 `ok/configured`。
3. 新安装查询授权，确认三项可选授权均为 `false`。
4. 用 5-20 名朋友进行真实生成，观察 `/v1/admin/analytics/usage?days=7`。
5. 每个版本至少收集一批满意和不满意反馈，再查看 `/v1/admin/analytics/feedback`。
6. 在管理后台完成一条反馈的分类、复现、计划和发布状态流转。
7. 用测试安装执行删除，确认旧令牌失效、新安装重新默认为关闭授权。
8. 做一次 Postgres 备份和恢复演练，记录恢复耗时和数据完整性结果。

备份与隔离恢复脚本：

```powershell
.\tools\reflex-cloud-backup.ps1 -OutputDirectory "D:\Desktop\reflex-cloud-backups"
.\tools\reflex-cloud-restore.ps1 `
  -BackupFile "D:\Desktop\reflex-cloud-backups\reflex-cloud-postgres-<timestamp>.dump" `
  -TargetDatabase "reflex_cloud_restore" `
  -ConfirmRestore
```

恢复脚本拒绝直接写入生产数据库 `reflex_cloud`，必须先恢复到隔离数据库并完成校验。

## 5. 运营阈值

- 每日预估成本达到预算的 50%：检查异常安装和 IP 分布；
- 达到 80%：降低免费额度或暂停新增 Beta 安装；
- 达到 100%：停止云端生成，只保留客户端自备 Provider 模式；
- 负反馈率连续两个版本上升：冻结模板发布，先按场景和版本复现；
- Provider 错误率或首包延迟异常：回退客户端默认 Provider 或暂停云端入口。

当前成本接口是监控和人工决策依据；预算账本使用 Postgres 行锁保护单日并发预占，
但正式多实例发布前仍应接入告警系统和 Redis 共享限流/取消状态。

可用 `tools\reflex-cloud-budget-check.ps1` 定期轮询管理分析接口：退出码 `0` 为正常、
`1` 为预警、`2` 为临界；远程地址必须使用 HTTPS，令牌只从环境变量读取。

## 6. 回滚

发布前保存当前镜像标签和数据库备份。回滚只切换 API 镜像，不删除 Postgres
卷或上传卷：

```powershell
docker compose pull
docker compose up -d
docker compose ps
```

数据库恢复必须在隔离实例完成校验后再切换流量。任何删除云端数据的操作都必须
通过客户端数据删除接口或已审计的管理流程完成，不直接删除生产卷。

## 7. 发布结论

alpha.6 已具备单实例 Beta 的预算护栏、公网代理配置、备份恢复工具和容器验收证据；
云服务镜像使用固定 uv 版本和 `uv.lock` 构建，不在发布时重新选择依赖版本。
alpha.7 已统一桌面端、Core、Runtime 和云服务的版本元数据；新镜像仍需在 P4-002
可复现构建门禁中生成和复验。
正式公网推广仍需完成真实域名部署、生产密钥管理、Redis 共享限流/取消状态、外部
告警接入、隐私政策发布和真实用户试用。这些是发布门槛，不能用本地测试通过替代。
