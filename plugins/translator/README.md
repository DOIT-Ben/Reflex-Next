# Reflex Translator

Reflex Next 的流式翻译插件。插件只负责校验文本、判断中英文方向、构造受控消息并清洗流式片段。

网络访问由 Runtime 注入的 Provider gateway 统一完成。插件不读取 Provider 密钥，不创建 HTTP 客户端，也不持久化原文或译文。

## 开发验证

```powershell
uv run --python 3.12 --with pytest pytest -q
```
