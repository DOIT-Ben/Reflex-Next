# Stage B Template Pack and 42 Scenes Implementation Plan

日期：2026-07-11
目标版本：`v0.3.0-b`

## Goal

在不修改当前仓库未跟踪 `resources\` 的前提下，将旧 Reflex 的 42 个场景、5 个风格和 1 个系统模板迁为可校验的内置模板包，并让 Core、Runtime 与 Tauri 手动场景选择共同消费同一行为契约。

## Scope

包含：

- `TemplatePack` 协议、版本化 manifest、路径与内容校验；
- 42 个内容场景、4 个主风格、`precise` 兼容风格和系统基础模板；
- content/prompt 双模式、场景、风格和 `zh-CN`/`en-US` 输出语言渲染；
- 模板包缺失、损坏、未知场景或未知风格时的通用回退；
- L0 规则识别扩展到 42 个场景 ID；
- Runtime 默认加载内置模板包；
- Tauri 调整页展示 42 个场景，选择具体场景时切换为手动策略；
- 阶段验证、可见层审计、独立提交和推送。

不包含：

- 第三方模板包安装和任意用户目录扫描；
- 模板在线下载、热更新或编辑器；
- L1 语义模型；
- 中英文完整 UI，本阶段只把配置语言安全传给模板渲染；
- 真实 Provider 付费调用。

## Architecture Review

- Core 定义模板包协议、文件包校验和 Provider 无关的 messages 渲染，不知道 Tauri、HTTP 或系统凭据。
- `template-packs\builtin` 只保存 manifest 与 Markdown 数据资产，不承载 Runtime 或 Provider 逻辑。
- Runtime 只从固定的内置位置加载模板包；加载失败得到安全回退 resolver，不扫描任意目录。
- Provider 继续只消费 Core 生成的 `messages`，不选择场景、风格或模式。
- Tauri 只发送场景 ID、策略和语言，不读取 Markdown 资产。

最高风险：开发态和发布态模板路径不同。阶段 B 使用显式固定开发路径并保证缺失时可回退；阶段 G 将自包含模板资源位置接入同一 resolver 工厂。

## Ordered Tasks

### Task 1: Freeze Manifest and Asset Contract

Files:

- Create `packages\reflex-core\tests\test_template_pack.py`
- Create `template-packs\builtin\manifest.json`
- Create 48 listed Markdown assets under `template-packs\builtin`

Checks:

- manifest lists exactly 42 unique scenes, 5 unique styles and 1 system asset;
- every listed path is relative, inside the pack, UTF-8, non-empty and unique;
- committed asset IDs match the approved design and old scene registry;
- `resources\` is neither read as the new pack nor modified.

### Task 2: Implement Template Pack Validation

Files:

- Create `packages\reflex-core\src\reflex_core\template\pack.py`
- Modify `packages\reflex-core\src\reflex_core\interfaces.py`
- Modify `packages\reflex-core\src\reflex_core\template\__init__.py`
- Modify `packages\reflex-core\src\reflex_core\__init__.py`

Checks:

- malformed schema, duplicate IDs, traversal paths, oversized files, invalid UTF-8 and missing assets fail with one safe `TemplatePackError`;
- loader has no optional or desktop dependencies;
- `import reflex_core` still avoids prohibited modules.

### Task 3: Implement Provider-Neutral Rendering and Fallback

Files:

- Modify `packages\reflex-core\src\reflex_core\template\resolver.py`
- Modify `packages\reflex-core\src\reflex_core\models.py`
- Extend `packages\reflex-core\tests\test_template_pack.py`
- Modify `packages\reflex-core\tests\test_models.py`

Checks:

- content and prompt modes produce different system messages;
- scene and style assets change the rendered request;
- language is whitelisted to `zh-CN`/`en-US`;
- `precise` remains an accepted compatibility style without becoming a fifth default UI button;
- missing or invalid pack renders a safe general request instead of blocking optimization.

### Task 4: Expand L0 Scene Recognition

Files:

- Modify `packages\reflex-core\src\reflex_core\scene\detectors.py`
- Modify `packages\reflex-core\tests\test_scene_detector.py`

Checks:

- one representative phrase maps to each non-general scene ID;
- specific rules win over broad rules;
- unmatched text still returns `general` with low confidence;
- no optional model dependency is imported.

### Task 5: Wire Runtime to the Builtin Pack

Files:

- Modify `packages\reflex-runtime\src\reflex_runtime\context.py`
- Modify `packages\reflex-runtime\tests\fixtures\reflex_provider_minimax.py`
- Modify `packages\reflex-runtime\tests\test_cli.py`

Checks:

- Sidecar sends `messages` rendered from the selected template to the Provider fixture;
- manual scene survives the complete command path;
- missing pack still yields a request through the Core fallback;
- stdout/stderr leakage assertions remain green.

### Task 6: Expose All Scenes in the Tauri Flow

Files:

- Modify `apps\tauri-host\src\domain\reflexSession.ts`
- Modify `apps\tauri-host\src\domain\reflexSession.test.ts`
- Modify `apps\tauri-host\src\domain\hostState.ts`
- Modify `apps\tauri-host\src\domain\hostState.test.ts`
- Modify `apps\tauri-host\src\App.svelte`

Checks:

- scene catalog contains 42 unique stable IDs;
- “自动识别” sends `scene=null` with `scene_policy=auto`;
- choosing a concrete scene sends that ID with `scene_policy=manual`;
- persisted language is included only as non-sensitive request metadata;
- the 680×480 and 760×540 layouts remain usable with the native select.

### Task 7: Verification, Documentation and Push

Files:

- Update `template-packs\builtin\README.md`
- Create `docs\verification\stage-b-verification.md`
- Update `README.md` and `workbench\readme.md`

Checks:

```powershell
cd packages\reflex-core
uv run --python 3.12 --with pytest pytest -q

