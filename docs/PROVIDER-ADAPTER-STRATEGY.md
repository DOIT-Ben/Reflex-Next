# Provider 适配层策略

更新时间：2026-08-12

本文只约束模型协议适配，不扩展 Reflex Next 的产品范围。Reflex Next 的产品本体仍是一次性的提示词/内容优化，不是持续聊天工作台。

## 当前实现盘点

仓库目前没有 LiteLLM、LangChain、LlamaIndex 或 OpenRouter SDK 的依赖或接入痕迹。现有适配器均为独立插件：

- `reflex-provider-minimax`：MiniMax 协议；
- `reflex-provider-openai-compatible`：OpenAI Chat Completions 兼容协议；
- `reflex-provider-native-protocols`：Anthropic Messages 和 Gemini GenerateContent。

Runtime 只依赖 `httpx`，通过插件 entry point 发现 Provider。`reflex-core` 不创建网络客户端，符合最小 Core 边界。

## 不把 LiteLLM 放进最小 Core

LiteLLM 可以作为“可选 Provider Adapter 插件”或独立 Cloud Gateway，用于把更多厂商协议转换为统一调用接口；不应作为 Runtime/桌面包的默认依赖，原因是：

1. 依赖树和安装包会显著变大，并增加启动、PyInstaller 打包和升级风险；
2. 供应链与传递依赖许可证需要逐项复核，不能仅依据仓库页面的许可证字段；
3. LiteLLM 的参数归一化可能隐藏厂商差异，错误分类、取消和响应上限仍必须由 Reflex Runtime 兜底；
4. 用户的 API Key、完整输入和原始响应不能因为引入网关而离开本机或进入第三方日志。

若后续采用 LiteLLM，接入方式应是独立插件（例如 `reflex-provider-litellm`），并通过可选 extra 或单独 sidecar 安装。Release 默认构建不携带该插件，除非完成许可证、SBOM、包体积、冷启动、取消和脱敏实测。

## 统一契约的目标形态

协议名称、模型目录和模型优化偏好必须分开：

```text
ProviderConfig
  provider_id / protocol / base_url / model / secret_ref

ProtocolProfile
  request_mapping / stream_mapping / error_mapping / cancellation

ModelCapabilityProfile
  context_window / system_message / json_output / reasoning / vision / tools
  prompt_preference / scene_preferences
```

Provider 只将 Core 的 `ModelRequest` 映射为供应商请求，并将响应映射回统一事件；场景、模式、风格和提示词模板仍由 Core/模板插件决定。模型偏好只影响渲染和可选参数，不得改变协议层职责。

## 自定义模型 ID 的安全边界

OpenAI-compatible Provider 应允许用户填写经过校验的自定义模型 ID（例如 `gpt-5.6-luna`），而不是要求模型必须出现在内置白名单。仍需保留以下限制：

- ASCII、长度上限和可打印字符校验；
- Provider 配置时绑定明确的 `base_url` 与协议类型；
- 不根据模型名自动推断或拼接任意 URL；
- 目录展示将用户模型标记为“自定义/未验证”；
- 请求和错误继续使用统一超时、取消、重试、响应大小和脱敏策略。

原生 Anthropic/Gemini Provider 可继续维护受信模型目录；若开放自定义模型，应由各协议适配器单独声明能力和验证策略。

## 接入前的验收门槛

任何新增适配器（包括 LiteLLM）至少需要：

1. 非流式和流式成功夹具；
2. 认证、限流、超时、网络、服务端、非法响应和空响应分类；
3. 主动取消（包括首片前和首片后）且无迟到事件；
4. 2 MiB 响应、50,000 事件和非法 UTF-8 上限测试；
5. 日志、异常、诊断和事件不得泄露密钥或完整用户输入；
6. 依赖许可证、SBOM、包体积、冷启动和 PyInstaller/Windows 生命周期验证。

在这些证据完成前，目录状态只能标记为 `experimental`，不能宣称“任意模型完全兼容”。

