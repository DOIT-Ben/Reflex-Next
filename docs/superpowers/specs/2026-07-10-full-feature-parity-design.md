# Reflex Next 全功能对齐设计

日期：2026-07-10
目标版本：`v1.0.0`
设计状态：待用户复核
行为基线：旧版 Reflex（Classic 参考实现）

## 1. 目标

在不复制旧 PyQt 工作台架构的前提下，让 Reflex Next 覆盖旧 Reflex 的有效产品能力，并交付可安装、可卸载、可恢复、可安全保存 Provider 密钥的 Windows 桌面产品。

“全功能对齐”指能力和用户结果对齐，不要求窗口结构、类名、数据库结构或内部实现与旧版一致。

最终用户应能完成以下主路径：

```text
托盘或全局快捷键呼出 Reflex
  -> 输入、粘贴或读取剪贴板
  -> 自动或手动选择场景
  -> 使用模板和风格构建请求
  -> 选择真实 Provider 并流式生成
  -> 取消、重试、复制、替换、翻译或预览结果
  -> 按隐私策略保存历史、评分、搜索、筛选和导出
```

## 2. 约束

### 2.1 保留的架构边界

- `reflex-core` 不依赖 Tauri、PyQt、SQLite、剪贴板、系统凭据、HTTP 客户端、torch 或 sentence-transformers。
- Runtime 负责插件发现、Provider 生命周期、命令调度和脱敏诊断。
- Provider 插件只负责供应商协议适配、流式解析、取消和错误分类。
- 模板、场景和风格由 Core 与模板包决定，Provider 不做 Prompt 决策。
- 历史、翻译、批处理、Markdown、语义模型均保持插件化。
- Tauri Host 负责窗口、托盘、快捷键、剪贴板、配置、系统凭据和 Sidecar 生命周期。

### 2.2 明确禁止

- 不迁移 PyQt 窗口、`QThread`、`pyqtSignal` 或旧 ViewModel。
- 不在 Core 中初始化 SQLite、读取剪贴板、下载模型或调用网络。
- 不把 API Key 放入仓库、配置 JSON、命令行、环境变量、日志、前端 store、localStorage、测试夹具或错误信息。
- 不让桌面产品在真实 Runtime 不可用时静默返回演示结果。
- 不让 CI 调用付费 Provider。
- 不默认开启自动替换剪贴板、历史保存或本地语义模型下载。

## 3. 功能对齐范围

### 3.1 核心生成

- 内容优化与提示词生成双模式。
- 简洁、平衡、详细、创意四种主风格。
- 旧 `precise` 风格资产作为兼容别名迁移，不增加第五个默认按钮。
- 流式输出、取消、重试、重新生成。
- 自动场景识别失败回退 `general`，不得阻塞生成。
- 输入校验、响应清洗、错误脱敏和耗时指标。

### 3.2 模板与场景

- 迁移旧版 42 个内容场景。
- 迁移四种主风格、`precise` 兼容风格和系统基础模板，共 48 份 Markdown 资产。
- 支持场景、风格、模式和语言变量渲染。
- 手动场景优先于自动识别。
- 模板包具备版本、清单、校验和加载失败回退。

### 3.3 Provider

必须覆盖旧版已声明 Provider：

- MiniMax
- 智谱 GLM
- DeepSeek
- 阿里通义千问
- SiliconFlow

每个 Provider 使用同一插件协议，并实现：

- 模型列表与默认模型配置。
- 流式响应解析。
- 主动取消和连接关闭。
- 超时、网络、鉴权、限流、服务端、无效响应和空结果分类。
- 固定脱敏错误，不直接显示供应商原始响应。
- 可注入假传输层，自动测试不访问网络。

MiniMax 第一阶段默认模型为旧版已验证的 `MiniMax-M2.7-highspeed`，模型名称和端点均进入非敏感配置，可在设置中修改。真实联调前再核验官方当前模型可用性。

### 3.4 语义场景识别

- L0 规则识别保持默认、零依赖、即时可用。
- L1 `semantic-detector` 插件按需加载 sentence-transformers。
- 支持模型状态、下载、镜像、断点续传、进度和取消。
- 模型不存在、下载失败或加载失败时回退 L0。
- 未启用插件时不得导入 torch、sentence-transformers 或 huggingface-hub。

### 3.5 历史与评分

- 使用 `history-sqlite` 插件保存历史。
- 支持搜索、Provider/场景/风格/日期筛选、评分和详情。
- 支持 JSON、CSV 和 Markdown 导出。
- 支持完整性扫描、坏记录隔离、重建索引和备份恢复。
- 历史输入和输出默认使用每条记录独立随机 nonce 的 AES-GCM 加密。
- 历史主密钥保存到 Windows Credential Manager，只通过私有 Runtime 管道进入历史插件内存。
- 支持密钥轮换、全库重加密和中断后从备份恢复。
- 隐私模式下不写入历史；关闭隐私模式不追补历史。
- 数据库仅在插件启用后初始化，不进入 Core 导入链。

