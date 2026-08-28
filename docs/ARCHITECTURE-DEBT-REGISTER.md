# Reflex Next 架构债务登记

本文件是架构与文件债务的唯一跟踪清单。`status` 只允许使用：`open`、`in_progress`、`verified`、`accepted`。

| ID | 优先级 | 状态 | 负责人 | 影响 | 问题 | 证据 | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ARC-P1-001 | P1 | verified | Runtime | 独立安装可能失败 | Runtime 已声明 `reflex-core` 正式依赖 | `packages/reflex-runtime/pyproject.toml`、`packages/reflex-runtime/uv.lock` | 干净环境独立安装与导入通过；本轮已验证 |
| ARC-P1-002 | P1 | verified | HTTP Host | 快速响应或重连可能丢事件 | HTTP Host 先建立订阅并保护未完成 request ID 生命周期 | `packages/reflex-http-host/src/reflex_http_host/app.py`、`gateway.py` | 快速 ping/provider/optimize 事件不丢失；断开后的 ID 在 Runtime 终态前不可复用；本轮已验证 |
| ARC-P1-003 | P1 | verified | HTTP Host | 非安全监听可能被未授权调用 | HTTP Host 开发模式与监听鉴权默认值已收紧 | `packages/reflex-http-host/src/reflex_http_host/gateway.py`、`app.py` | 默认生产安全；非 loopback 无 Token 启动失败；本轮已验证 |
| ARC-P1-004 | P1 | verified | Release | 插件可能漏过版本与物料门禁 | Provider 插件由统一注册表覆盖验证、版本和 SBOM | `tools/project-registry.json` 与工具脚本 | 注册表新增项目自动进入相关门禁；本轮已验证 |
| ARC-P1-005 | P1 | in_progress | CI/Release | 合并与发布证据仍不完整 | 默认提交 CI 尚无新的远端全量运行证据 | `.github/workflows/backend-ci.yml` | PR/push 默认门禁覆盖核心测试、插件、Cloud、Rust 与前端构建；`run_heavy` 覆盖 Windows 生命周期工具契约、短浸泡 smoke、依赖/SBOM；正式 Windows 生命周期、72 小时浸泡、签名发布和远端分支保护另行实跑核验 |
| ARC-P1-006 | P1 | in_progress | Cloud | 并发下可能额度超发 | Cloud 输出额度需完成 PostgreSQL 多实例并发复验 | `services/reflex-cloud/src/reflex_cloud/service.py`、`api.py` | 超额块不下发；独立服务实例并发不超额；输出额度结算的 PostgreSQL 多实例并发门禁通过 |
| ARC-P1-007 | P1 | verified | Release | 额外物料可能自证通过 | 发布候选验证器改为固定集合校验 | `tools/verify_release_candidate.ps1`、`tools/tests/release_candidate_contract.ps1` | 独立固定校验 3 个 artifact、6 个文档、14 个 SBOM、2 个清单；额外/缺失/改名/重复组件均拒绝；本轮已验证 |
| ARC-P2-001 | P2 | open | Runtime | 编排变化容易扩散到能力与诊断 | RuntimeContext 职责过宽 | `packages/reflex-runtime/src/reflex_runtime/context.py` | 编排、能力、诊断职责可独立测试 |
| ARC-P2-002 | P2 | open | Host | Rust/Python 行为可能分叉 | Rust/Python Host 重复实现 Sidecar 生命周期 | `sidecar.rs`、`reflex_http_host/gateway.py` | 共享协议契约与一致性测试 |
| ARC-P2-003 | P2 | open | Host/Frontend | 单领域改动影响无关功能 | Tauri commands/sidecar 与前端 App 为巨型协调器 | `commands.rs`、`sidecar.rs`、`App.svelte` | 单领域变化不再扩散到无关职责 |
| ARC-P2-004 | P2 | in_progress | Runtime/Frontend | Provider 目录可能出现不一致 | Provider/Plugin 多份事实来源 | Runtime registry、descriptor、前端 catalog、`reflex_core.provider_events` | Provider 事件兼容已单点收口；目录和 descriptor 仍需统一权威来源 |
| ARC-P2-005 | P2 | open | Frontend | 组件名义复用但行为不受门禁保护 | 共享 UI 组件接入与行为门禁不足 | `apps/tauri-host/src/components/ui` | 真实生产调用和交互测试齐全 |
| ARC-P2-006 | P2 | verified | Release | 工具清单漂移会漏验证 | Runtime Sidecar、版本、依赖审计、SBOM、RC 和 Cloud 工具统一使用注册表加载器 | `tools/project_registry.ps1`、`tools/project-registry.json`、相关工具脚本 | 共享加载器完成 schema、标识符、仓库内相对路径、唯一性和已存在路径 reparse point 校验；9 个消费者全部复用；本轮契约已验证 |
| ARC-P2-007 | P2 | open | CI | 补充检查可能被误当合并门禁 | self-hosted workflow 目前是手动稳定子集，与主 CI 覆盖口径不同 | `.github/workflows/ci-selfhosted.yml`、`backend-ci.yml` | 明确为补充性手动检查，或改为复用主验证入口并建立独立发布职责，不得被误当作合并门禁 |
| ARC-P2-008 | P2 | open | CI | 文本契约可能漏判工作流语义 | Workflow 契约主要以正则检查文本，未验证 YAML 事件矩阵和条件求值 | `tools/tests/verify_backend_contract.ps1` | 使用 YAML 解析或 actionlint 等真实语义校验，并覆盖 push/PR/`run_heavy=false/true` |
| ARC-P3-001 | P3 | in_progress | Docs | 用户会误读历史验证为当前状态 | 文档日期、产品范围和验证状态漂移 | `docs/`、`workbench/` | 本轮日期、当前 SBOM 数量和验证边界已同步；历史文档仍需持续标注 |
| ARC-P3-002 | P3 | open | QA/Release | 本地产物可能被误当正式证据 | 验证证据与本地运行产物身份不清 | `workbench/http-soak-*.json` | 迁移或保留决策有引用核查证据 |
| ARC-P3-003 | P3 | open | Core | 入口含义容易误判 | Core preview Sidecar 命名容易混淆 | `packages/reflex-core/src/reflex_core/sidecar.py` | 明确兼容/示例用途 |
| ARC-P3-004 | P3 | open | HTTP Host | tombstone 无限增长或误拒请求 | HTTP Host 未完成 request ID tombstone 的时间过期策略 | `packages/reflex-http-host/src/reflex_http_host/gateway.py` | 以可证明的时间窗口和数量上限共同治理 tombstone，并补充过期/重启语义测试 |
| ARC-P2-009 | P2 | open | Frontend/CI | 约定的命名门禁当前无法直接执行 | 前端没有 `typecheck`、`lint`、`identity:check`、`docs:check` npm scripts | `apps/tauri-host/package.json`、`tools/verify_backend.ps1` | 提供真实命令并纳入 CI，或将统一验证入口的等价检查明确文档化 |
| ARC-P3-005 | P3 | open | Frontend QA | 静态契约不能证明真实焦点回归 | 对话框焦点恢复目前主要由源码契约覆盖 | `apps/tauri-host/src/domain/frontendArchitecture.test.ts` | 在受控浏览器/Tauri 测试中覆盖键盘焦点、Esc、切换对话框和 inert 边界 |

