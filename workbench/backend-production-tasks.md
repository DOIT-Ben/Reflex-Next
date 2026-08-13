# Reflex Next 后端生产化任务账本

更新时间：2026-07-15
长期路线图：`docs/BACKEND-PRODUCTION-ROADMAP.md`

## 状态说明

- `待办`：尚未开始；
- `进行中`：已分配且正在执行；
- `待集成`：子任务完成，等待主线程审查；
- `待验证`：实现已集成，等待完整门禁；
- `完成`：实现、验证、文档和提交均完成；
- `阻塞`：存在需要用户或外部条件处理的真实阻塞。

## 当前阶段：阶段 4 发布候选验证中，阶段 3 长期运行建设中

| ID | 任务 | 状态 | 依赖 | 验证 |
|---|---|---|---|---|
| P0-001 | 建立长期路线图和任务账本 | 完成 | 无 | 文档审查、路径检查 |
| P0-002 | 安全专项生产化审查 | 完成 | 无 | P0-P3 报告、上线门禁 |
| P0-003 | Provider/Runtime 可靠性审查 | 完成 | 无 | 任务图、协议风险、上线门禁 |
| P0-004 | 性能/资源/可观测性审查 | 完成 | 无 | SLO、基准和浸泡方案 |
| P0-005 | 测试/CI/发布工程审查 | 完成 | 无 | 统一入口、CI 和发布门禁 |
| P0-006 | 建立统一后端验证脚本 | 完成 | P0-005 | 单命令运行 10 个 Python 包、Rust 和前端契约 |
| P0-007 | 建立 Windows 后端 CI | 完成 | P0-006 | GitHub Windows Run `29255203782` 全门禁通过 |
| P0-008 | 建立版本一致性检查 | 完成 | P0-005 | 日常元数据、锁文件和发布标签模式契约通过 |
| P0-009 | 建立发布前敏感信息扫描 | 完成 | P0-002 | 扫描器契约、受控夹具和当前跟踪文件实扫通过，并已接入统一 CI |
| P0-010 | 冻结第一阶段 Provider 目录协议 | 完成 | P0-003 | 严格目录 schema、可信发布状态和会话配置语义测试通过 |
| P0-011 | 隔离 Release 与开发 Runtime，生产拒绝 Mock | 完成 | P0-002 | bundled 移除开发变量，Rust 133 项通过 |
| P0-012 | 封锁当前 WebView 外部导航 | 完成 | P0-002 | 主/历史窗口固定入口，外链与危险 scheme 负向测试通过 |
| P0-013 | 冻结资源上限和错误码 | 完成 | P0-003、P0-004 | 工程评审通过 |

## 阶段 1：Provider 与 Runtime 生产可靠性

| ID | 任务 | 状态 | 依赖 | 验证 |
|---|---|---|---|---|
| P1-001 | Runtime 输出 Provider/模型可信目录 | 完成 | P0-010 | `provider_catalog` 契约、插件隔离和脱敏测试通过 |
| P1-002 | Rust Host 暴露只读 Provider 目录命令 | 完成 | P1-001 | 主窗口只读命令、严格解析、有界 stdout/stderr 和重启测试通过 |
| P1-003 | 前端 Domain Bridge 消费动态目录 | 完成 | P1-002 | Runtime 请求 ID 关联、严格目录解析、错误脱敏、设置页接入；前端 163 项与 Rust 191 项通过，见 `docs/verification/provider-catalog-frontend.md` |
| P1-004 | 冻结重试、超时、取消和错误分类 | 完成 | P0-003 | MiniMax/OpenAI-compatible 负向夹具、主动取消和安全错误测试通过 |
| P1-005 | 增强 SSE/JSON 断流与超大响应防护 | 完成 | P1-004 | 两类 Provider 均完成 2 MiB/50,000 上限、截断和非法 UTF-8 测试 |
| P1-006 | Sidecar 崩溃和并发恢复验证 | 完成 | P1-004 | 唯一安全终态、路由清理、进程终止和下一请求重启测试通过 |
| P1-007 | 建立脱敏真实 Provider 冒烟工具 | 完成 | P1-004 | Runtime NDJSON、Credential Manager、8 MiB 输出上限、500 ms 迟到事件观察与 8 项契约通过 |
| P1-008 | 完成真实流式与取消实机门禁 | 完成 | P1-007、新凭据 | MiniMax 目录、流式成功和取消实机通过，见 `docs/verification/provider-smoke-2026-07-15.md` |
| P1-009 | 正确分类 `OperationCancelled` | 完成 | P0-013 | Core 取消终态测试通过 |
| P1-010 | 主动中断 Provider 阻塞读取 | 完成 | P1-009 | Token 回调主动关闭 client/response，阻塞读取和退避取消测试通过 |
| P1-011 | 建立 Runtime 并发和等待队列上限 | 完成 | P0-013 | 固定 4 worker/32 真等待、FIFO/取消/关闭回收、`runtime_busy` 通过 |
| P1-012 | 建立输出、分片和总时限上限 | 完成 | P0-013 | 2 MiB/50,000、120s watchdog、终态线性化和阻塞读取硬中断通过 |
| P1-013 | 重做请求 ID 有界生命周期 | 完成 | P1-011 | 100,000 会话防重放、零活动安全轮转、旧 reader 退出和并发原子测试通过 |
| P1-014 | OpenAI-compatible 移除 MiniMax 私有依赖 | 完成 | P1-004 | 独立锁文件与 Runtime 聚合锁更新，插件 38 项通过 |

## 阶段 2：安全与本地数据加固

| ID | 任务 | 状态 | 依赖 | 验证 |
|---|---|---|---|---|
| P2-001 | Credential Manager 保存/读取/删除实机测试 | 完成 | P0-002 | 3 项 Windows 实机测试通过，隔离探针已清理 |
| P2-002 | Tauri capability 与私有命令最小权限复核 | 完成 | P0-002 | capability JSON 与 Rust 矩阵精确一致，私有命令禁入 |
| P2-003 | 历史损坏、恢复和轮换中断演练 | 完成 | P0-002 | 7 项灾难恢复夹具、索引/AEAD/记录一致性和幂等恢复通过 |
| P2-004 | Markdown/CSV/路径/协议攻击性夹具 | 完成 | P0-002 | Markdown、CSV、WebView、历史路径、自定义 CA 路径与私有字段负向夹具通过 |
| P2-005 | Python/Rust/npm 依赖漏洞和许可证门禁 | 完成 | P0-007 | 全 lockfile 漏洞、许可证 allowlist、稳定退出码和真实审计通过 |
| P2-006 | 构建产物敏感信息扫描和 SBOM | 完成 | P0-009 | `cf45530` 干净工作树的前端构建、敏感扫描、12 组件 SBOM 和哈希复核通过；本地证据为合并门禁，远端 workflow 仅手动触发 |

## 阶段 2.5：云端反馈闭环与质量发布

