# Reflex Next 架构设计

更新时间：2026-08-29

当前实现审计请先阅读 [架构审计](ARCHITECTURE-AUDIT.md) 和
[架构债务登记](ARCHITECTURE-DEBT-REGISTER.md)。本文保留设计基线；实际发布状态以
最新验证证据（`docs/verification/`）为准。

## 1. 设计结论

Reflex Next 不继续沿用“PyQt 大工作台”作为产品本体，而是重做为：

```text
Python Core + Tauri 轻量桌面宿主 + Python 插件系统
```

核心判断：

- 现有项目已经复现了主要功能，但核心能力还没有从工作台中抽取出来。
- 新版本应先建立无 UI、无 PyQt、可测试、可嵌入的 `reflex-core`。
- 桌面界面只是一个宿主，不再承载业务内核。
- 历史、翻译、批处理、语义模型、模板管理等能力应按插件装载。
- 语义场景自动识别属于核心体验，但重模型实现不能成为核心依赖。

一句话目标：

```text
任意宿主给 Reflex Core 一段文本，Core 根据模式、风格、场景路由和模板生成模型请求，
通过 Provider 插件流式返回结果，并把状态、片段、错误、安全信息以事件流形式交还宿主。
```

## 2. 核心产品能力

Reflex 的核心不是大窗口、设置页或历史列表，而是以下能力组合：

1. 输入校验
2. 场景自动路由
3. 风格控制
4. 模式选择
5. 模板渲染
6. Provider 调用
7. 流式事件返回
8. 响应清洗
9. 错误与密钥脱敏

最小业务流：

```text
用户输入
  -> Validate
  -> Scene Router
  -> Template Resolver
  -> Provider Plugin
  -> Event Stream
  -> Host 渲染 / 复制 / 保存
```

## 3. 推荐技术栈

### 3.1 核心层

```text
语言：Python 3.11 或 3.12
数据模型：dataclasses 或 pydantic
测试：pytest
插件发现：Python packaging entry points
配置：TOML / JSON
```

网络客户端（`httpx` / `requests`）只允许出现在 Provider、Host 或 Cloud
适配层，不属于 `reflex-core` 的核心运行时依赖。Core 只定义请求模型、事件
协议和纯业务用例，由外层适配器提供网络能力。

核心层禁止依赖：

- PyQt5 / PySide
- Tauri API
- 系统托盘
- 窗口对象
- SQLite 默认初始化
- torch / sentence-transformers 默认导入

### 3.2 桌面宿主

```text
框架：Tauri 2
系统桥接：Rust
前端：Svelte 或 React，推荐 Svelte
桌面能力：托盘、全局快捷键、剪贴板、小浮窗、设置页
```

Tauri 在新架构中的定位：

```text
Tauri 是轻量桌面外壳，不是 AI 内核。
```

### 3.3 插件层

插件采用 Python package 形式发布，通过 `pyproject.toml` entry points 注册。

插件类型：

- `provider`：模型供应商适配
- `command`：用户可执行动作
- `template_pack`：模板包
- `scene_detector`：场景识别器
- `storage`：历史、收藏、统计等存储插件
- `transformer`：翻译、改写、格式转换等文本变换插件

## 4. 分层架构

```text
reflex-core
  models / events / safety / template / optimize use case

reflex-runtime
  RuntimeContext / PluginManager / ConfigStore / SecretStore / PermissionPolicy

reflex-host-tauri
  tray / hotkey / clipboard / floating window / settings

reflex-plugins
  providers / template packs / scene detectors / storage / commands
```

推荐目录：

```text
reflex_next/
  core/
    models.py
    events.py
    usecases/
      optimize.py
    template/
      resolver.py
      pack.py
    scene/
      router.py
      detectors.py
    safety/
      validate.py
      redact.py
      sanitize.py
  runtime/
    context.py
    plugin_manager.py
    config_store.py
    secret_store.py
    permissions.py
  providers/
    minimax/
    openai_compatible/
    qwen/
  template_packs/
    builtin/
  hosts/
    tauri/
    cli/
    legacy_pyqt_adapter/
  plugins/
    history_sqlite/
    semantic_detector/
    batch_runner/
    translator/
```

## 5. 核心请求模型

```python
@dataclass
class OptimizeRequest:
    text: str
    mode: str = "content"
    style: str = "balanced"
    scene: str | None = None
    scene_policy: str = "auto"
    provider: str | None = None
    model: str | None = None
    stream: bool = True
    metadata: dict[str, object] = field(default_factory=dict)
```

字段说明：

- `mode`：`content` 表示优化内容，`prompt` 表示生成结构化提示词。
- `style`：`concise` / `balanced` / `detailed` / `creative`。
- `scene`：为空时进入自动识别。
- `scene_policy`：`auto` / `manual` / `ask`。
- `provider`：为空时由运行时配置选择默认 Provider。

## 6. 事件流协议

Core 不直接操作 UI，只产出事件。

```python
@dataclass
class Event:
    type: str
    data: dict[str, object]
```

基础事件：

```text
status      用户可见状态，例如“正在连接模型服务”
scene       场景识别结果
request     请求已发出
chunk       流式文本片段
done        完成结果
error       用户可见错误
metric      耗时、模型、token 等统计
```

示例：

```text
status: 正在分析场景
scene: code_review, confidence=0.86, method=semantic
status: 正在连接模型服务
chunk: ...
done: final_text
```

## 7. Provider 插件协议

Provider 插件只负责把统一模型请求转为供应商请求，并把响应转成事件。

```python
from collections.abc import Iterable
from typing import Any

from reflex_core import CancellationToken, OptimizeRequest, ProviderEvent


class ProviderPlugin:
    id: str
    model: str | None

    def stream_events(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[ProviderEvent]:
        ...
```

