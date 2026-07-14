# Reflex Cloud

Reflex Cloud 是桌面客户端的独立云端服务。第一阶段提供匿名安装身份、分项隐私
授权、反馈和截图附件、数据删除、保留策略以及简单管理后台。

## 本地启动

```powershell
cd services\reflex-cloud
Copy-Item .env.example .env
uv sync --extra dev
uv run reflex-cloud
```

默认地址为 `http://127.0.0.1:8787`，管理页为 `/admin`。生产环境必须替换
`.env` 中的两个随机密钥，并通过 HTTPS 反向代理暴露服务。

## 测试

```powershell
uv run --extra dev pytest -q
```

## 隐私约束

- 提示词、结果和截图默认不上传；
- 服务器不接收 Provider API Key；
- 管理列表不返回正文和附件；
- 安装令牌仅以 HMAC 形式保存；
- 用户可以调用数据删除接口删除反馈和附件。