| ID | 任务 | 状态 | 依赖 | 验证 |
|---|---|---|---|---|
| P2-007 | 云端反馈、授权和删除边界 | 完成 | P2-003、P2-004 | 反馈附件二次授权校验、敏感信息脱敏、删除级联和用户可见错误测试通过 |
| P2-008 | 免费额度、全局预算和运营错误边界 | 完成 | P2-007 | 安装/IP/全局预算事务、预占结算、预算巡检和 Cloud 全量回归通过 |
| P2-009 | 质量发布来源、发布、回滚和曝光归因 | 完成 | P2-007、P2-008 | 来源状态校验、公开元数据隔离、指导注入、发布锁、回滚、幂等曝光和隐私删除测试通过 |
| P2-010 | 客户端质量透明度与管理后台闭环 | 完成 | P2-009 | Rust 命令权限、前端 Bridge、设置页授权开关、管理草稿/发布/回滚操作和运行态验证通过 |
| P2-011 | PostgreSQL 多实例质量发布并发验证 | 完成 | P2-009 | 独立 PostgreSQL 16 测试库中发布/回滚并发、部分唯一索引、唯一终态和 schema 清理通过 |

## 阶段 3：性能、资源与可观测性

| ID | 任务 | 状态 | 依赖 | 验证 |
|---|---|---|---|---|
| P3-001 | 建立冷启动与首状态基准 | 完成 | P0-006 | 本地 Mock P50/P95/P99、失败计数、环境元数据和 9 项契约通过 |
| P3-002 | 建立 10,000 次请求/取消浸泡 | 进行中 | P1-006 | 工具、100 次 CI、10,000 次本机门禁通过；上一轮 72 小时门禁因 10ms 夹具竞态提前失败，100ms 修复后 2,000 次复验通过，待重新运行正式门禁 |
| P3-003 | 建立插件和历史资源浸泡 | 完成 | P2-003 | 三轮 1,000 次、Private Bytes/句柄/线程/SQLite 连接预算通过 |
| P3-004 | 审查请求 ID、线程、队列和缓冲上限 | 完成 | P0-004 | Runtime/插件/Host 硬上限、唯一终态、会话轮转和连接归零通过 |
| P3-005 | 建立轮转脱敏诊断 | 完成 | P0-004、P0-002 | Runtime/Host 请求与生命周期、配置恢复、历史修复/恢复终态、轮转上限和隐私负向测试通过 |
| P3-006 | 建立诊断包导出 | 完成 | P3-005 | 固定来源 ZIP、严格再白名单化、二次扫描、原子提交、取消/崩溃清理和最小权限通过 |
| P3-007 | 语义模型 single-flight 与生命周期互斥 | 完成 | P0-004 | 4 路 single-flight、管理互斥、缓存代际失效和零等待 L0 回退通过 |
| P3-008 | 建立 1 万条历史性能和保留策略 | 完成 | P2-003 | 10,000 条标准数据保存、分页、搜索、导出、轮换和磁盘预算通过；保留、恢复与搜索截止有契约 |

## 阶段 4：安装、升级与发布候选

| ID | 任务 | 状态 | 依赖 | 验证 |
|---|---|---|---|---|
| P4-001 | 统一版本号和构建元数据 | 完成 | P0-008 | `VERSION`、产品清单、锁文件、界面和云服务元数据一致 |
| P4-002 | 干净 Windows 10/11 构建验证 | 待验证 | P2、P3 完成 | Windows 11 已通过，Windows 10 待验证；见 `docs/verification/release-alpha8-windows-lifecycle.md` |
| P4-003 | 安装、覆盖安装、卸载和重装生命周期 | 待验证 | P4-002 | Windows 11 已通过，Windows 10 待验证；见 `docs/verification/release-alpha8-windows-lifecycle.md` |
| P4-004 | 配置和历史升级兼容 | 进行中 | P4-002 | 配置 11 项、History 迁移回归、v0 Host 启动、beta.11 到 alpha.8 安装目录覆盖，以及旧 Runtime 实际历史库到当前 Runtime 的读写/备份迁移通过；官方旧版包/真实旧数据 Host 全链路待验证 |
| P4-005 | 签名、更新与回滚方案 | 进行中 | 用户采购决策 | `docs/RELEASE-SIGNING.md` 已冻结签名、时间戳、更新和回滚流程；实际证书、签名实跑和回滚演练待完成 |
| P4-006 | 发布清单、校验和、SBOM 和恢复手册 | 进行中 | P4-003、P4-005 | 当前门禁要求 schema 2、24 文件哈希、12 项 SBOM 和 6 份用户文档；正式签名、标签、回滚包和最终 RC 审计待完成 |

## 阶段 5：受控试用与正式发布

| ID | 任务 | 状态 | 依赖 | 验证 |
|---|---|---|---|---|
| P5-001 | 受控试用和问题分级 | 待办 | RC1 | 无未处理 P0/P1 |
| P5-002 | 全量回归、冒烟、浸泡和安装复验 | 待办 | P5-001 | 四类证据齐全 |
| P5-003 | 隐私、依赖、支持范围和故障文档 | 完成 | P5-001 | `PRIVACY.md`、`THIRD-PARTY-NOTICES.md`、`SUPPORT.md`、`TROUBLESHOOTING.md`；链接、敏感扫描、用户可见层和候选包来源绑定通过 |
| P5-004 | 生成签名安装包和回滚包 | 待办 | P5-002 | 包校验通过 |
| P5-005 | 创建并验证 `v1.0.0` | 待办 | 全部门禁 | 标签、发布物、校验和一致 |

## 当前验证基线

