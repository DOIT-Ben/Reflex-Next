# 历史记录：历史与增强能力验证（2026-07-12）

更新日期：2026-07-12

> 历史证据提示：本文记录旧工作树的增强能力验证，不代表当前工作树的完整发布门禁。

## 结论

Stage D 已完成历史工作视图、结果保存与评分、流式翻译、安全 Markdown 预览、可选本地语义识别，以及批量导入、执行与导出。增强能力均通过 Runtime 插件协议接入，Tauri Host 只负责权限同步、事件消费和用户交互，`reflex-core` 未增加宿主、存储、网络或重模型依赖。

本轮未读取或使用真实 Provider 密钥。真实 MiniMax 在线请求仍需用户在应用设置中保存密钥后执行。可选的 `plugins\semantic-detector` 只在已启用且本地模型可用时惰性加载；模型不可用或低置信时，Runtime 回退已覆盖 42 场景的 Core L0 规则识别，并在识别失败时回退通用场景。

## 自动化结果

| 范围 | 结果 |
|---|---|
| Core | 78 passed；禁止依赖导入检查通过 |
| Runtime（含 builtins） | 213 passed |
| History SQLite | 123 passed |
| Translator | 15 passed |
| Markdown Preview | 12 passed |
| MiniMax Provider | 18 passed |
| Batch Runner | 2 passed |
| 前端 | 125 passed |
| 前端生产构建 | 通过，0 warnings |
| 前端生产依赖 | 0 vulnerabilities |
| Rust Host | 131 passed，2 ignored |
| Rust 格式与构建 | 通过 |

Rust 忽略项为依赖 Windows 凭据管理器的真实后端探针，不影响内存后端、错误脱敏、保存、删除和状态读取测试。

## 运行时验证

- Translator 真实 Sidecar Mock 链路按 `started -> chunk -> result` 完成，取消后不再产生结果事件。
- Markdown Preview 真实 NDJSON Sidecar 链路按 `plugin_configured -> started -> result` 完成，stderr 为空且进程正常退出。
- Markdown 恶意样例中的 `script`、`javascript:` URL、远程图片和事件属性不会进入最终 HTML。
- Provider-backed 插件只获得 Runtime 注入的受限 gateway，不读取密钥、不创建 HTTP 客户端，也不接收原始 Provider 配置字段。
- Batch Runner 只解析和导出内存文本，不申请文件系统或密钥权限；Host 使用既有 CoreBridge 逐项执行，并将并发限制在 1 至 4。

## 用户可见层检查

- Translator 在 `760x540` 和 `680x480` 视口无页面或对话框溢出，支持自动/中文/English、取消、重试、复制和设为当前结果。
- Markdown Preview 在 `760x540` 和 `480x520` 视口无页面溢出，分栏、源码和预览模式尺寸稳定，窄屏自动改为纵向布局。
- 两个对话框均支持 Esc 关闭并恢复“更多操作”焦点；浏览器控制台错误为 0。
- 批处理入口同时位于默认页和完成结果的更多操作菜单；在桌面与 `390x800` 窄屏验证中，格式、风格、场景、并发、解析、状态列表与底部操作区均可见，Esc 可关闭。
- 预览链接不可导航，远程图片不渲染；浏览器回退环境无 Runtime 时只显示固定安全错误。
- 页面未出现阶段名、版本标签、调试状态、测试提示、工具名或内部目录等生产管理信息。

## 安全与边界

- `import reflex_core` 不导入 PyQt、PySide、sqlite3、pyperclip、torch、sentence-transformers 或 huggingface-hub。
- 历史密钥只存在于宿主凭据存储和 Runtime 私有配置路径，公共插件事件不携带密钥或私有配置。
- Translator 固定使用 `doc_translation`、`precise` 和 `content`，Provider 异常仅返回安全错误码。
- Markdown 使用 Python-Markdown 解析并由 Bleach 白名单清洗；不允许图片、样式、脚本、嵌入对象、SVG、MathML、事件属性或危险协议。
- 生产代码、文档和暂存内容未发现真实 API Key、Bearer 值或 Authorization 值。
- `resources\` 保持 27 个文件，聚合 SHA-256 为 `3BAF82F50AA911BBC68DE1851741BD5B14AF06D3D1E6F5B994D90E761A5B236D`，未暂存且不进入提交。

## 残余与发布前检查

- 真实 MiniMax 在线翻译和优化需要用户在应用内配置凭据后进行一次人工验收；自动化未读取聊天中出现过的任何密钥。
- Windows 通知区域菜单逐项点击和凭据管理器真实探针仍属于发布前实机检查。
- L1 本地模型下载与状态管理仍属于发布前宿主能力；当前插件不会自动下载模型，也不影响 L0 场景识别和失败回退。

## 回退

- 可在设置中分别关闭 Translator、Markdown Preview、Batch Runner 与 Semantic Detector，Core 优化主链保持可用。
- Translator、Markdown Preview 或 Batch Runner 插件不可用时，宿主保留当前内容，只显示固定错误并允许重试或关闭。
- Stage D 提交按职责独立，可逐提交回退，不需要迁移或删除用户数据。
