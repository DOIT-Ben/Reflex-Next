# Reflex Next 工作台

更新时间：2026-09-12

本文件是维护者的工作区快照：当前阶段、已实现范围与验证基线。对外状态以
[更新日志](../CHANGELOG.md) 和 [后端生产化路线图](../docs/BACKEND-PRODUCTION-ROADMAP.md) 为准；
迁移计划、开发记录和早期设计文档只用于追溯。

## 当前阶段

项目处于 `v0.7.0-alpha.8` 生产化收尾阶段，不是正式稳定版。

- 阶段 0：13/13 完成；
- 阶段 1：14/14 完成；
- 阶段 2：11/11 完成；`cf45530` 本机供应链复核通过，远端 workflow 已支持 push、pull request 和手动入口；分支保护是否强制该检查仍需仓库设置核验；
- 阶段 3：7/8 完成，正式 72 小时稳定性测试（soak）待重新运行；
- 阶段 4：版本统一完成，Windows 10、真实升级、签名和发布候选仍在处理；
- 阶段 5：用户文档完成，受控试用、最终回归、签名包和 `v1.0.0` 尚未开始。

## 已实现范围

### Core 与 Runtime

- 稳定请求模型、事件信封、场景路由、模板渲染、安全校验和通用场景回退；
- 固定并发和等待队列、请求 ID 生命周期、总时限、输出和分片上限；
- Runtime NDJSON 命令循环、插件发现、取消、Sidecar 崩溃恢复和脱敏诊断；
- Core 导入不引入 PyQt、PySide、sqlite3、pyperclip、torch、sentence-transformers 或 huggingface-hub。

### Provider 与插件

- MiniMax 和 OpenAI-compatible Provider 的流式、取消、重试、断流和错误分类；
- 内置模板包、49 个场景（其中 42 个二级子场景）和多风格渲染；
- 加密历史、翻译、批处理、Markdown 预览和可选语义识别；
- 历史恢复、轮换、大数据量性能和插件资源长稳测试。

### 桌面宿主与前端

- Svelte/Vite 主界面、命令面板、设置、历史、结果对比和反馈面板；
- Rust Host、常驻 Sidecar、托盘、全局快捷键、窗口恢复和剪贴板策略；
- Windows Credential Manager、Tauri capability 白名单和外部导航限制；
- 动态 Provider/模型目录以 Runtime 为 Tauri 运行时权威来源；前端保留的浏览器/Demo fallback 只是降级快照，必须通过版本与一致性测试，不能当作生产真值。

### Reflex Cloud

- 匿名安装身份、隐私授权、免费额度和全局预算；
- 用户反馈、可选截图、提示词改进计划和数据删除；
- 管理端反馈分析、质量草稿、发布、回滚和曝光归因；
- 质量发布的 PostgreSQL 多实例发布/回滚、唯一终态和 schema 清理已有历史验证；
- Cloud 默认本机端口为 `8787`，其他项目的 `8020` 服务不属于 Reflex Cloud。

## 当前验证基线

- Python：13 个项目已纳入 `tools/project-registry.json`；本轮当前工作树实际回归 Core 109 项、Runtime 333 项、HTTP Host 44 项、Reflex Cloud 86 项、MiniMax Provider 32 项，均为退出码 0 的包级 `uv run --locked ... pytest`；
- Rust/Tauri Host：本轮 `cargo test --locked --lib -- --test-threads=2` 通过 197 项、忽略 3 项、失败 0 项；3 项 Credential Manager 实机测试仍需单独环境；
- 前端：本轮 `npm test -- --run` 通过 30 个测试文件、222 项测试，Vite 生产构建转换 267 个模块；
- Runtime：本轮包级 333 项通过；另有既有本机 10,000 次短门禁记录，完成和取消各 5,000 次；
- Provider：真实 MiniMax 流式成功和取消通过，证据不保存正文或密钥；
- Cloud：本轮补充独立服务实例的输出额度并发回归；质量发布/回滚有 PostgreSQL 16 历史证据但本轮未重跑，输出额度结算的 PostgreSQL 16 多实例门禁仍未关闭；
- 安全：受版本控制文件敏感扫描、依赖审计、许可证和权限矩阵已有通过记录。

以上证据绑定的是 2026-08-29 当前工作树，不绑定某个提交，不能替代仍未完成的正式发布门禁；短浸泡报告为本机运行产物，不入库。每次提交必须先完成与改动范围匹配的本地隔离验证；后端 workflow 已支持 push、pull request 和手动触发，默认 push/PR 执行常规代码门禁和 Windows 生命周期工具契约，短浸泡 smoke、依赖实审和 SBOM 通过手动 `run_heavy` 入口执行；正式 Windows 生命周期和 72 小时稳定性测试仍需独立发布门禁实跑，分支保护是否实际要求该 workflow 仍需仓库设置确认。

## 未完成门禁

1. 正式 72 小时且至少 10,000 次请求/取消稳定性测试（soak）；
2. Windows 10 干净构建、安装、覆盖安装、卸载和重装；
3. 官方旧版包和真实旧数据的完整升级链路；
4. 实际代码签名、更新和回滚演练；
5. 受控试用、全量回归、签名安装包、回滚包和 `v1.0.0`。

## 工作区约束

- 根目录 `resources/` 是本地旧资产参考，不修改、不暂存；
- 根目录前端设计归档不进入版本库；
- `workbench` 下截图、日志和 soak JSON 是本地运行产物，不提交；
- `.env`、`.env.local`、凭据和真实用户数据不得读取或提交；
- 已有用户修改不得回滚、格式化或混入项目整理提交；
- 不创建正式安装包或 Tag，除非全部门禁满足并获得明确批准。

## 文档入口

- `docs/INDEX.md`：统一文档导航；
- `docs/ARCHITECTURE.md`：架构边界；
- `docs/MIGRATION.md`：迁移设计基线；
- `docs/BACKEND-PRODUCTION-GOAL.md`：长期完成标准；
- `docs/BACKEND-PRODUCTION-ROADMAP.md`：阶段门禁；
- `docs/verification/`：可复核验证记录。

## 后续顺序

1. 在资源条件满足时重新运行正式 72 小时稳定性测试（soak）；
2. 为当前提交取得构建物扫描和 SBOM 证据；
3. 在 Windows 10 环境完成构建与安装生命周期；
4. 使用官方旧版本和脱敏真实数据完成升级验证；
5. 准备证书并完成签名、更新、回滚和 RC 审计；
6. 受控试用通过后再生成正式发布物和 `v1.0.0`。