## 本轮验证记录

以下记录针对 2026-08-29 当前工作树，命令均在仓库根目录或对应项目目录执行，退出码均为 `0`；未覆盖项仍按表中 `in_progress/open` 保留。

| 范围 | 命令/证据 | 结果 | 未覆盖风险 |
| --- | --- | --- | --- |
| Core | `packages/reflex-core`：`uv run --locked --extra dev pytest -q` | 109 passed | 未做发布环境安装包演练 |
| Runtime | `packages/reflex-runtime`：`uv run --locked --extra dev pytest -q` | 333 passed | 仍需正式长时浸泡 |
| HTTP Host | `packages/reflex-http-host`：`uv run --locked --extra dev pytest -q` | 44 passed | Rust/Python Host 完全等价性仍未证明 |
| Cloud | `services/reflex-cloud`：`uv run --locked --extra dev pytest -q` | 86 passed | PostgreSQL 多实例额度并发仍未复验 |
| Provider | `plugins/provider-minimax`：`uv run --locked --extra dev pytest -q` | 32 passed | 其它 Provider 的真实外部服务回归不在本轮范围 |
| Tauri Host | `apps/tauri-host/src-tauri`：`cargo test --locked --lib -- --test-threads=2` | 197 passed，3 ignored | Credential Manager 实机、Windows 安装生命周期和签名未覆盖 |
| Frontend | `apps/tauri-host`：`npm test -- --run`；`npm run build`；Playwright 预览窗口 760×540、680×480、390×844 | 222 passed；构建转换 267 modules；预览布局无横向溢出、窄窗可滚动；设置折叠、焦点陷阱与深色主题复验通过 | 真实 Windows Tauri 窗口与安装生命周期仍未覆盖；真实 DOM 焦点回归仍需补测 |
| Governance | `tools/tests/project_registry_contract.ps1`、`check_version_consistency_contract.ps1`、`audit_dependencies_contract.ps1`、`generate_release_sbom_contract.ps1`、`release_candidate_contract.ps1`、`verify_backend_contract.ps1` | 全部 passed | CI 远端运行、YAML 条件求值和分支保护仍未由本地契约证明 |
| Runtime soak | `tools/soak_backend.py --iterations 100 --batch-size 4 --cancel-every 2`；`workbench/runtime-soak-smoke-20260829.json` | 100 iterations；50 completed、50 cancelled；650 protocol events；final observation 0；graceful shutdown；passed | 仅为本机短浸泡，未替代正式 72 小时/10,000 次发布门禁 |

## 维护规则

- 每个条目必须包含源码或配置证据，不能只写主观评价。
- 结构拆分必须先有行为测试，再移动职责。
- `resources`、数据库、凭据、用户数据和来源不明归档保持保护状态。
- 完成条目必须记录命令、退出码、测试范围和未覆盖风险。
