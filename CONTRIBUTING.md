# 贡献指南

感谢关注 Reflex Next。本项目处于 alpha 阶段，欢迎 Issue 与 PR，但请先阅读
[AGENTS.md](AGENTS.md) 与 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，
理解项目的架构边界后再动手。

## 架构红线（PR 不符合将直接被拒）

- `packages/reflex-core` 禁止依赖 PyQt/PySide、Tauri API、SQLite 初始化、
  pyperclip、torch、sentence-transformers、huggingface-hub；
- Provider、历史、翻译、批处理、Markdown 预览、语义模型、剪贴板、托盘、
  快捷键必须保持插件化或宿主能力，不得下沉进最小 Core；
- Tauri 宿主只消费事件流，不承载业务内核；
- 不把真实 API Key、token、账号写入代码、文档、日志或测试。

## 开发环境

- Windows 10/11（当前主平台）
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node.js 22 + npm
- Rust stable（Tauri 2 宿主）

```powershell
# 前端依赖
npm --prefix apps/tauri-host ci
# Python 依赖（各 package/plugin 内均有 uv.lock）
uv sync --frozen
```

## 本地验证门禁

提交前请确保以下门禁全部通过（与 CI 一致）：

```powershell
# 前端：类型检查 + lint + 单测（当前 222 例）
npm --prefix apps/tauri-host run typecheck
npm --prefix apps/tauri-host run lint
npm --prefix apps/tauri-host test

# 后端 + 集成验证（等价 CI 的锁定后端验证，含大量门禁时较慢）
.\tools\verify_backend.ps1 -SkipHeavy -SkipDependencyAudit -SkipReleaseMaterials

# 工具契约自检
.\tools\tests\verify_backend_contract.ps1
.\tools\tests\verify_windows_lifecycle_contract.ps1
```

## 提交规范

- 提交信息格式：`类型: 摘要`，类型取 `feat / fix / opt / refactor / docs / conf / chore / ci`；
- 遵循小步迁移：一次 PR 只做一件事，每个阶段必须有可验证产物；
- 行为承接旧版 Reflex（Classic）时，先写迁移说明或测试样例；
- 涉及脱敏、密钥、隐私授权的改动，必须在 PR 描述中说明验证方式。

## Issue 与 PR

- Bug 报告请附：版本号、复现步骤、脱敏后的日志片段（不要贴 API Key）；
- 功能建议请先说明是否属于 Core / 插件 / 宿主职责，避免破坏架构边界；
- 安全问题不要走公开 Issue，参见 [SECURITY.md](SECURITY.md)。

## 许可证

提交即表示你同意以 [MIT License](LICENSE) 授权你的贡献。
