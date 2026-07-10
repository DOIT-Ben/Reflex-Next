# reflex-provider-minimax

Reflex Next 的 MiniMax Provider 插件，通过 `reflex.providers` entry point 注册。

当前能力：

- 映射统一模型请求到 MiniMax Chat Completions 请求；
- 解析 SSE 流式响应和完整 JSON 响应；
- 支持请求前取消和流式过程中取消；
- 在首个内容分片前对限流、服务端错误和网络错误做有限重试；
- 首个内容分片后不自动重试，避免重复计费或重复内容；
- 将认证、限流、超时、网络、服务端和协议错误映射为稳定安全错误；
- 不在日志、异常文本或对象表示中暴露密钥、请求体和原始响应体。

当前代码默认配置：

```text
Endpoint: https://api.minimaxi.com/v1/chat/completions
Model: MiniMax-M2.7-highspeed
```

真实调用前应以 MiniMax 官方文档核对 Endpoint 和模型可用性。密钥由桌面宿主从系统安全存储读取并在本地进程通道内配置，不由插件读取文件或环境变量。

## 本地验证

```powershell
cd plugins\provider-minimax
uv run --python 3.12 --with pytest --with httpx pytest -q
```