- Python：10 个包全部通过，本轮 Reflex Cloud 48 项通过；
- Rust/Tauri Host：194 项通过，3 项 Windows Credential Manager 实机测试默认忽略且已单独实跑通过；
- 生产工具：Provider 冒烟 8 项加 2 个子用例、性能基准 9 项、History 基准 38 项、插件/历史资源工具 40 项通过；
- Runtime 浸泡：工具契约 14 项、CI 100 次短门禁通过；本机 10,000 次中 5,000 完成、5,000 取消、65,002 个协议事件、迟到事件 0、安全退出；
- 72 小时 Runtime 门禁最近一轮已提前结束：报告 `workbench\runtime-soak-72h-alpha8-20260715-045742.json` 记录 824 次（完成 412、取消 412），因 `completed_instead_of_cancelled` 失败，未达到 10,000 次/72 小时门槛；P3-002 继续保持进行中；
- 取消浸泡夹具已将首 chunk 后的处理窗口从 10ms 调整为 100ms，严格终态断言不变；修复后 2,000 次中完成/取消各 1,000 次、13,000 个协议事件、迟到事件 0，并安全退出；
- 插件/历史浸泡：三轮各 1,000 次均通过，Private Bytes 最大增量 454,656 B，三轮句柄/线程增量均为 0，SQLite 最终活动连接 0、峰值 1；统一门禁保留 100 次短烟测；
- TypeScript Domain Bridge 与前端架构契约：26 个文件、168 项测试通过，最大 2 workers；
- Provider/模型目录：Tauri Host 先订阅 `reflex://provider-catalog`，再调用 `runtime_list_providers`，按 Rust 返回的请求 ID关联结果；设置页和调整页使用 Runtime 目录，目录异常只显示固定用户提示并保留浏览器安全回退；
- 前端生产构建：本轮 Vite 构建通过，242 个模块，主包约 270.39 kB、gzip 约 84.29 kB；
- `cf45530` 本机供应链复验：干净安装 0 个 npm 漏洞，26 个测试文件、168 项测试通过（最多 2 workers），Vite 242 个模块构建和 `dist` 敏感扫描通过；12 个 CycloneDX 1.5 BOM、源锁文件和清单哈希独立复核错误为 0；
- `cf45530` 远端历史状态：Run `29422634887` 因 GitHub Billing 在 Runner 分配前失败，执行步骤和 Artifact 均为 0；该失败不是代码门禁失败，也不再作为合并门禁；
- 前端视觉与交互：680x480、760x540、920x720 无页面溢出或控件裁切，Demo Core 生成、命令面板、设置导航和悬浮反馈实跑通过；
- 发布前敏感扫描：契约测试与当前受版本控制文件实扫通过；
- 依赖门禁：10 个 Python 环境（含 Reflex Cloud）、RustSec、Rust/npm 许可证和 npm 全 lockfile 真实审计通过；`cryptography` 已升至 `48.0.1`；
- RustSec 临时例外：`quick-xml 0.39.4` 两项公告仅存在于非 Windows Wayland 依赖图，例外在 2026-10-01 到期，进入 Windows 依赖图会立即失败；
- Windows CI：Run `29377826885` 完成安全扫描、干净依赖安装、全量测试、100 次 Runtime 浸泡、生产构建、构建物扫描和 SBOM 上传，结论为 `success`；
- 版本一致性检查：14 个产品版本来源统一为 `0.7.0-alpha.8`；Python/uv 的 PEP 440 规范化形式 `0.7.0a8` 经过等价校验；
- alpha.8 干净 Windows 构建：从提交 `8310736` 的干净副本完成冻结依赖、Runtime 单文件、Rust release 和 NSIS 构建；该历史证据包含 11 项 SBOM，不能替代当前含 Cloud 的 12 项 SBOM 门禁；
- alpha.8 隔离生命周期：首次安装、Sidecar ping/shutdown、同版本覆盖安装、卸载、重装和最终清理通过；详见 `docs/verification/release-alpha8-windows-lifecycle.md`；
- 生命周期工具：`tools\verify_windows_lifecycle.ps1` 已固化隔离安装、覆盖、卸载、重装、Sidecar 协议和 Host 启动检查，契约测试与 alpha.8 实跑均通过；
- 真实 Provider：MiniMax 目录、流式成功和定时取消实机通过，结果只保留分类和时延；详见 `docs/verification/provider-smoke-2026-07-15.md`；
- 配置与历史升级契约：Rust 配置迁移 11 项、History 旧库夹具与全套回归、v0 Host 启动、beta.11 到 alpha.8 安装目录覆盖，以及旧 Runtime 实际生成库到当前 Runtime 的详情/列表/新写入/`migration-v1` 备份迁移通过；官方旧版包/真实旧数据 Host 全链路仍由 P4-004 继续验证；
- 发布候选物料：旧 alpha.8 审查物料包含 3 个可执行物、11 份 SBOM 和 19 个文件，已标记为历史证据；当前 `new_release_candidate.ps1` / `verify_release_candidate.ps1` 使用 schema 2，固定要求 12 份 SBOM、6 份用户文档和 24 个文件，旧物料不能继续作为当前 RC；
- 本轮供应链增量门禁（2026-07-15）：在隔离工作树执行 `verify_backend.ps1 -SkipFrontend`，10 个 Python 项目、工具契约、真实依赖审计、Rust `192 passed, 3 ignored`、短浸泡和真实 SBOM 全部通过；真实 SBOM 为 12 个组件、13 个物料文件，锁文件和组件哈希全部一致；
- 统一验证脚本契约：步骤、锁文件、失败码、Rust/Vitest 并发上限通过；
- 当前已知测试工程缺口：根目录一次性收集全部 pytest 会因同名测试模块冲突，必须按包隔离或改用 importlib 模式；
- 当前工作区原有未跟踪内容：`resources/` 与用户提供的前端重做归档，任何任务不得修改或暂存。

## 2026-07-14 第五批集成记录

- 建立脱敏 Provider 冒烟工具，真实模式只读取 Windows Credential Manager，不接受命令行明文密钥；
- 冒烟工具对 stdout 单行设置 8 MiB 上限，取消后持续观察 500 ms，迟到 `chunk/done` 统一失败；
- 建立冷启动、首状态、首包、总耗时和取消 P50/P95/P99 本地 Mock 基准；当前 10 样本烟测冷启动 P95 为 827.091 ms，取消确认 P95 为 101.907 ms，不作为正式 RC SLO 证据；
- 建立默认禁用的轮转结构化诊断基础库，未知字段、消息正文和 URL 不落盘，损坏日志安全丢弃后恢复；
- 建立 Python/Rust/npm 漏洞和许可证 allowlist 门禁，并接入统一验证与 Windows CI；
- 真实门禁发现并修复 `cryptography 45.0.7` 的四项公告，升级到 `48.0.1` 后历史插件 130 项通过；
- `cargo-audit` 升级到支持 CVSS 4.0 的 `0.22.2`；两项仅位于 Wayland 非 Windows 图的 `quick-xml` 公告采用带到期日和目标可达性复核的临时例外；
- 将重设计稿的标题栏、导航、输入/结果双栏、状态栏和命令面板原生移植到 Svelte/Tauri 前端，明确拒绝 Next API、Prisma、ZAI SDK 和浏览器后端；
- 图标改为 `@lucide/svelte` 按文件导入，构建扫描从 3590 个模块降至 184 个；
- 本批统一验证通过：Python 644 项通过、6 项条件跳过，Rust 152 项、前端 148 项、敏感扫描、真实依赖审计、干净 npm 安装和生产构建全部通过。

## 2026-07-14 第六批供应链记录

- 建立锁文件驱动的 CycloneDX 1.5 生成器：Python 使用固定 `uv 0.11.13`，Rust 使用固定 `cargo-cyclonedx 0.5.9`，Node 使用 npm 原生 SBOM；
- 生成 9 个 Python、1 个 Rust Host 和 1 个 Node Host 组件 SBOM，汇总清单固定记录源锁文件、SBOM 文件及双方 SHA-256；
- 生成期间任何锁文件变化都会失败，非空输出目录会失败，错误格式、错误根组件、重复组件和超大 SBOM 会失败；
- 将源码敏感扫描与产物敏感扫描分离，产物模式只扫描显式目录，保持相同脱敏规则且不会重复遍历仓库；
- 统一后端门禁实际生成并验证 11 个组件 SBOM；Windows CI 额外扫描前端 `dist`，上传 30 天保留的 SBOM Artifact；
- Run `29275128988` 的全量验证、构建物扫描和 Artifact 上传均为 `success`；下载复核得到 12 个文件、11 个组件清单，格式、目标和全部 SHA-256 摘要有效。

## 2026-07-14 第七批长期运行记录