### 3.6 翻译、批处理和 Markdown

- `translator`：翻译生成结果，支持目标语言、取消和复制。
- `batch-runner`：文本、CSV 或逐行任务批处理，支持进度、单项错误、取消、恢复和导出。
- `markdown-preview`：安全渲染 Markdown，不执行原始 HTML、脚本或远程嵌入。
- 三类能力均消费 Core/Provider 契约，不复制 Provider HTTP 逻辑。

### 3.7 桌面体验

- 单实例。
- 托盘菜单：打开、最近结果、历史、批处理、设置、退出。
- 全局快捷键注册、冲突提示和可配置回退。
- 窗口显示、隐藏、聚焦、多显示器越界恢复。
- 剪贴板显式读取、复制结果、首次替换确认和可配置策略。
- 设置持久化、配置版本迁移和非法值回退。
- 中文、英文界面切换。
- 浅色、深色和跟随系统主题。
- 支持导入、校验和恢复旧版自定义主题 JSON，但不复制旧 PyQt 主题编辑器布局。

### 3.8 隐私与网络

- API Key 保存到 Windows Credential Manager。
- TLS 校验默认开启。
- 支持自定义 CA 文件路径，但不得关闭校验作为默认回退。
- 日志不记录完整用户输入、完整输出、Authorization、请求体或供应商响应体。
- 诊断只记录阶段、Provider、模型、耗时、状态类别和匿名诊断 ID。

### 3.9 安装与生命周期

- Python Runtime、Core、模板和内置插件打包为自包含 Sidecar 资源。
- 安装后不依赖仓库路径、系统 Python 或 `uv`。
- 支持首次启动、升级、降级阻止、卸载和重装。
- 卸载默认保留用户历史和设置，并提供明确的“删除本地数据”选项。
- 应用退出、崩溃和卸载后不得残留 Sidecar、下载器或模型任务进程。

## 4. 目标目录

```text
apps/tauri-host/
  src/
    domain/
    views/
    stores/
  src-tauri/src/
    commands/
    config_store.rs
    secret_store.rs
    sidecar/
    tray.rs
    hotkey.rs
    window.rs

packages/reflex-core/
  src/reflex_core/
    provider.py
    template/
    scene/
    usecases/

packages/reflex-runtime/
  src/reflex_runtime/
    plugin_manager.py
    provider_registry.py
    config.py
    context.py

plugins/
  provider-minimax/
  provider-zhipu/
  provider-deepseek/
  provider-alibaba/
  provider-siliconflow/
  semantic-detector/
  history-sqlite/
  translator/
  batch-runner/
  markdown-preview/

template-packs/builtin/
  manifest.json
  content/
  style/
  system/
```

目录可以按实际代码量微调，但所有权边界不得改变。

## 5. Provider 插件契约

### 5.1 元数据

每个 Provider 插件声明：

- `id`
- `display_name`
- `version`
- `models`
- `default_model`
- `required_secret`
- `permissions`

### 5.2 运行接口

```python
class ProviderPlugin(Protocol):
    id: str
    model: str | None

    def configure(self, secret: str, config: ProviderConfig) -> None: ...

    def stream(
        self,
        rendered_request: ModelRequest,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[str]: ...
```

`ModelRequest` 由 Core 模板层生成，至少包含 system/user messages；Provider 只将其映射为供应商请求。

### 5.3 错误类型

Provider 内部错误统一映射为：

- `provider_unconfigured`
- `provider_auth_failed`
- `provider_rate_limited`
- `provider_timeout`
- `provider_network_error`
- `provider_service_error`
- `provider_invalid_response`
- `provider_empty_response`
- `cancelled`

用户界面只显示固定中文/英文消息和恢复动作。原始异常仅允许经过脱敏后进入本地诊断，并且不得包含完整响应体。

## 6. 密钥设计

### 6.1 保存

前端设置页只维护输入控件的瞬时值。点击保存后：

```text
Svelte 临时输入
  -> Tauri save_provider_secret
  -> Rust SecretStore
  -> Windows Credential Manager
  -> 清空前端输入
```

前端只能查询“已配置/未配置”和掩码尾部，不得重新读取完整密钥。

### 6.2 注入 Runtime

Rust Host 在发送 optimize 前读取所选 Provider 密钥，并通过已拥有的匿名 stdin 管道发送私有 `configure_provider` 命令。该命令不能由前端 capability 直接调用。