Core 通过 `ProviderEvent` 统一承载开始、文本增量、用量、完成、错误和取消事件。
旧版仅提供 `stream` 的第三方 Provider 只在 `iter_provider_events` 兼容边界转换，
新的 Provider 不应再实现旧签名。

Provider 插件必须遵守：

- 不记录明文 API Key。
- 不记录完整用户输入。
- 所有错误先脱敏再返回。
- 支持超时。
- 支持取消。
- 支持流式输出；不支持流式时由 Core 聚合为兼容事件。

首批 Provider：

```text
minimax
openai_compatible
qwen
zhipu
```

## 8. 模板包协议

模板包提供场景、风格和渲染规则。

```python
class TemplatePack:
    id: str
    version: str

    def list_scenes(self) -> list[SceneSpec]:
        ...

    def list_styles(self) -> list[StyleSpec]:
        ...

    def render(self, request: OptimizeRequest, scene: SceneSpec) -> PromptMessages:
        ...
```

现有 `resources/templates` 适合迁移为默认模板包：

```text
reflex-template-pack-builtin
```

模板包不应依赖 Provider，也不应依赖桌面 UI。

## 9. 场景自动识别

语义场景自动识别应进入新核心体验，但必须分层实现，避免重依赖拖慢启动。

场景识别链：

```text
Scene Router
  -> L0 轻量规则识别
  -> L1 本地语义识别
  -> L2 Provider 路由识别
  -> fallback general
```

### 9.1 L0 轻量规则识别

默认内置，零额外依赖。

识别依据：

- 代码块
- 文件扩展名
- 中英文比例
- 翻译关键词
- 邮件格式
- 表格、列表、报告结构
- 明显业务词、学习词、问题诊断词

优点：

- 启动快
- 稳定
- 不下载模型
- 不阻塞优化

### 9.2 L1 本地语义识别

作为可选插件。

```text
reflex-plugin-semantic-detector
```

要求：

- 懒加载
- 用户显式启用
- 模型未下载时不自动阻塞主流程
- 下载进度通过事件返回
- 失败回退 `general`

### 9.3 L2 Provider 路由识别

用当前 Provider 做一次轻量分类请求。

适用场景：

- 用户希望更准确
- 本地不安装语义模型
- 可以接受一次额外请求成本

### 9.4 场景识别接口

```python
class SceneDetectorPlugin:
    id: str
    priority: int

    def detect(self, text: str, context: RuntimeContext) -> SceneDetectionResult:
        ...
```

返回：

```python
@dataclass
class SceneDetectionResult:
    scene: str
    confidence: float
    method: str
    reason: str = ""
```

关键原则：

- 场景识别是核心流程的一环。
- 语义模型不是核心依赖。
- 识别失败不能阻塞优化。
- 置信度不足时回退 `general`。
- 手动选择场景时跳过自动识别。

## 10. RuntimeContext

现有项目存在多个全局单例。新架构统一通过 `RuntimeContext` 显式传递依赖。

```python
@dataclass
class RuntimeContext:
    config: ConfigStore
    secrets: SecretStore
    plugins: PluginManager
    logger: Logger
    permissions: PermissionPolicy
    cancellation: CancellationToken
```

禁止在 Core 中使用：

- 全局下载器
- 全局 Provider 管理器
- 全局场景分类器
- 全局隐私管理器
- 全局历史服务

## 11. 桌面宿主体验

第一版桌面宿主只做小工具，不做大工作台。

主体验：

```text
全局快捷键
  -> 呼出小浮窗
  -> 自动读取剪贴板或当前输入
  -> 自动识别场景
  -> 选择风格 / 模式 / 模型
  -> 流式输出
  -> 一键复制 / 替换剪贴板
```

托盘菜单：

- 打开小浮窗
- 最近一次结果
- 插件管理
- 设置
- 退出

设置页只保留最小项：

- 默认 Provider
- API Key
- 默认模型
- 默认模式
- 默认风格
- 场景识别策略
- 插件开关

## 12. 安全边界

Core 层必须统一处理：

- API Key 脱敏
- Bearer Token 脱敏
- Provider 错误脱敏
- 日志不记录完整 Prompt
- 历史插件保存前可配置脱敏策略
- 插件权限声明

插件权限建议：

```text
network       允许访问网络
secrets       允许读取指定 Provider 密钥
clipboard     允许读写剪贴板
storage       允许写入本地存储
model_cache   允许下载或读取本地模型
```

## 13. 首版范围

首版只做：

- `reflex-core`
- `reflex-runtime`
- MiniMax Provider
- 内置模板包
- L0 场景规则识别
- Tauri 小浮窗
- 托盘
- 全局快捷键
- 剪贴板复制

不进入首版：

- 批处理
- 大历史管理器
- Markdown 预览
- 欢迎页
- 大设置页
- 本地语义模型
- 多语言完整 UI
- 复杂主题系统

## 14. 验收标准

架构验收：

- 导入 `reflex_core` 不导入 PyQt、torch、sentence-transformers。
- 不启动窗口也能执行一次优化。
- Provider 可通过插件注册。
- 模板可通过模板包替换。
- 场景识别失败不阻塞优化。
- Tauri 宿主只消费事件，不承载业务逻辑。
- API Key 不出现在日志、错误、历史导出和事件文本中。

性能验收：

- 冷启动不加载语义模型。
- 无插件时核心导入时间可控。
- 首次优化可看到状态事件和首包事件。
- 取消请求不会阻塞主界面。

产品验收：

- 用户按快捷键即可完成一次输入优化。
- 默认体验不需要打开大工作台。
- 插件关闭后核心仍可运行。