- 建立单 Runtime 进程请求/取消浸泡工具，固定最多 4 并发、4,096 事件队列、8 MiB 诊断上限和 100,000 条终态历史；
- 每个请求使用唯一 Mock 分片标记检测串线，取消后持续检查迟到 `chunk/done`，完成请求严格要求 `done -> metric`，未知事件和重复终态统一失败；
- 工具不继承 Provider 凭据，不在报告中记录请求正文、分片正文、请求 ID 或异常详情；
- 本机 10,000 次门禁在 64.672 秒内完成：5,000 正常完成、5,000 主动取消、65,002 个协议事件、队列峰值 8、最终 500 ms 观察窗口迟到事件 0，Runtime 安全退出；
- 统一验证增加 14 项工具契约和 100 次短浸泡；Run `29278465239` 全部门禁通过；
- Windows CI 增加固定 Cargo 工具二进制缓存，缓存键包含三项精确版本，命中后仍通过 Cargo 安装清单核验版本；缓存 `5712766991` 已成功写入；
- P3-002 仍需完成 72 小时、至少 10,000 次正式持续运行，因此保持“进行中”，不提前关闭。

## 2026-07-14 第八批诊断接入记录

- Runtime 请求主链记录 Provider、模型、阶段、分片数、耗时和固定错误码，错误事件与本地记录共享随机诊断 ID；
- Runtime 插件终态只记录插件 ID、操作、状态和固定错误码，不记录调用方请求 ID、输入、返回数据、历史路径或备份 ID；
- Host 独立观察 Runtime/插件安全终态，记录 Sidecar 生命周期，并对主配置失效后的备份恢复和默认回退生成固定 `config_recovery` 事件；
- Host 与 Runtime 各自使用 1 MB 单文件、3 文件、3 MB 总量上限；仅精确设置 `REFLEX_DIAGNOSTICS_ENABLED=1` 时启用，默认不创建目录、不写盘、不上传；
- 本机统一后端门禁通过：Python 9 包 660 项、Rust Host 159 项加 3 项默认忽略、Provider/性能/浸泡工具、安全扫描、依赖审计和 11 组件 SBOM 全部通过；
- 前端开发服务器占用 Rolldown 原生文件时，全量脚本的 `npm install` 会被 Windows 拒绝；本轮未终止用户运行中的前端，改用 `-SkipFrontend` 完成后端闭环，前端 148 项与生产构建继续采用上一成功 CI 证据；
- Run `29283308542` 在干净 Windows Runner 完成全量门禁并返回 `success`，P3-005 关闭；P3-006 继续负责用户显式诊断包导出与导出前二次敏感扫描。

## 2026-07-14 第九批诊断包导出记录

- Host 固定读取应用数据目录下 Host/Runtime 各 3 个诊断文件，不递归枚举，导出目标只来自主窗口原生保存对话框；
- JSONL 在打包前重新执行严格 schema 校验并删除 Runtime 请求 ID，未知字段、非 UTF-8、不完整行、单文件/总量/单行超限统一拒绝；
- 标准库二次扫描覆盖常见 Provider Key、私钥、Bearer/JWT、GitHub、Slack、AWS、Google、Stripe、凭据赋值/URL和高熵令牌，同时放行诊断 ID、UUID、版本、哈希和脱敏占位符；
- ZIP 使用固定 Stored 条目和无设备信息的 manifest，最终上限 8 MB；相对/UNC/设备路径、父目录跳转、符号链接和 Windows reparse point 均拒绝；
- 同目录私有临时文件在 flush/sync 后原子提交，提交前恢复普通 Windows 文件属性；取消、失败及异常退出 journal 清理均保护旧目标；
- `diagnostic_bundle_export/cancel` 只授予主窗口，前端领域桥只发送空参数且只接受 `completed/cancelled`，任意底层异常转换为固定安全文案；
- 本机门禁通过：Python 660 项、Rust 180 项加 3 项默认忽略、TypeScript 24 文件 151 项、Vite 193 模块生产构建、依赖审计、源码敏感扫描、100 次浸泡和 11 组件 SBOM；
- Run `29286297352` 验证后端导出核心为 `success`，Run `29287096369` 验证最终桥接提交和完整构建为 `success`，文档态由 Run `29287933356` 复验；P3-006 关闭。

## 2026-07-14 第十批资源生命周期记录

- Runtime 将 Optimize 与插件调用统一纳入固定 4 worker、32 真等待的 FIFO 调度器；第 37 个任务返回 `runtime_busy`，等待取消、关闭竞态、worker 异常和部分启动失败均完成回收测试；
- 插件增加固定 4 槽隔离执行层、120 秒总时限、50,000 事件、2 MiB 累计输出和 64 事件缓冲；合作式与顽固插件均产生唯一安全终态，顽固插件不会继续制造线程；
- Host 活动路由上限为 64，私有通道为 64 普通事件加 1 个保留终态；慢消费者溢出后返回唯一 `runtime_unavailable` 并清理路由；
- 请求 ID 防重放改为 100,000 条会话窗口，窗口耗尽时仅在活动路由归零、旧 Runtime 停止且 reader 退出后安全轮转，不再淘汰旧 ID 后直接复用；
- History SQLite 对重复读写、写锁取消、仓储异常、导出超限和导出取消建立连接计数证据，所有路径 `opened == closed` 且最终 `active == 0`；
- 本机统一门禁通过：Python 681 项、Rust 184 项加 3 项默认忽略、Provider/性能/浸泡工具、安全扫描、依赖审计和 11 组件 SBOM；
- GitHub Actions Run `29300400632` 在干净 Windows Runner 完成全量验证、前端构建、构建物扫描和 SBOM 上传，结论为 `success`；P3-004 关闭，下一主线进入 P3-003 插件/历史资源浸泡。

## 2026-07-14 第十一批插件与历史资源浸泡记录

- 新增纯标准库 Windows 资源采样器，按 PID 采集 Private Bytes、Working Set、句柄和 OS 线程；PID、平台、WinAPI 失败和返回值均使用固定安全错误；
- 混合负载通过 Runtime `CapabilityRegistry` 交错执行 Batch Runner `parse` 与 History SQLite `save/list/detail/rate/export`，报告不含正文、记录 ID、数据库路径或密钥；
- 默认计划冻结为预热 100 次、正式 1,000 次、每 100 次采样；Private Bytes、句柄、线程、SQLite 活动连接和峰值连接阈值均进入自动判定；
- 连续三轮 1,000 次全部通过：Private Bytes 增量分别为 454,656、319,488、454,656 B；Working Set 增量分别为 958,464、720,896、933,888 B；句柄和线程增量均为 0；
- 三轮 SQLite 最终活动连接均为 0、峰值均为 1、数据库均为 114,688 B、WAL 均为 0 B；
- 统一验证增加 40 项工具契约和 100 次真实短烟测；扩展后的本机后端门禁全部通过；Run `29305552320` 远端复验为 `success`，P3-003 关闭。

## 2026-07-14 第十二批语义模型生命周期记录

- 新增共享模型生命周期锁和缓存代际，模型加载、下载、删除与状态读取不再并发破坏缓存；
- 同一检测器 4 路并发首次调用只执行一次模型工厂和一次场景向量初始化，其余调用复用结果；
- 下载或模型加载占锁时，管理命令稳定返回 `model_busy`；优化检测零等待回退 L0，不阻塞主链；
- 下载完成和删除完成使旧内存模型失效；删除后的下一次检测重新加载，不继续使用已删除缓存对应的旧模型；
- 下载中途取消、下载失败和模型工厂异常均释放生命周期锁；默认导入仍不加载 `sentence_transformers`、`torch` 或 `huggingface_hub`；
- 本机统一门禁通过：Python 686 项、Rust 184 项加 3 项默认忽略、两类浸泡、安全扫描、依赖审计和 11 组件 SBOM；
- GitHub Actions Run `29306300319` 完成全量验证、前端构建、构建物扫描和 SBOM 上传，结论为 `success`；P3-007 关闭。