```text
Rust Credential Manager adapter
  -> 内存中的 configure_provider NDJSON
  -> Python Runtime 内存 ProviderRegistry
  -> Provider 实例
```

密钥不进入进程参数、环境变量、stdout、stderr、日志或持久化配置。Provider 切换、密钥更新和 Runtime 退出时释放旧引用。Python 无法保证物理内存立即擦除，因此安全边界定义为“不持久化、不记录、不跨进程暴露”。

### 6.3 当前用户提供的密钥

设计、代码、测试和提交中不得出现真实密钥。真实联调时必须先由用户通过设置页保存到系统凭据库。联调完成后建议轮换在对话中出现过的密钥。

## 7. 配置设计

非敏感配置保存到 Tauri 应用配置目录，采用带版本 JSON：

```json
{
  "version": 1,
  "provider": "minimax",
  "model": "MiniMax-M2.7-highspeed",
  "mode": "content",
  "style": "balanced",
  "scene_policy": "auto",
  "clipboard_policy": "manual",
  "history_enabled": true,
  "privacy_mode": false,
  "language": "zh-CN",
  "theme": "system",
  "hotkey": "Ctrl+Alt+R",
  "tls_verify": true,
  "ca_bundle_path": null
}
```

配置迁移必须满足：

- 写入前校验。
- 原子替换。
- 保留最近一次有效备份。
- 未知字段忽略并保留兼容。
- 非法值回退安全默认值并产生脱敏诊断。

## 8. Runtime 与插件发现

- 生产态使用 Python entry points 发现插件。
- 仓库开发态允许显式本地插件目录，但不得扫描任意用户目录。
- 插件声明类型和权限，默认禁用第三方未知插件。
- 内置 Provider、模板包和增强插件随安装包发布。
- 单个插件加载失败不阻止 Runtime 启动；所选插件失败时返回可恢复错误。
- Mock Provider 只用于测试和显式开发配置，不允许自动回退。

## 9. UI 信息架构

### 9.1 快速浮窗

保持当前 Figma Current 主体验：

- 输入
- 配置摘要
- 调整
- 唯一主生成按钮
- Generating / Complete / Error 状态

不把历史、批处理和 Provider 参数全部塞回主浮窗。

### 9.2 独立工作视图

- 设置：Provider、模型、密钥状态、默认行为、语言、主题、网络和快捷键。
- 历史：搜索、筛选、评分、详情、导出和修复。
- 批处理：任务列表、进度、错误和导出。
- 插件：内置插件状态、权限和启停。

这些视图使用 Tauri 独立窗口或同窗口路由，不恢复旧版大工作台布局。

### 9.3 结果增强

Complete 状态增加：

- 翻译
- Markdown 预览
- 保存/隐私状态
- 评分

增强动作按需出现，不削弱复制和重新生成主路径。

## 10. 历史数据设计

`history-sqlite` 至少保存：

- 记录 ID
- 创建时间
- 加密输入正文
- 加密输出正文
- mode/style/scene
- Provider/model
- 耗时和状态
- 评分
- 标签

数据库迁移使用递增 schema version。升级前创建备份，迁移失败时回滚并进入只读恢复模式。

历史加密约束：

- 数据密钥由 Rust Host 生成并保存在 Windows Credential Manager。
- Runtime 通过私有匿名管道把数据密钥交给 `history-sqlite`，不得写入数据库或配置。
- 每条记录使用独立随机 nonce 和认证标签。
- Provider、场景、风格、时间和评分等筛选元数据可保持明文；输入和输出始终加密。
- 全文搜索在插件进程内解密候选记录后执行，不建立明文全文索引。
- 轮换密钥前创建完整备份，逐批重加密并记录不含正文的进度检查点。

历史修复流程：

1. `PRAGMA quick_check`
2. 复制原库到备份目录
3. 隔离不可解析记录
4. 重建索引
5. 输出不含正文的修复摘要

## 11. 批处理设计

- 输入支持逐行文本、CSV 指定列和粘贴列表。
- 每个任务使用独立 `request_id`。
- 默认串行或低并发，Provider 并发上限可配置。
- 单项失败不终止整批。
- 取消后停止新任务并取消运行中请求。
- 结果支持 CSV、JSON 和 Markdown 导出。
- 批处理日志不记录完整输入和输出。

## 12. 国际化与主题

- 首发语言：`zh-CN`、`en-US`。
- UI 文案使用稳定 key，不在业务逻辑中拼接两套语言。
- Provider 原始错误不参与翻译；先分类，再映射本地文案。
- 主题支持 `light`、`dark`、`system`。
- 旧版自定义主题通过受校验的 JSON 导入；无效颜色、未知字段和不可读文件不得覆盖当前主题。
- 所有状态在两种语言和两种明暗主题下通过布局检查。

