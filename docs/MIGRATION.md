# Reflex Next 功能迁移文档

更新时间：2026-07-09

## 1. 迁移目标

本迁移不是在现有 PyQt 工作台上继续重构，而是从现有项目中抽取可复用能力，重做一个轻量、插件化、可嵌入的新架构。

目标形态：

```text
旧 Reflex：工作台里包含核心功能
新 Reflex：核心功能外面挂不同宿主和插件
```

迁移原则：

- 先抽核心，再做宿主。
- 先跑通单 Provider，再扩展多 Provider。
- 先做 L0 场景识别，再接 L1 语义模型。
- 先保留行为，再优化体验。
- 不把 PyQt、QThread、SQLite、torch 作为核心依赖。

## 2. 功能分级

### 2.1 必须进入 Core

这些是 Reflex 的核心价值，应迁入 `reflex-core`。

| 功能 | 当前位置 | 新位置 | 迁移方式 |
|---|---|---|---|
| 输入校验 | `api/validators.py` | `core/safety/validate.py` | 提取纯函数 |
| 响应清洗 | `api/validators.py` | `core/safety/sanitize.py` | 提取纯函数 |
| 错误脱敏 | `api/base_client.py` | `core/safety/redact.py` | 独立成统一策略 |
| 模式控制 | `api/prompt_builder.py` | `core/template/resolver.py` | 保留 content/prompt 两种模式 |
| 风格控制 | `api/prompt_builder.py` | `core/template/style.py` | 提取 style spec |
| 场景路由 | `core/scene_registry.py` | `core/scene/router.py` | 加入自动识别策略 |
| 模板渲染 | `api/prompt_builder.py`、`resources/templates` | `template_packs/builtin` | 迁为模板包 |
| 流式结果 | `core/optimization_worker.py` | `core/events.py` | 改为事件流 |
| 优化用例 | `OptimizationService/Controller` | `core/usecases/optimize.py` | 去掉 PyQt 和历史写入 |

### 2.2 必须进入 Runtime

这些是运行时能力，不属于纯 Core。

| 功能 | 当前位置 | 新位置 | 说明 |
|---|---|---|---|
| Provider 注册 | `api/factory.py` | `runtime/plugin_manager.py` | 从类注册改为插件发现 |
| 配置读取 | `config/config_manager.py` | `runtime/config_store.py` | 拆成核心配置和宿主配置 |
| 密钥存储 | `utils/crypto.py` | `runtime/secret_store.py` | 宿主负责安全存储适配 |
| 取消控制 | `OptimizationThread.cancel()` | `runtime/cancellation.py` | 与 UI 框架无关 |
| 日志策略 | `utils/logger.py` | `runtime/logging.py` | 默认脱敏 |
| 权限策略 | 无统一实现 | `runtime/permissions.py` | 插件按权限运行 |

### 2.3 应做成插件

这些有价值，但不应默认压进最小内核。

| 功能 | 当前位置 | 新插件 |
|---|---|---|
| MiniMax | `api/minimax_client.py` | `reflex-provider-minimax` |
| 智谱 / SiliconFlow | `api/siliconflow_client.py` | `reflex-provider-zhipu` / `reflex-provider-siliconflow` |
| 通义千问 | `api/alibaba_client.py` | `reflex-provider-qwen` |
| DeepSeek | `api/deepseek_client.py` | `reflex-provider-deepseek` |
| 历史记录 | `database/history_manager.py` | `reflex-plugin-history-sqlite` |
| 翻译 | `services/translation_service.py`、`ui/services/translation_service.py` | `reflex-plugin-translator` |
| 批处理 | `ui/batch_process_dialog.py` | `reflex-plugin-batch-runner` |
| 语义场景识别 | `utils/scene_classifier.py`、`utils/model_downloader.py` | `reflex-plugin-semantic-detector` |
| 模板管理 | `ui/prompt_manager_dialog.py`、`ui/template_dialog.py` | `reflex-plugin-template-manager` |
| Markdown 预览 | `ui/markdown_preview_dialog.py` | `reflex-plugin-markdown-preview` |
| 评分 | `HistoryManager.update_rating` | `history` 插件能力 |

### 2.4 不迁入首版

这些属于重工作台体验，首版不迁。

- 欢迎页
- 大设置页
- 大历史管理窗口
- 复杂主题系统
- 多窗口支持
- 托盘复杂菜单
- 批量导入导出
- 历史修复工具
- 完整 i18n UI

## 3. 现有模块迁移判断

### 3.1 `ui/`

当前 `ui/` 是最大重量来源。

处理方式：

```text
不迁移 UI 代码到 Core。
只参考交互经验，重新做 Tauri 小宿主。
```

可参考：

- 主输入输出布局
- 优化状态反馈
- 模式、风格、模型选择
- 错误提示文案

不可直接迁入：

- `MainViewModel`
- `ReflexMainWindow`
- 各类 `QDialog`
- `QThread` worker
- PyQt signal