## 2026-07-14 第十三批历史性能与保留策略记录

- History SQLite 默认保留上限冻结为 10,000 条、180 天、512 MiB，任一先到；数量即时检查，年龄与容量按保存间隔检查，单批最多清理 500 条；
- 备份默认最多 3 个且最长 30 天，活动轮换检查点引用的备份不被普通清理删除；恢复旧备份时会补齐保留计数和状态元数据；
- 索引布局通过版本标记一次迁移，普通保存不再重复重建索引；关键词全文扫描具有 5 秒硬截止，并在批次与解密边界响应取消；
- 新增隐私安全 History 基准工具与 38 项契约，small 10 条和 heavy 2 条 smoke 接入统一门禁；
- 正式 10,000 条 small 基准通过：保存 P95/P99 28.087/37.382 ms，分页 P95/P99 9.196/9.897 ms，搜索最慢 1,225.626 ms，导出 7,168.004 ms，轮换 6,325.191 ms；
- 轮换总峰值 115,908,801 B，约为 57,925,632 B 数据库的 2.00 倍；History 插件 158 项和统一脚本契约通过，P3-008 关闭。

## 2026-07-13 第一批集成记录

- Release/bundled Sidecar 主动移除 `REFLEX_RUNTIME_DEVELOPMENT`，源码 debug 启动仍可显式使用开发模式；
- Core 正确映射 `OperationCancelled`，输出超过 2 MiB 或 50,000 个有效分片时返回安全 `output_too_large`；
- Runtime 最多同时执行 4 个 Optimize，最多注册 32 个异步任务，超限返回安全 `runtime_busy`；
- 新增 `tools/verify_backend.ps1`、脚本契约测试和 Windows CI；
- 主线程修正干净环境 `dev` 依赖和 Vitest 参数，并补充生产构建步骤；
- 修复干净 Windows Runner 缺少正式 Sidecar 时的 Rust 测试资源准备，测试占位文件仅在验证期间创建并自动清理；
- GitHub Windows Run `29255203782` 已完成 9 个 Python 包、Rust、TypeScript 测试和前端生产构建，结论为 `success`；
- Core 已在 120 秒单调时钟截止点终止迟到分片并返回安全 `request_timeout`，阻塞 HTTP 主动关闭仍由 P1-010 跟踪；
- Tauri 主窗口与历史窗口只允许固定本地入口，发布构建拒绝开发服务器，外链与危险协议不能替换当前 WebView；
- Host 请求 ID 防重放改为 100,000 条滚动窗口，活动 ID 在历史淘汰后仍禁止复用，不再永久拒绝新请求；
- OpenAI-compatible Provider 已独立于 MiniMax，具备有限重试、幂等键、安全错误、2 MiB/50,000 上限及 JSON/SSE 截断防护；
- 发布前敏感扫描已进入统一验证和 Windows CI，命中输出只包含相对位置与规则名；
- 本批仍未完成：主动关闭阻塞 HTTP、MiniMax 同等级协议防护、动态 Provider 目录和产品版本统一。

## 2026-07-13 第二至四批集成记录

- 阶段 0 全部任务完成，当前推进阶段切换为阶段 1；
- Runtime 与 Rust Host 建立唯一可信 Provider/模型目录，MiniMax 标记 `supported`，未完成真实门禁的兼容 Provider 固定为 `experimental`；
- Provider 取消回调可主动关闭阻塞 HTTP 与重试退避，Core 120 秒 watchdog 到期触发相同中断并稳定返回 `request_timeout`；
- MiniMax 与 OpenAI-compatible 均完成有限重试、空响应、截断、非法 UTF-8、2 MiB 和 50,000 事件上限；
- Sidecar 异常 EOF 会清空路由、发出唯一安全终态、终止残留进程并允许下一请求重启；
- Credential Manager 保存、读取、掩码、删除实机闭环通过；Tauri 主/历史窗口权限矩阵完成最小化；
- 历史库恢复在主库截断、备份损坏、替换中断和轮换 checkpoint 异常下保护最后有效数据；
- Markdown 与批处理新增危险协议、活动 HTML、CSV 公式、畸形引号、路径字段、取消和资源上限夹具；
- 本阶段剩余主阻塞：脱敏真实 Provider 冒烟工具与新凭据实机门禁；前端动态目录消费由前端负责人承接；产品版本统一仍由 P4-001 跟踪。

## 2026-07-15 云端预算与运维加固记录

- 新增每日全局请求上限和预估成本预算账本；Provider 调用前按保守输出上限预占，
  成功、失败、额度拒绝和连接中断路径均有结算或回退，账本不保存安装 ID、正文或原始 IP；
- `/v1/admin/analytics/usage` 新增今日预算日期、请求/成本已用、预占、剩余、使用率和超限状态；
- 新增 Caddy `public` Compose profile、16 MB 请求体上限、SSE 不缓冲和严格代理头信任范围；
- 新增 PostgreSQL custom-format 备份与隔离恢复脚本，恢复脚本拒绝直接写入 `reflex_cloud`；
- 新增只读预算巡检脚本，使用退出码区分正常、预警和临界状态，不输出管理令牌；
- 云服务门禁 `tools\verify_cloud.ps1` 通过：运维契约、Compose 解析和 `31 passed`；
- 为 Core、MiniMax Provider 和模板命名上下文增加 `.dockerignore`，生产上下文降至约 317 KB；
- Dockerfile 改为多阶段 `uv 0.11.13` + `uv sync --frozen`，生产依赖与 `uv.lock` 一致；
- `reflex-cloud:0.1.0-alpha.6` 锁定镜像构建成功，约 95 MB，镜像用户为 `reflex`；
- 使用 alpha.6 隔离 Compose 完成健康、预算、默认隐私、中文错误、新表和容器权限验证；
- 完成 custom-format 备份、SHA-256 校验和隔离恢复，恢复库含 9 张表、安装记录一致；QA 容器、卷、构建器和临时文件均已清理。

## 2026-07-15 版本元数据统一记录

- 新增根级 `VERSION` 作为发布版本基线，桌面 Tauri、Cargo、npm、Core、Runtime 和 Cloud 清单统一到 `0.7.0-alpha.7`；
- npm、Cargo 和 10 个 Python 项目的锁文件由各自工具重新生成，Python 预发布版本按 PEP 440 记录为 `0.7.0a7`；
- 版本门禁覆盖 14 个发布清单和锁文件来源，并兼容 Windows PowerShell 5.1 对 npm lock 的解析限制；
- 前端状态栏改为读取构建包版本，云服务 OpenAPI 改为读取已安装分发包版本，不再显示旧的 `v0.6 beta` 或 `0.1.0`；
- 版本契约和统一验证契约通过；Core 90 项、Runtime 303 项（6 项条件跳过）、Cloud 32 项、前端 158 项和 Rust 188 项（3 项系统凭据实机测试默认忽略）通过，前端生产构建成功；
- P4-001 已关闭；P4-002/P4-003 的 Windows 11 证据完成，Windows 10 仍待补；P4-004 配置/历史兼容进行中，P4-005 签名/更新/回滚和 P4-006 发布清单仍待处理。

