# Reflex Next

Reflex Next 是一个本地优先、插件化的 AI 文本工具。它使用 Python Core 承载业务逻辑，
通过 Python Runtime 和插件连接模型能力，并由 Tauri 2 提供轻量桌面宿主。

```text
Python Core + Python Runtime/插件 + Tauri 2/Rust Host + Svelte UI
```

## 当前状态

- 当前版本：`v0.7.0-alpha.8`；
- 核心产品功能、桌面主链、增强插件和 Reflex Cloud 闭环已基本实现；
- 真实 MiniMax 流式请求和取消已有脱敏实机证据；
- Cloud 反馈、隐私授权、免费额度、质量发布、回滚和 PostgreSQL 多实例并发已有验证；
- 正式 72 小时浸泡、Windows 10 生命周期、真实旧版本升级、
  代码签名和受控试用仍未完成。

本版本适合开发和内部验收，不是可公开推广的正式稳定版。当前任务状态以
[生产任务账本](workbench/backend-production-tasks.md)为准。

## 主要能力

- 内容优化与结构化提示词生成；
- 自动或手动场景选择、模式、风格和语言控制；
- MiniMax 与 OpenAI-compatible Provider 插件；
- 流式输出、取消、超时、有限重试和稳定错误分类；
- 历史、翻译、批处理、Markdown 预览和可选语义识别插件；
- 托盘、全局快捷键、剪贴板、设置和 Windows Credential Manager；
- 可选 Reflex Cloud：匿名安装身份、免费额度、反馈、截图、改进计划、数据删除和质量发布。

## 架构边界

- `reflex-core` 不依赖 PyQt、Tauri API、SQLite、剪贴板或本地语义模型；
- Runtime 负责插件发现、配置、取消、并发和 Sidecar 协议；
- Provider 只处理供应商协议，不决定场景、模板或产品模式；
- 历史、翻译、批处理、Markdown 和语义模型保持插件化；
- Tauri Host 只承载桌面能力和事件渲染，不承载业务内核；
- 密钥、错误、日志、诊断和反馈数据遵守脱敏与分项授权边界。

## 目录结构

```text
apps/
  tauri-host/                    Tauri 2、Rust Host 和 Svelte 前端
packages/
  reflex-core/                   无 UI Python 核心
  reflex-runtime/                Python Sidecar 与插件运行时
plugins/
  provider-minimax/              MiniMax Provider
  provider-openai-compatible/    OpenAI-compatible Provider
  history-sqlite/                本地加密历史
  translator/                    翻译
  batch-runner/                  批处理
  markdown-preview/              Markdown 预览
  semantic-detector/             可选本地语义识别
template-packs/
  builtin/                       内置模板和场景
services/
  reflex-cloud/                  可独立部署的 Cloud 服务
tools/                           验证、构建、浸泡、SBOM 和发布工具
docs/                            架构、部署、发布和验证文档
workbench/                       当前任务账本与项目内部状态
```

## 文档入口

- [统一文档导航](docs/INDEX.md)
- [架构设计](docs/ARCHITECTURE.md)
- [功能迁移](docs/MIGRATION.md)
- [UI 实现规格](docs/UI-IMPLEMENTATION-SPEC.md)
- [后端生产化路线图](docs/BACKEND-PRODUCTION-ROADMAP.md)
- [Cloud Beta 部署说明](docs/CLOUD-BETA-RELEASE.md)
- [隐私说明](docs/PRIVACY.md)
- [支持范围](docs/SUPPORT.md)
- [故障处理](docs/TROUBLESHOOTING.md)
- [发布恢复指南](docs/RELEASE-RECOVERY.md)

## 开发与验证

查看统一验证步骤：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\verify_backend.ps1 -ListSteps
```

执行低资源验证：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\verify_backend.ps1 -SkipHeavy
```

启动桌面开发环境：

```powershell
cd apps\tauri-host
npm run tauri:dev
```

Reflex Cloud 默认本机地址为 `http://127.0.0.1:8787`。部署和生产环境变量要求见
[Cloud Beta 部署说明](docs/CLOUD-BETA-RELEASE.md)。Cloud 未部署时，本地 Core 和桌面主链仍可独立运行。

## 安全约束

- 不把 API Key、Token 或账号写入仓库、日志、安装包和诊断包；
- 客户端自备 Provider 密钥不上传到 Reflex Cloud；
- 改进计划默认关闭，提示词、结果和截图按授权分别处理；
- Release 构建拒绝开发 Mock Provider；
- 正式发布前必须完成代码签名、安装生命周期、回滚和发布物审计。