## 13. 交付阶段

### 阶段 A：安全配置与 MiniMax 主链

- ConfigStore
- SecretStore
- PluginManager / ProviderRegistry
- MiniMax Provider
- Runtime 私有密钥配置命令
- 设置页真实保存
- 真实流式、取消和错误联调

### 阶段 B：模板和 42 场景

- 模板包协议与 manifest
- 48 份 Markdown 资产迁移
- 双模式、风格和场景渲染
- L0 识别覆盖扩展

### 阶段 C：桌面宿主能力

- 单实例
- 托盘
- 全局快捷键
- 窗口管理
- 剪贴板完整读写策略

### 阶段 D：历史与结果增强

- history-sqlite
- 搜索/筛选/评分/导出/修复
- translator
- markdown-preview

### 阶段 E：批处理与语义模型

- batch-runner
- semantic-detector
- 模型下载、取消、镜像和回退

### 阶段 F：其余 Provider、i18n 和网络配置

- 智谱、DeepSeek、通义、SiliconFlow
- 中英文
- 主题
- TLS 与自定义 CA

### 阶段 G：打包和发布

- 自包含 Sidecar
- 安装、升级、卸载、重装
- 生命周期、DPI、多显示器和长期运行验证

阶段连续执行，但每阶段独立提交和验收。前一阶段失败时先修复，不把失败带入后一阶段。

## 14. 测试策略

### 14.1 自动测试

- Core：模型、模板、场景、取消、安全和禁止依赖。
- Runtime：插件发现、私有配置命令、多请求、取消、进程退出和错误脱敏。
- Provider：请求映射、SSE/JSON 解析、错误分类、重试、取消和密钥不泄漏。
- Rust：SecretStore、ConfigStore、Sidecar 生命周期、托盘、热键和剪贴板错误。
- 前端：设置、密钥状态、状态机、历史、批处理、i18n 和错误恢复。
- 契约：所有 Provider 使用相同录制夹具通过事件顺序测试。

### 14.2 网络测试

- 默认测试和 CI 完全离线。
- 真实 smoke 必须显式启用，只调用一个 Provider、一个短输入、一次请求。
- smoke 记录 Provider、模型、状态码类别、首包时间、总耗时和取消结果，不记录请求正文、响应正文或密钥。
- 真实调用失败不自动重试付费请求，除非错误类型明确可重试且未收到内容。

### 14.3 可见层验收

- 760×540、680×480、125% 和 150% DPI。
- 中英文、浅色和深色。
- Empty、Ready、Generating、Complete、Error、Settings、History、Batch。
- 长文本、长单词、超长 Provider/模型名称。
- 用户可见层不得出现 Mock、debug、test、验收标签、工具名、内部目录或原始异常。

### 14.4 生命周期

- 安装后首次启动。
- 无系统 Python 启动。
- Runtime 崩溃恢复。
- 应用退出无残留进程。
- 升级保留设置和历史。
- 卸载/重装路径真实执行。

## 15. 提交与发布策略

- 每个阶段使用独立中文提交，遵循项目提交格式。
- Provider、宿主、历史、插件和发布不混在同一提交。
- 每阶段完成后推送远端分支并记录验证证据。
- 最终 `v1.0.0` 只在全部功能矩阵、安装包和生命周期验收通过后创建。

## 16. 回滚策略

- ConfigStore 保留上一版本备份。
- SQLite 迁移前备份，失败回滚到只读模式。
- 新 Provider 可独立禁用，不影响 Mock 测试和其他 Provider。
- 语义模型插件失败回退 L0。
- 新桌面能力通过独立模块接入，可按功能关闭托盘或热键。
- 发布包保留前一稳定版本安装程序。

## 17. 完成定义

只有同时满足以下条件，才可称为“旧版功能已补齐”：

- 旧版 README 声明的能力全部在功能矩阵中通过。
- 42 个场景和 48 份模板资产已校验迁移。
- 五类 Provider 具备离线契约测试，MiniMax 完成真实 smoke。
- 历史、评分、搜索、筛选、导出和修复可用。
- 翻译、批处理、Markdown 和语义模型插件可用。
- 托盘、全局快捷键、单实例、剪贴板和设置持久化可用。
- 中英文、主题、TLS 和隐私策略可用。
- 密钥只存在系统凭据库和受控进程内存。
- 安装、升级、卸载、重装和退出清理均真实执行。
- 自动测试、构建、依赖审计、可见层审计和代码审查无阻断项。
- `resources\` 用户原有未跟踪目录未被误提交。