## 2026-07-15 alpha.8 干净构建与生命周期记录

- Windows 11 权威验证副本来自提交 `8310736`，版本清单和临时发布标签均为 `v0.7.0-alpha.8`；
- `uv sync --frozen`、`npm ci`、Runtime 单文件构建、`cargo build --locked` 和 `npm run tauri:build` 全部通过；
- 发布版 Host 启动、Sidecar `ping/shutdown`、同版本覆盖安装、静默卸载、重装和最终清理均已实机执行；
- Windows 10 干净构建和生命周期尚无同等级实机证据，因此 P4-002/P4-003 保持待验证；
- 未验证跨版本升级、配置/历史迁移、代码签名、更新和回滚；这些仍按 P4-004/P4-005 处理。
- 配置与历史数据层迁移契约已验证，真实跨版本覆盖安装仍按 P4-004 处理；

## 2026-07-15 Provider 动态目录接入记录

- 新增前端 `ProviderCatalogBridge`，在发送目录命令前订阅固定事件，使用 Rust 返回的请求 ID过滤旧事件；
- 前端镜像 Runtime 的 Provider 目录边界：版本、请求 ID、字段集合、Provider/模型数量、排序、默认模型、发布状态和会话配置状态；
- `provider_catalog_error`、监听失败、命令失败和超时均转换为固定的“模型目录暂不可用，请稍后重试。”，不向用户透传底层错误或任何凭据内容；
- 设置页 Provider 列表、模型列表和默认模型均来自 Runtime 目录；浏览器 Demo 保留静态目录，Tauri 目录暂不可用时保留安全回退并显示状态提示；
- `npm test -- --maxWorkers=2`：26 个测试文件、163 项通过；`npm run build`：242 个模块构建通过；`cargo test --locked --lib -- --test-threads=2`：191 项通过、3 项 Credential Manager 测试按平台条件忽略；
- 本项不改变 Provider 密钥存储、Runtime 配置或真实请求正文边界。

## 2026-07-15 跨版本历史迁移加固记录

- 修复相同 `user_version`、旧索引布局历史库迁移前不创建备份的问题；布局迁移现在与 schema 迁移一样先执行在线备份；
- 新增 `tools\cross_version_history_upgrade_smoke.py`，使用显式离线 Mock 让旧 Runtime 生成真实加密历史，再由当前 Runtime 读取、列表、新写入和校验迁移备份；
- 旧 Runtime 实际库为 schema `1`/旧布局，当前库为 schema `1`/布局 `3`，`history.sqlite3.migration-v1.bak` 保留旧快照；
- 当前修复后的 alpha.8 NSIS 包重新执行 8 阶段 Windows 隔离生命周期，全部通过；
- 该证据使用源码重建 beta.11 夹具，不等同于历史官方签名包或真实用户数据，P4-004 保持进行中。

## 2026-07-15 长期浸泡复盘记录

- 72 小时 Runtime 浸泡报告已落盘，但在约 4.58 小时、824 次迭代时因一次取消请求收到完成终态而提前停止；
- 该报告明确标记 `passed=false`，因此不能把这轮当作 P3-002 完成证据；下一轮需要先定位取消竞态，再重新满足 10,000 次和 72 小时双门槛。
- 根因是 Mock 分片间只留 10ms 取消处理窗口，长时间系统调度抖动偶发让请求先完成；窗口调整为 100ms 后，仍在首 chunk 后发送取消且继续拒绝任何迟到 `chunk` / `done`；
- 修复后工具契约 15 项和 2,000 次有界浸泡通过；现有 12 小时旧夹具任务保持运行，不与新 72 小时门禁并发。

## 2026-07-15 发布候选物料记录（历史 11 组件证据）

- 当时新增发布候选物料生成器和验证器，固定收集安装包、Host、Runtime、11 项 SBOM、发布说明、恢复指南和校验和；
- 验证器重新计算文件哈希，绑定源码提交、版本、标签、工作树状态、锁文件和用户文档，并执行二次敏感扫描；
- 该历史 alpha.8 审查包 19 个文件全部通过完整性验证，但因未签名、无匹配发布标签和工作树保留用户改动，正式就绪门禁稳定返回 `release_not_ready`；Cloud 纳入供应链后，该 11 组件物料不能继续作为当前 RC；
- 旧提交生成的物料在当前源码上会被拒绝，来源漂移检查已实跑通过；P4-005/P4-006 仍未达到正式发布条件。

## 2026-07-15 云服务供应链门禁增量记录

- `services/reflex-cloud` 已加入后端验证、依赖审计策略、SBOM 生成、发布候选生成和发布候选验证，共覆盖 10 个 Python 项目、12 个总组件；
- Cloud 许可证元数据按锁定版本逐项复核并纳入精确覆盖，未放宽未知许可证规则；真实全生态依赖审计返回 `Dependency audit passed.`；
- 真实 SBOM 复核结果：12 个 CycloneDX 1.5 组件、13 个 SBOM 目录文件，所有源锁文件 SHA-256 与组件 SBOM SHA-256 均匹配；
- 发布工具错误输出改为稳定单行 stderr 类别，长路径 worktree 下的发布候选契约也已通过；当前候选仍需正式签名、匹配标签、干净工作树和最终 RC 审计。
- 本轮提交 `851c29a`、`d23be08` 已推送到 `origin/codex/full-feature-parity`；新提交对应的 Windows CI、前端 Artifact 和完整发布候选复核仍待完成。
- 用户发布文档已纳入候选包：隐私、第三方软件、支持范围和故障处理均完成来源绑定与敏感信息复核。
- Cloud 完整部署复验：`verify_cloud.ps1`（含真实 Docker Compose 配置渲染）通过，运维契约通过，Cloud 测试 `39 passed`；仅产生弃用警告，不影响退出码。
- 本轮后续提交 `ab2ec26`、`e3ec04e`、`59e5062` 已推送；最新 CI Run `29388421937` 在启动前因账户计费限制失败，未执行代码步骤，待外部计费恢复后重跑。

## 2026-07-15 云端隐私与准入事务加固记录

- 反馈提交现在由服务端核对当前安装授权记录和政策版本；提示词/结果必须具备改进计划授权，截图只有在本次反馈明确勾选后才会写入，客户端字段不能绕过正文授权；
- 新增 `consent_required`、`consent_outdated`、`quota_unavailable` 和 `ip_quota_unavailable` 用户可见错误分类；
- 一次云端优化的安装额度、IP 小时限流和全局预算预占改为同一数据库事务，任一准入失败都会回滚其余准入变更，并处理多实例首次建行竞争；
- 云服务测试：`36 passed`；Python 编译检查通过；运维契约 `reflex_cloud_ops_contract.ps1` 通过；`verify_cloud.ps1 -DryRun -SkipDocker` 通过；前端 `163 passed`、生产构建和 Rust Host `192 passed/3 ignored` 通过；
- 修复提交 `ec110f6`、`c215822`、`050fc33`、`59e5464`、`4909e64`、`7593ead`、`924d35d` 已推送到 `origin/codex/full-feature-parity`；本记录不关闭 P3-002、P4-002、P4-003、P4-004、P4-005 或 P4-006。

