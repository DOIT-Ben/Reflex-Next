# 历史记录：内置模板与场景验证（2026-07-11）

更新日期：2026-07-11

> 历史证据提示：本文记录旧工作树中 42 个 L0 识别场景的离线验证，不等同于当前完整场景目录数量或当前发布门禁。

## 结论

内置模板包、42 场景 L0 识别、Core 渲染、Runtime 接线和 Tauri 手动场景选择已通过离线验证。模板包缺失或损坏时保留通用回退，不阻塞生成；当前仓库未跟踪的 `resources\` 未被读取为新模板包、未被修改、未进入暂存或提交。

真实 MiniMax 付费请求不属于本轮离线验证。该门禁仍需用户在应用设置页手动保存密钥后执行，不能从聊天记录、命令、环境变量或文件导入。

## 自动化结果

| 范围 | 命令 | 结果 |
|---|---|---|
| Core | `uv run --python 3.12 --with pytest pytest -q` | 75 passed |
| Runtime | `uv run --python 3.12 --with pytest --with httpx pytest -q` | 32 passed |
| MiniMax Provider | `uv run --python 3.12 --with pytest --with httpx pytest -q` | 18 passed |
| 前端 | `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2` | 41 passed |
| 前端构建 | `npm run build` | 通过 |
| 前端生产依赖 | `npm audit --omit=dev` | 0 vulnerabilities |
| Rust Host | `cargo test -- --test-threads=2` | 29 passed，2 个 Windows 凭据实机探针按默认忽略 |
| Rust 构建 | `cargo build` | 通过 |

所有测试按组件顺序执行；Vitest 最多使用 2 个 worker，Rust 最多使用 2 个测试线程，测试后未发现遗留 Vitest、Jest 或 Playwright worker。

## 模板与场景检查

- `manifest.json` 精确列出 42 个唯一场景、5 个唯一风格和 1 个系统模板，共 48 份 Markdown 资产。
- 48 份目标资产与旧 Reflex 对应源资产逐文件 SHA-256 一致。
- 清单加载覆盖相对路径、包内边界、重复 ID、文件存在性、符号链接拒绝、UTF-8、非空和大小限制。
- `content` 与 `prompt` 使用不同系统指令；场景、风格和 `zh-CN` / `en-US` 会进入 Provider 无关的渲染结果。
- `precise` 作为兼容风格可渲染，但不进入桌面端四种默认风格按钮。
- 代表性短语覆盖全部 41 个非通用场景；具体规则优先于宽泛规则，未匹配文本以低置信度回退 `general`。
- Runtime 端到端夹具确认手动 `code_review`、`prompt`、`precise` 和 `en-US` 均传入模板渲染，并把生成的 `messages` 交给 Provider。

## 桌面检查

- 调整页场景目录与内置 manifest 的 42 个 ID 顺序一致且无重复。
- 默认请求使用 `scene=null` 和 `scene_policy=auto`。
- 选择具体场景会同步切换为 `scene_policy=manual`；未知或空值安全回退自动识别。
- 持久语言只以 `zh-CN` 或 `en-US` 非敏感元数据传入请求。
- 680×480 与 760×540 下场景选择可用，页面无横向或纵向整体溢出；较小窗口由调整区内部滚动承载长目录。
- 用户界面未出现 Mock、debug、test、TODO、生成器、验收、Tauri、Runtime、Sidecar、内部目录或阶段标签。

## 安全与边界检查

- `import reflex_core` 不导入 PyQt、PySide、sqlite3、pyperclip、torch、sentence-transformers 或 huggingface-hub。
- Core 不读取桌面配置、系统凭据、剪贴板或网络；Runtime 只从固定内置路径装载模板包。
- Provider 不选择模式、风格、场景或语言，只消费 Core 生成的消息。
- 当前分支提交与工作区差异未发现生产凭据、Authorization 值或完整用户输入。
- `resources\` 基线保持 27 个文件，聚合 SHA-256 为 `3BAF82F50AA911BBC68DE1851741BD5B14AF06D3D1E6F5B994D90E761A5B236D`，且不在 Git 暂存或提交列表中。

## 回退与恢复

- 模板包损坏或发布路径缺失：使用 Core 通用回退 resolver，继续生成并记录不含正文的安全诊断。
- 场景规则回归：回退 L0 规则提交，保留 `general` 回退和手动场景能力。
- Runtime 路径异常：回退 Runtime 模板包接线，Core、manifest 和资产可独立保留。
- 桌面场景选择异常：回退 Tauri 场景目录切片，不影响 Core 和 Runtime 的模板能力。