### 3.2 `api/`

`api/` 里有可复用资产，但需要拆开。

保留：

- Provider 请求字段映射
- 流式解析逻辑
- HTTP 错误分类
- Prompt 构建思路

重写：

- `BaseAIClient` 不能继续做全能基类
- Provider 不应负责模板选择
- Provider 不应负责缓存和历史
- Provider 不应直接决定产品模式

新结构：

```text
ProviderPlugin = 供应商协议适配
TemplateResolver = 模板与场景
OptimizeUseCase = 业务编排
```

### 3.3 `core/`

当前 `core/optimization_worker.py` 的业务意图可保留，但实现要重写。

迁移方向：

```text
OptimizationThread -> EventStream
OptimizationController -> OptimizeUseCase
OptimizationService -> Host Adapter
```

不要迁入：

- `QThread`
- `pyqtSignal`
- `thread.wait()`
- 直接写历史
- 自动复制剪贴板

### 3.4 `config/`

当前配置太宽，混合了 UI、模型、历史、窗口、性能、安全。

新配置拆分：

```text
core config:
  default_provider
  default_model
  default_style
  default_mode
  scene_policy
  timeout
  tls_verify

host config:
  hotkey
  window_position
  tray_enabled
  clipboard_policy
  theme

plugin config:
  每个插件独立 namespace
```

### 3.5 `database/`

历史记录不进入核心。

迁移为：

```text
StoragePlugin
  save_result()
  query()
  update_rating()
  export()
```

首版可以不带历史插件，只保留最近一次结果。

### 3.6 `utils/scene_classifier.py`

语义识别功能保留，但从默认链路拆出。

迁移为：

```text
Scene Router:
  L0 builtin rule detector
  L1 semantic detector plugin
  L2 provider detector plugin
```

当前 `sentence-transformers`、`torch`、模型下载器必须只在 L1 插件启用时导入。

## 4. 新架构功能迁移表

| 旧功能 | 新架构位置 | 首版 | 备注 |
|---|---|---:|---|
| 内容优化 | `core/usecases/optimize.py` | 是 | 核心 |
| 提示词生成 | `core/usecases/optimize.py` | 是 | 核心 |
| 简洁/平衡/详细/创意 | `core/template/style.py` | 是 | 核心 |
| 40+ 场景 | `template_packs/builtin` | 是 | 可先迁常用场景 |
| 自动场景识别 L0 | `core/scene/rule_detector.py` | 是 | 零依赖 |
| 自动场景识别 L1 | `plugins/semantic_detector` | 否 | 第二阶段 |
| MiniMax | `providers/minimax` | 是 | 第一个 Provider |
| 智谱/通义/DeepSeek | `providers/*` | 否 | 第二阶段 |
| 流式输出 | `core/events.py` | 是 | 核心 |
| API Key 加密 | `runtime/secret_store.py` | 是 | 宿主适配 |
| 历史记录 | `plugins/history_sqlite` | 否 | 插件 |
| 翻译 | `plugins/translator` | 否 | 插件 |
| 批处理 | `plugins/batch_runner` | 否 | 插件 |
| Markdown 预览 | `plugins/markdown_preview` | 否 | 插件 |
| 评分 | `plugins/history_sqlite` | 否 | 插件 |
| 设置大窗 | Tauri settings view | 否 | 简化 |
| 托盘 | `hosts/tauri` | 是 | 宿主 |
| 全局快捷键 | `hosts/tauri` | 是 | 宿主 |
| 剪贴板 | `hosts/tauri` | 是 | 宿主 |

## 5. 分阶段计划

### 阶段 0：冻结旧行为

目标：

- 保留现有项目作为行为参考。
- 明确哪些测试代表核心行为。

产出：

- 核心行为测试清单
- 现有 Prompt 构建样例
- MiniMax 流式响应样例
- 场景映射样例

验收：

- 能用样例描述旧功能输出预期。
- 后续重写不依赖人工回忆。

### 阶段 1：抽取 Core

目标：

- 创建 `reflex-core`。
- 不依赖 PyQt。
- 跑通单次优化。

必须完成：

- `OptimizeRequest`
- `OptimizeResult`
- `Event`
- `OptimizeUseCase`
- `TemplateResolver`
- `RuleSceneDetector`
- `Safety` 工具

验收：

```python
from reflex_core import OptimizeUseCase, OptimizeRequest

events = use_case.optimize(OptimizeRequest(text="写一封求职邮件"))
```

运行时不得导入：

- PyQt5
- torch
- sentence_transformers
- sqlite3

### 阶段 2：迁移 MiniMax Provider

目标：

- MiniMax 作为第一个 Provider 插件。
- 支持流式事件。

必须完成：

- `ProviderPlugin` 协议
- `ModelRequest`
- `ModelEvent`
- MiniMax 请求构造
- MiniMax 流式解析
- 错误脱敏

验收：