## 2026-07-15 Cloud 错误边界与前端恢复动作加固记录

- Rust Host 对 Cloud 非成功响应只读取有界错误体中的白名单 `error.code`，未知码、超大错误体和服务端原始 `message` 均回退固定安全文案；反馈错误复用有界解析，避免异常响应造成无界读取；
- Cloud HTTP 错误已覆盖额度、IP 限流、全局预算、Provider 配置、容量、并发、请求冲突和隐私授权等用户可操作分类；Cloud SSE 错误事件按白名单码重建，不再透传 Core/服务端原始字段；
- 前端将错误转换为稳定的 `code`、中文提示和恢复动作，设置、重试、修改输入和重新打开应用分别呈现，英文界面补齐对应翻译；
- 针对性 Rust 测试 `6 passed`，前端定向测试 `18 passed`；前端全量 `26` 个测试文件、`166 passed`，Vite `242` 个模块构建通过；Rust Host 全量 `194 passed`、`3 ignored`；
- 全仓 `cargo fmt --check` 仍受既有 `commands.rs` 及用户修改中的 `config_store.rs` 格式差异影响；本轮只定向格式化 `feedback.rs`，未覆盖用户文件；
- 长期 12 小时浸泡仍在运行，72 小时正式门禁和 GitHub CI 计费阻塞仍保持未决，不因本轮错误边界修复提前关闭 P3-002 或 P2-006。

## 集成约定

- 子智能体完成后只进入“待集成”，不得自行宣布阶段完成；
- 主线程审查差异、运行相关测试，再运行统一后端门禁；
- 每次提交后更新本账本的状态和证据；
- 阶段门禁失败时回到对应任务，不跳到下一版本；
- 阶段完成后立即选择下一阶段最高价值任务继续推进。

## 2026-07-15 反馈链路收尾记录

- 反馈面板移除截图操作现在会清空待提交截图，而不只是取消勾选；
- 反馈提交异常统一经过前端白名单归一化，保留用户可操作的授权/限流提示，未知错误回退为固定安全文案；
- 前端验证：26 个测试文件、167 项通过；Vite 生产构建 242 个模块通过；
- 本轮仅完成反馈链路收尾，不关闭 P3-002、P2-006、Windows 10 验证、签名/更新/回滚或正式 RC 门禁。

## 2026-07-15 `cf45530` 当前提交供应链复核

- 在 detached 干净工作树完成 `npm ci`、168 项前端测试和 242 模块生产构建；构建物共 6 个文件、357,528 B；
- `dist` 和受版本控制文件敏感扫描、敏感扫描契约、SBOM 契约及统一验证脚本契约全部通过；
- 生成 12 份 CycloneDX 1.5 BOM 和 1 份清单；独立复算 BOM、源锁文件和清单哈希，错误为 0；清单 SHA-256 为 `e97b72303c594066c343c32197db54ba3ba6d65dad8ec4d5bfea1a86d5c360fe`；
- Windows CI Run `29422634887` 精确绑定 `cf45530`，但 GitHub 因账户付款失败或 spending limit 在分配 Runner 前拒绝启动；Job 步骤和 Artifact 均为 0；
- 本机供应链符合；按用户确认的本地测试后提交、推送和直接合并策略，远端 Artifact 不再作为门禁，`P2-006` 关闭。完整证据见 `docs/verification/build-artifact-sbom-alpha8-20260715.md`。

## 2026-07-15 P3-002 正式浸泡启动与 Cloud 回归

- 已启动正式 Runtime 请求/取消浸泡：至少 10,000 次、最低 72 小时、批量 4、每分钟 3 次、每 2 次请求取消；报告路径为 `workbench\runtime-soak-72h-alpha8-20260715-130930.json`；报告生成前不视为通过；
- `verify_cloud.ps1 -SkipDocker` 的运营契约通过；因已运行的 `reflex-cloud.exe` 锁定虚拟环境入口，官方 `uv run` 测试包装器未能执行安装步骤；使用同一 `.venv` 的 `python -m pytest -q` 完成 Cloud 全量测试，结果 `39 passed`、1 个上游弃用警告；
- 本记录不提前关闭 P3-002，也不改变 P2-006、P4-002、P4-003、P4-004、P4-005 或 P4-006 状态。

## 2026-07-15 Cloud 本机验证器锁定兼容

- `tools\verify_cloud.ps1` 增加显式 `-NoSync` 选项；CI 默认行为仍保持冻结依赖同步，本机已有服务运行时可避免替换被占用的入口文件；
- `powershell -NoProfile -ExecutionPolicy Bypass -File tools\verify_cloud.ps1 -SkipDocker -NoSync` 通过：运营契约通过、Cloud 测试 `39 passed`、Docker 按参数跳过。

## 2026-07-15 Cloud 质量发布闭环收尾

- 新增质量发布、来源反馈和质量曝光数据模型；草稿只接受经过校验的人工指导，来源反馈必须处于 `fixed` 或 `released` 才能发布；
- 新增公开质量发布元数据接口、管理员草稿/列表/详情/发布/回滚接口，发布与回滚使用进程锁、数据库行锁、事务回滚和唯一发布索引；
- Cloud 优化请求按发布版本注入受限指导，响应返回版本头；客户端只消费版本、标题、摘要、模板包版本、来源数量和发布时间；
- 匿名质量曝光默认关闭，开启后按安装身份和请求 ID 幂等记录 `baseline` 或质量发布版本；反馈分析支持 `by_quality_release`，删除安装数据会删除曝光记录；
- 管理后台支持场景指导 JSON、来源反馈一键加入、用户可见错误、创建草稿、发布/回滚确认和效果展示；设置页新增匿名质量分析开关与当前质量版本展示；
- 定向 Cloud 回归：`12 passed`；完整 Cloud `48 passed`、前端 `168 passed`、Rust Host `194 passed/3 ignored`，Vite 生产构建 `242 modules` 通过；
- Cloud 运维契约和受版本控制文件敏感扫描均以退出码 `0` 通过；统一验证契约输出 `verify_backend contract checks passed.` 后外层执行器超时，未将该次退出码记作成功，相关 Cloud、前端、Rust 和命令权限分项均已独立复验；
- 本项不关闭 P3-002、P2-006、Windows 10 验证、真实多实例并发、签名/更新/回滚或正式 RC 门禁。

## 2026-07-15 PostgreSQL 质量发布并发门禁建设

