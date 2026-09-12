# Reflex Next 文档导航

更新时间：2026-09-12

本页是项目文档入口。文档之间出现状态差异时，按下列顺序判断：

1. [AGENTS.md](../AGENTS.md)：项目边界和协作规则；
2. [后端生产化路线图](BACKEND-PRODUCTION-ROADMAP.md)：生产化目标和阶段门禁；
3. [更新日志](../CHANGELOG.md)：当前版本状态；
4. 与具体能力对应的源码、测试和 `docs/verification/` 证据；
5. 迁移计划、开发记录和历史设计文档用于追溯。

历史文档用于解释设计来源，不代表当前任务仍处于当时阶段。

## 术语表

| 术语 | 含义 |
|---|---|
| Sidecar | 与桌面宿主同进程组外独立运行的 Python 子进程，通过 NDJSON 管道通信 |
| 稳定性测试（soak） | 长时间、大批量连续请求/取消的耐久验证（如 10,000 次 / 72 小时） |
| 门禁 | 合并或发布前必须通过的自动化验证关卡 |
| 脱敏 | 日志与错误输出中移除密钥、完整输入等敏感内容的处理 |
| 受控试用 | 在受限范围内邀请真实用户使用并收集反馈的发布前环节 |

## 架构与迁移

- [架构设计](ARCHITECTURE.md)
- [架构审计](ARCHITECTURE-AUDIT.md)
- [架构债务登记](ARCHITECTURE-DEBT-REGISTER.md)
- [Provider 适配层策略](PROVIDER-ADAPTER-STRATEGY.md)
- [功能迁移](MIGRATION.md)
- [旧版参考映射](CLASSIC-REFERENCE.md)
- [UI 实现规格](UI-IMPLEMENTATION-SPEC.md)

## 生产化与发布

- [后端生产化目标](BACKEND-PRODUCTION-GOAL.md)
- [后端生产化路线图](BACKEND-PRODUCTION-ROADMAP.md)
- [Cloud 闭环架构](CLOUD-CLOSURE-ARCHITECTURE.md)
- [Cloud Beta 部署说明](CLOUD-BETA-RELEASE.md)
- [Alpha.8 发布说明](releases/v0.7.0-alpha.8.md)
- [签名、更新与回滚方案](RELEASE-SIGNING.md)
- [发布恢复指南](RELEASE-RECOVERY.md)

## 用户文档

- [隐私说明](PRIVACY.md)
- [支持范围](SUPPORT.md)
- [试用方案模板](USER-TRIAL-0.7.1.md)
- [故障处理](TROUBLESHOOTING.md)
- [第三方软件声明](THIRD-PARTY-NOTICES.md)

## 验证证据与开发记录

- `docs/verification/`：可复核的测试、性能、Provider、Cloud、升级和发布证据。较早版本的通过记录不能替代当前版本的正式门禁。
- `docs/dev-records/`：按日期形成的实现记录，用于追溯，不承担当前状态维护职责。
