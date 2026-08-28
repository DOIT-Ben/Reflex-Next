# Reflex Next 架构审计

审计日期：2026-08-29  
审计范围：Core、Runtime、Python 插件、HTTP Host、Tauri Host、前端、Cloud、CI 与发布物料。

## 总结

当前项目评级为**黄灯**：宏观分层合理，Core 独立性较强，但宿主与编排层已经出现局部低内聚、重复事实来源和发布门禁断点。

这不是全局失控的代码库。Core 无 UI/Tauri/SQLite/网络依赖，插件边界和安全能力仍然清楚；问题集中在“变化一个功能需要触及多少层”和“同一事实需要维护多少份”。

## 本轮治理落地

- 建立 `tools/project-registry.json`，让 Python 项目覆盖、依赖审计、版本一致性和 SBOM 由同一份机器可读注册表驱动。
- Runtime 正式声明 `reflex-core` 依赖，并将旧的文本流 Provider 兼容转换收敛到 Core 的单一事件边界。
- HTTP Host 改为先建立事件订阅再发送命令；默认关闭开发 Mock，非 loopback 监听必须配置 Token。
- HTTP Host 对未完成流的 request ID 增加终态前 tombstone，重复请求返回 409；MiniMax 事件元数据改为记录实际请求模型。
- Cloud 输出额度结算改为带上限条件的数据库更新，避免并发结算越过每日上限。
- 默认 CI 增加 push/PR 触发，默认执行 Core/Runtime/插件/Cloud、Rust、前端和 Windows 生命周期工具契约；手动 `run_heavy` 入口追加受控短浸泡 smoke、依赖实审与 SBOM。正式 Windows 安装/升级/卸载、72 小时浸泡和签名发布仍需独立发布门禁实跑；架构、注册表和发布清单均有契约测试。
- Runtime Sidecar、Cloud 验证工具的项目路径，以及版本、依赖审计、SBOM、RC 工具现在共同使用 `tools/project_registry.ps1` 的基础校验；SBOM 组件与 Rust/Node 锁文件也由注册表统一生成。
- 发布候选验证器改为独立生成固定文件白名单，并强制 SBOM 组件集合、文件映射和根组件完整唯一。

本轮验证以本地包级测试和门禁契约为主；Windows 安装/升级/卸载、真实 PostgreSQL、Rust/Python Host 完全等价性仍属于发布门禁，不因静态检查通过而提前关闭。

## 实际架构判断

| 层 | 当前判断 | 主要证据 | 治理结论 |
| --- | --- | --- | --- |
| Core | 独立性强 | `packages/reflex-core` 无运行时 UI、Tauri、SQLite、网络依赖 | 保持最小边界，增加导入门禁 |
| Runtime | 合理但过度集中 | `RuntimeContext` 同时编排 Provider、插件、历史、诊断和调度 | 拆服务，不重写协议 |
| Plugin | 物理独立，逻辑半开放 | entry point 与固定能力 ID/白名单并存 | 分离发现、descriptor 和信任策略 |
| Tauri Host | 宿主偏厚 | `commands.rs`、`sidecar.rs` 承担大量生命周期和策略 | 保留 Host 能力，迁出业务编排 |
| HTTP Host | 适配层边界已收紧，仍与 Rust Host 重复实现 | 订阅顺序、终态保留、重复 request_id 和监听鉴权已有门禁 | 继续做 Rust/Python Host 等价性验证 |
| 前端 | 组件化与巨型协调并存 | `App.svelte` 集中管理多领域异步流程 | 按领域拆 controller/store |
| Cloud | 能独立部署，但服务内聚性不足 | `service.py` 混合额度、反馈、质量发布和清理 | 拆领域服务，保留事务边界 |
| 发布治理 | 黄灯偏红 | CI 已具备 push/PR 触发，但分支保护强制关系未核验；插件和 SBOM 清单曾有遗漏 | 由注册表生成清单并强化 PR 门禁 |

## 风险状态

### 本轮已验证的 P1 风险修复

1. Runtime 已声明 `reflex-core` 正式依赖，并通过独立临时虚拟环境安装/导入。
2. HTTP Host 已统一为“先订阅、后发送”，且终态事件在队列满时不可丢失。
3. HTTP Host 默认关闭开发 Runtime；非 loopback 监听无 Token 会拒绝启动。
4. `provider-openai-responses` 已进入统一注册表、版本、依赖和 SBOM 门禁。
5. Cloud 输出按块原子结算；超额块不下发，跨独立服务实例测试保持每日上限。

### 仍开放的 P1：发布边界

1. 默认 CI 已加入 push/PR 触发并与受控重型 smoke 分层，但当前工作区尚无新的远端全量运行证据；正式 Windows 生命周期、升级、72 小时浸泡和签名发布仍需独立发布门禁实跑。
2. Cloud 输出额度跨实例并发已用 SQLite 独立连接回归；质量发布/回滚已有 2026-07-15 PostgreSQL 历史证据，但本轮未重跑；输出额度结算的 PostgreSQL 多实例门禁仍需复验。

### P2：结构性维护债务

- `App.svelte`、`commands.rs`、`sidecar.rs`、`RuntimeContext` 和 Cloud `service.py` 低内聚。
- Rust 与 Python Host 各自维护 Sidecar 生命周期和路由实现。
- Plugin descriptor 和 Provider 目录仍存在重复或兼容性真值；Tauri 运行时以 Runtime 目录为权威，浏览器/Demo fallback 仅是版本化降级快照；Provider 文本流兼容已收口到 Core 单一事件边界。
- self-hosted CI 已收敛为手动补充稳定子集，Workflow 契约目前仍以静态约束为主，不能替代远端分支保护或完整语义验证。
- 共享 UI 组件存在“文件已创建但生产接入和行为门禁不足”的风险。
- 大型 CSS 与大型测试文件增加修改影响范围。

### P3：文档与资产债务

- 架构文档和当前功能范围存在时间与状态漂移。
- `workbench` soak JSON、根目录归档包的“正式证据/本地产物/历史资产”身份需要明确。
- Core 旧 preview Sidecar 与 Runtime Sidecar 命名相近。
- 发布证据和历史归档容易被误读；协议常量重复风险已由唯一性契约消除。
- HTTP Host 的 request ID tombstone 目前按数量上限淘汰，时间过期策略仍待补齐。

## 不应采取的动作

- 不因文件行数多就删除安全、恢复、取消、诊断和历史加密逻辑。
- 不一次性改成新的前端框架、插件框架或根级 Python workspace。
- 不删除 `resources`、`.env*`、数据库、用户数据、soak 证据或来源不明归档。

## 验收标准

- Core 可在干净环境独立安装，且导入边界门禁通过。
- Runtime、插件、Provider、产品版本和 SBOM 均由统一注册表覆盖。
- HTTP Host 先订阅后发送命令；生产默认关闭开发 Mock；非 loopback 必须鉴权。
- Rust/Python Host 的事件、取消、超时和错误契约一致。
- P1 回归测试进入提交门禁；Windows 生命周期、升级、签名和回滚作为发布门禁保留。