cd ..\reflex-runtime
uv run --python 3.12 --with pytest --with httpx pytest -q

cd ..\..\plugins\provider-minimax
uv run --python 3.12 --with pytest --with httpx pytest -q

cd ..\..\apps\tauri-host
$env:VITEST_MAX_WORKERS='2'
npm test -- --maxWorkers=2
npm run build

cd src-tauri
cargo test -- --test-threads=2
cargo build
```

Also run manifest inventory, Core prohibited-import, production credential, user-visible internal-text, `git diff --check`, staged-path and outgoing-commit scans. Browser and real Tauri screenshots must cover Ready, Adjust and Settings at 680×480 and 760×540; screenshots are review evidence only and are not committed.

## Commit Plan

1. `docs: 制定阶段 B 模板与场景计划 | v0.3.0-b0 | YYYY-MM-DD HH:MM`
2. `feat: 实现内置模板包与 42 场景渲染 | v0.3.0-b1 | YYYY-MM-DD HH:MM`
3. `feat: 接入 Runtime 模板渲染主链 | v0.3.0-b2 | YYYY-MM-DD HH:MM`
4. `feat: 对齐 42 场景桌面选择 | v0.3.0-b3 | YYYY-MM-DD HH:MM`
5. `docs: 记录阶段 B 验证与回退 | v0.3.0-b4 | YYYY-MM-DD HH:MM`

每次暂存前确认 `resources\` 不在路径列表；阶段完成后推送 `codex/full-feature-parity`。

## Recovery

- 模板包损坏：禁用文件包并使用 Core 通用回退，不阻塞生成。
- 场景规则回归：回退 L0 规则提交，保留 `general` 回退。
- Runtime 路径错误：回退 Runtime 接线，Core 与资产提交可独立保留。
- UI 布局回归：回退场景选择 UI，不影响 Core 和 Runtime 模板能力。
