# Reflex Next 项目规则

本文件同时是维护者与贡献者的工作约定：无论由人还是由 AI 编码代理执行，
以下边界与规则同等生效。

## 项目概况

- 项目名称：Reflex Next
- 项目类型：轻量桌面产品 / 本地 AI 运行时 / 插件化提示词工具
- 推荐技术栈：Python Core + Tauri 2 + Python 插件系统
- 主要入口：`packages/reflex-core`
- 主要输出物：可嵌入 Python Core、Tauri 小宿主、Provider/模板/场景识别插件

## 当前目标

本项目用于重做 Reflex，不在旧 PyQt 工作台上继续堆功能。

旧版 Reflex（Classic，作者早期内部原型，不以任何形式分发）是行为基线和资产来源；新项目不得直接复制旧 UI 架构。

## 架构边界

Core 禁止依赖：

- PyQt5 / PySide
- Tauri API
- SQLite 默认初始化
- pyperclip
- torch
- sentence-transformers
- huggingface-hub

Core 只允许表达：

- 请求模型
- 事件流
- 模板渲染
- 场景路由
- Provider 协议
- 安全校验、清洗、脱敏

## 插件原则

以下能力必须作为插件或宿主能力，不得进入最小 Core：

- Provider
- 历史记录
- 翻译
- 批处理
- Markdown 预览
- 本地语义模型
- 剪贴板
- 托盘
- 快捷键

## 文档优先

开发前先读：

1. `docs/ARCHITECTURE.md`
2. `docs/MIGRATION.md`
3. `docs/CLASSIC-REFERENCE.md`
4. `workbench/readme.md`
5. `workbench/known-pitfalls.md`

## 变更规则

- 优先保持小步迁移，避免一次性复刻旧项目。
- 每个阶段必须有可验证产物。
- 行为承接旧项目时，先写迁移说明或测试样例。
- 不把真实 API Key、token、账号写入代码、文档、日志或测试。

## 验收底线

- `import reflex_core` 不应导入 PyQt、torch、sentence-transformers 或 sqlite3。
- Provider 错误和日志必须脱敏。
- 场景自动识别失败必须回退通用场景，不得阻塞优化。
- Tauri 宿主只消费事件流，不承载业务内核。
