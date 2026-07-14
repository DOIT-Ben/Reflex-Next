# Reflex Cloud 产品闭环架构

## 1. 目标

Reflex Cloud 为桌面客户端补充四条云端闭环，同时保持本地 Core 和自备
Provider Key 模式可以独立运行：

1. 用户对结果进行满意或不满意反馈，并在明确确认后附加应用窗口截图；
2. 云端 Provider 代理提供可计量的免费额度；
3. 用户可独立选择是否加入改进计划，并随时撤回或删除数据；
4. 反馈进入分类、复现、修复、发布和效果对比流程。

## 2. 边界

```text
Tauri Desktop
  |- Local Runtime -> Local Provider (BYOK)
  `- Reflex Cloud API
       |- Installation identity and consent
       |- Feedback and attachment ingestion
       |- Cloud optimization and quota
       `- Admin triage and quality analytics
```

`reflex-core` 不依赖云端 API。云端服务位于 `services/reflex-cloud`，通过稳定
HTTP/SSE 协议与客户端通信。

## 3. 隐私默认值

- 使用指标、提示词/结果、截图三类授权相互独立；
- 三类授权默认均为关闭，不允许预选或静默开启；
- 截图只截 Reflex 应用窗口，确认后才捕获，并在发送前提供预览和删除；
- 提示词和结果只有在本次反馈中显式勾选后才能随反馈上传；
- API Key、Authorization、剪贴板无关内容和完整桌面截图永不上传；
- 客户端先脱敏，服务器再次脱敏；
- 用户可查询当前授权、撤回授权并删除云端数据；
- 原始反馈默认保留 90 天，之后删除附件并移除可识别字段。

## 4. 反馈状态机

```text
new -> triaged -> reproduced -> planned -> fixed -> released
  `-------------------------------------------------> rejected
```

每条反馈包含应用版本、系统、Provider、模型、模式、风格、场景、请求 ID、
诊断 ID、错误代码和耗时等非正文上下文。管理员列表默认不返回提示词、结果或
附件内容，敏感详情需要单独请求。

## 5. API 第一阶段

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/v1/installations` | 创建匿名安装身份和一次性返回的令牌 |
| `GET` | `/v1/quota` | 查询当日免费请求、输入字符和输出字符额度 |
| `GET` | `/v1/privacy/consent` | 查询分项授权 |
| `PUT` | `/v1/privacy/consent` | 更新分项授权并记录版本 |
| `DELETE` | `/v1/privacy/data` | 删除该安装身份及其反馈和附件 |
| `POST` | `/v1/optimize` | 使用云端 Provider 代理并以 SSE 返回 Core 事件 |
| `POST` | `/v1/optimize/cancel` | 取消当前安装身份拥有的生成请求 |
| `POST` | `/v1/feedback` | 提交满意/不满意反馈 |
| `GET` | `/v1/admin/feedback` | 管理员查看脱敏反馈列表 |
| `GET` | `/v1/admin/analytics/feedback` | 按分类和版本查看质量指标 |
| `GET` | `/v1/admin/feedback/{id}` | 管理员查看单条授权详情 |
| `PATCH` | `/v1/admin/feedback/{id}` | 更新分类和处理状态 |

客户端身份使用高熵安装令牌，服务器只保存带 pepper 的 HMAC。管理员接口使用
独立 Bearer Token。生产环境必须通过 HTTPS，并由反向代理限制请求体和速率。

## 6. 云端生成第二阶段

```text
POST /v1/optimize       -> SSE
POST /v1/optimize/cancel
GET  /v1/quota
```

当前 alpha 先按请求次数、输入字符和输出字符设置三道日上限，生成请求在发送 Provider
前预占请求与输入额度，成功后记录输出用量。当前 alpha 以安装身份和单进程并发闸门
控制资源；正式多实例部署前必须补 Redis/IP/账户级限流。云端 Provider Key 只存在
服务器环境或密钥系统，客户端自备 Key 永不上传。接入真实 Provider 的 token 计量后，
再增加 token 成本账本，
不改变客户端查询契约。客户端保留自备 Key 模式作为离线于 Reflex Cloud 的替代路径。

## 7. 改进和发布闭环

反馈进入服务端脱敏、去重、分类和人工复核队列。只有具备有效改进计划授权的
提示词/结果才能进入质量数据集，并保留来源、授权版本和删除传播标识。模板或
模型策略变更必须记录版本，通过同场景负反馈率、完成率、首包时间和重试率做
前后对比，不能直接把原始用户数据写入测试或训练资产。
