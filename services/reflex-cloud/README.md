# Reflex Cloud

Reflex Cloud 是桌面客户端的独立云端服务，提供匿名安装身份、分项隐私授权、云端
Provider SSE 代理、免费额度、反馈和截图附件、数据删除、保留策略、成本监控以及
简单管理后台。

## 本地启动

```powershell
cd services\reflex-cloud
Copy-Item .env.example .env
uv sync --extra dev
$env:REFLEX_CLOUD_PROVIDER_API_KEY = "server-only-key"
uv run reflex-cloud
```

默认地址为 `http://127.0.0.1:8787`，管理页为 `/admin`。生产环境必须替换
`.env` 中的管理员密钥、token pepper 和云端 Provider 密钥，并通过 HTTPS 反向代理
暴露服务。生产还必须配置 Provider 价格版本和输入/输出单价。客户端自备 API Key
不会发送到这里。

健康检查：

- `/health/live`：进程存活检查；
- `/health/ready`：数据库和 Provider 就绪检查；
- `/v1/admin/analytics/usage?days=7`：匿名日聚合请求和预估成本；
- `/v1/admin/analytics/feedback`：分类和版本质量分析。

## 测试

```powershell
uv run --extra dev pytest -q
```

## 隐私约束

- 改进计划、提示词/结果和截图默认关闭；
- 客户端自备 API Key 永不上传，云端 Provider Key 只从服务器环境读取；
- `/v1/optimize` 以版本化 Core 事件信封通过 SSE 返回结果；
- `/v1/quota` 返回请求、输入字符和输出字符的每日免费额度；
- 成本只保存按日期、Provider、模型和价格版本聚合的估算，不保存安装身份或正文；
- 管理列表不返回正文和附件；
- 安装令牌仅以 HMAC 形式保存；
- 用户可以调用数据删除接口删除反馈和附件。