- 能收到 `status/request/chunk/done/error` 事件。
- 日志不含 API Key。
- 日志不含完整用户输入。

### 阶段 3：迁移内置模板包

目标：

- 将现有 `resources/templates` 迁为模板包。
- 保留模式、风格、场景。

必须完成：

- `TemplatePack` 协议
- `SceneSpec`
- `StyleSpec`
- content/prompt 两种模式渲染
- 常用场景优先迁移

优先场景：

- general
- article_writing
- email
- code_generation
- code_review
- doc_translation
- report_writing
- problem_diagnosis

验收：

- 同一输入在不同风格下生成不同请求。
- 手动选择场景时跳过自动识别。
- 自动识别场景时能选择对应模板。

### 阶段 4：Tauri 小宿主

目标：

- 替代 PyQt 大工作台。
- 做小浮窗和托盘体验。

必须完成：

- 全局快捷键
- 托盘
- 小浮窗
- 剪贴板读取/写入
- Provider 设置
- API Key 设置
- 流式输出区域

验收：

- 不打开大窗口也能完成一次优化。
- 点击托盘可打开小浮窗。
- 按快捷键可呼出。
- 首包前能看到状态提示。

### 阶段 5：插件系统

目标：

- 通过 entry points 发现插件。
- 插件按类型注册。

必须完成：

- `PluginManager`
- 插件元信息
- 权限声明
- 插件启停
- 插件配置 namespace

验收：

- 安装一个 Provider 插件后无需改 Core 代码即可识别。
- 禁用插件后核心仍可运行。

### 阶段 6：迁移语义场景识别

目标：

- 保留自动识别优势。
- 不让重模型拖慢启动。

必须完成：

- L1 semantic detector 插件
- 懒加载
- 模型存在性检测
- 下载状态事件
- 失败回退

验收：

- 未启用插件时不导入 `torch`。
- 未下载模型时不阻塞优化。
- 启用插件后能返回场景和置信度。
- 失败时回退 `general`。

### 阶段 7：按需迁移增强插件

迁移顺序建议：

1. History SQLite
2. Translator
3. Batch Runner
4. Template Manager
5. Markdown Preview

每个插件单独验收，不与 Core 混改。

## 6. 首版最小闭环

首版只需要做到：

```text
Tauri 小浮窗
  -> 输入文本
  -> L0 自动场景识别
  -> 内置模板包
  -> MiniMax Provider
  -> 流式输出
  -> 一键复制
```

首版不需要：

- 历史列表
- 批处理
- 翻译对比
- 本地语义模型
- 大设置页
- Markdown 预览

这样可以避免一开始又变成重工作台。

## 7. 风险和取舍

### 7.1 Python sidecar 复杂度

Tauri 与 Python Core 的集成有两条路线：

```text
路线 A：Python sidecar 进程
路线 B：嵌入式 Python runtime
```

推荐先用路线 A。

原因：

- 调试简单
- 崩溃隔离
- 插件安装更自然
- 不需要一开始解决嵌入式 Python 打包复杂度

### 7.2 插件安全

Python 插件本质上有代码执行能力，因此要用权限声明和安装来源控制降低风险。

首版策略：

- 只加载本地可信插件目录。
- 插件声明权限。
- 默认不允许插件读取密钥，除非 Provider 类型并绑定指定 Provider。
- 日志统一走 Runtime 脱敏。

### 7.3 语义识别准确率

L0 规则识别不会像语义模型一样准，但它足够快，适合作为默认。

策略：

- 默认 L0。
- 用户开启“更准确识别”后启用 L1。
- Provider 路由识别作为不安装本地模型时的替代。

## 8. 代码迁移禁止事项

禁止把以下内容迁入 `reflex-core`：

- `PyQt5`
- `QThread`
- `pyqtSignal`
- `QTimer`
- `QWidget`
- `QDialog`
- `sqlite3` 默认初始化
- `pyperclip`
- `torch`
- `sentence_transformers`
- `huggingface_hub`

禁止在 Core 中做：

- 自动打开窗口
- 自动复制剪贴板
- 自动写历史数据库
- 启动时下载模型
- 启动时检查 CUDA
- 直接读取 UI 配置项

## 9. 迁移完成标准

Core 完成：

- 可以无 UI 调用优化。
- 可以自动识别场景。
- 可以渲染模板。
- 可以通过 Provider 插件流式返回。
- 可以脱敏错误和日志。

Host 完成：

- 可以托盘运行。
- 可以快捷键呼出。
- 可以剪贴板读写。
- 可以显示状态、片段、完成和错误事件。

Plugin 完成：

- Provider 可插拔。
- 模板包可插拔。
- 场景识别器可插拔。
- 历史、翻译、批处理不影响最小启动。

最终验收：

```text
用户不打开大工作台，也能在 3 步内完成一次提示词优化：
快捷键呼出 -> 输入或读取剪贴板 -> 流式生成并复制结果。
```