- 新增 `tools\reflex_cloud_postgres_quality_release_smoke.py`：只读取 `REFLEX_CLOUD_POSTGRES_TEST_URL`，强制测试库命名、回环地址和随机 schema，设置连接/锁/语句超时，结束后清理 schema；
- 烟测覆盖两个独立数据库连接池下的同版本并发发布、不同版本并发发布、同一版本并发回滚、部分唯一索引核验和唯一安全终态；
- 新增 5 项工具契约测试，验证数据库地址守卫、远程访问显式授权、固定输出字段、缺少配置和凭据不回显；统一验证步骤已接入；
- 初次因本机可用虚拟内存不足而暂缓；随后使用 128 MiB/0.5 CPU、回环端口和 tmpfs 的独立 PostgreSQL 16 容器完成真实验证；结果为同版本发布 `1` 个成功、不同版本发布 `1` 个成功、回滚 `1` 个成功、最终 `published_count=1`、唯一索引有效、schema 清理成功；
- 数据库侧复核随机 schema 残留为 `0`，临时容器与端口已清理；完整证据见 `docs\verification\cloud-postgres-quality-release-2026-07-15.md`；
- 测试后的低虚拟内存曾导致 Docker Desktop 退出，已恢复原有三个容器和长期浸泡任务；新增资源保护包装器，低于 2 GiB 可用物理内存或 4 GiB 可用虚拟内存时拒绝执行。

## 2026-08-12 alpha.8 供应链修复与 Windows 生命周期复验

- 统一依赖门禁首次定位到 `cryptography 48.0.1` 对应的 `PYSEC-2026-3552`、`PYSEC-2026-3553`、`PYSEC-2026-3554`；历史插件和 Runtime 已统一升级到 `cryptography>=50.0.0,<51`，锁文件、依赖审计策略和测试均同步更新。
- `tools\build_runtime_sidecar.ps1` 已在构建前显式执行冻结依赖同步（含 `dev`、`builtins` extra），修复虚拟环境存在但缺少 PyInstaller 时的打包失败；`npm run package:windows` 已完成完整 NSIS 构建。
- 统一发布门禁复验通过：Core `90 passed`、Runtime `317 passed`、Cloud `81 passed`、History `159 passed`、Rust `194 passed, 3 ignored`、Frontend `27` 个文件/`184 passed`、原生协议 `13 passed`；依赖审计、密钥扫描、SBOM/契约检查均通过；短浸泡 `100 iterations`（`50 completed`、`50 cancelled`）通过。
- 冻结 Sidecar 探测通过：Anthropic `claude-3-5-haiku-20241022` 与 Gemini `gemini-2.5-pro` 均返回 `catalog_ok`；未读取真实 API Key，未调用真实第三方模型。
- 最新安装包为 `apps\tauri-host\src-tauri\target\release\bundle\nsis\Reflex_0.7.0-alpha.8_x64-setup.exe`，英文工作台修补后重新构建于 `2026-08-12 13:17:58`，大小 `21,861,462` bytes，SHA-256 `D834199CF786A18B853508B2C82BB72E2BE23E4D3FDB7038FC643511633656F5`；该包已通过包级密钥扫描。
- Windows 11 隔离生命周期已通过：`install`、`sidecar-ping-shutdown`、`host-start`、`legacy-config-start`、`overlay-install`、`uninstall`、`reinstall`、`final-cleanup`；未知用户文件保持不变。
- 上述生命周期已使用本轮新包哈希 `D834199CF786A18B853508B2C82BB72E2BE23E4D3FDB7038FC643511633656F5` 重新实跑，`LIFECYCLE_RESULT.status=passed`，并确认 `unknown_file_preserved=true`。
- 当前构建 Runtime 的真实 MiniMax 脱敏冒烟已复跑：命令为 `packages\reflex-runtime\.venv\Scripts\python.exe tools\provider_smoke.py --operation all --provider minimax --runtime apps\tauri-host\src-tauri\resources\runtime\reflex-runtime.exe --timeout-seconds 30 --cancel-after-ms 250`；Runtime SHA-256 为 `C7113743B89D3E1D5EB11384289A32144BCA865F6E11C53C11424C64F7BA570C`。结果：目录 `catalog_ok`；真实流式请求 `success`，首个分片 `5906 ms`、总耗时 `5922 ms`、`1` 个分片；真实取消 `cancelled`，总耗时 `265 ms`、取消延迟 `15 ms`、无分片。凭据来自 Windows Credential Manager，未把密钥、请求正文或响应正文写入输出。
- 本轮仍不关闭 P3-002、P4-002、P4-004、P4-005、P4-006：72 小时/至少 10,000 次正式 Runtime 浸泡、Windows 10 干净环境、官方旧版安装包与真实脱敏用户数据升级、代码签名/更新/回滚及正式 RC/v1.0.0 标签仍未形成完整证据。
- UI 复核发现的英文核心工作台混杂文案已修复：输入区、结果区和生成配置条统一接入 `tr`，英文契约与全量前端回归通过；其他低频页面仍需在 RC 前做一次全局英文可见层扫描。当前建议保持 `v0.7.0-alpha.8` Windows 11 受控试用版定位。

## 2026-08-13 P3-002 浸泡挂起诊断与切片睡眠修复

- 正式 168 小时/10,000 次浸泡于 2026-08-13 19:49 启动，约 30 分钟、第 25 批（约 100 次）后挂起：驱动与 Runtime 子进程 CPU 全部冻结且不再推进；
- py-spy 转储（`workbench\soak-stuck-driver-20260813-2019.txt`、`soak-stuck-runtime-20260813-2019.txt`）显示驱动主线程停在限速 `time.sleep`，子进程健康等待 stdin、worker 空闲；排除机器睡眠（无电源事件）与请求路径问题；结论为限速长等待偶发不返回；
- 高速复现 600/min×10,000 次通过：`runtime-soak-repro-fast-20260813-2022.json`，5,000 完成/5,000 取消、65,000 协议事件、`passed=true`；独立 12×80s 长 sleep 微实验全部精确返回，确认非确定性复现；
- 修复：`tools\soak_backend.py` 限速等待改为 1s 粒度切片循环（`_sliced_sleep`，默认 sleeper，注入契约不变），新增契约测试 1 项；`16 passed`，有界限速验证 `passed=true`；
- P3-002 保持进行中，正式浸泡在修复后重新启动。

## 2026-08-14 本地 HTTP 宿主（SSE）形态建立

- 新增 `packages/reflex-http-host`：本地 HTTP 宿主，网关进程消费同一套 NDJSON sidecar 协议（与 Tauri 宿主同构），零侵入 Core/Runtime；
- 端点：`POST /v1/optimize`（SSE 流式，客户端可自选 request_id，断开自动 cancel）、`POST /v1/requests/{id}/cancel`、`POST /v1/ping`、`GET /v1/providers`、`GET /v1/health`；默认绑定 127.0.0.1:8790，可选 Bearer 鉴权（REFLEX_HTTP_TOKEN），单请求 120s 超时，子进程环境白名单不继承凭据；
- 契约测试 40 项通过（包内 23 + 工具契约 17），`verify_backend.ps1 -PythonProject reflex-http-host` 与 `check_version_consistency.ps1` 通过；
- 分级并发压力证据 `workbench/http-soak-graded-20260814-0400.json`：并发 1/4/16/32 × 20 次全通过，取消每 4 次全部命中 cancelled 终态，零串线零缺终态；P95 884-1488ms；连接级偶发抖动经单次重试消化；Runtime 4 活跃+32 排队容量为并发硬边界，超限以 runtime_busy 稳定语义表达；
- 验证记录 `docs/verification/backend-http-host.md`；P3-002 等现有门禁状态不变。
