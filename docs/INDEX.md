# Reflex Next 文档导航

更新时间：2026-08-28

本页是项目文档入口。文档之间出现状态差异时，按下列顺序判断：

1. `AGENTS.md`：项目边界和协作规则；
2. `workbench/backend-production-tasks.md`：当前任务状态和验证证据；
3. `docs/BACKEND-PRODUCTION-ROADMAP.md`：生产化目标和阶段门禁；
4. 与具体能力对应的源码、测试和 `docs/verification/` 证据；
5. 迁移计划、开发记录和历史实施计划。

历史文档用于解释设计来源，不代表当前任务仍处于当时阶段。

## 架构与迁移

- [架构设计](ARCHITECTURE.md)
- [架构审计](ARCHITECTURE-AUDIT.md)
- [架构债务登记](ARCHITECTURE-DEBT-REGISTER.md)
- [Provider 适配层策略](PROVIDER-ADAPTER-STRATEGY.md)
- [功能迁移](MIGRATION.md)
- [旧版参考映射](CLASSIC-REFERENCE.md)
- [UI 实现规格](UI-IMPLEMENTATION-SPEC.md)

## 当前生产化

- [后端生产化长期目标](BACKEND-PRODUCTION-GOAL.md)
- [后端生产化路线图](BACKEND-PRODUCTION-ROADMAP.md)
- [生产任务账本](../workbench/backend-production-tasks.md)
- [Cloud 闭环架构](CLOUD-CLOSURE-ARCHITECTURE.md)
- [Cloud Beta 部署说明](CLOUD-BETA-RELEASE.md)

## 发布与用户文档

- [Alpha.8 发布说明](releases/v0.7.0-alpha.8.md)
- [签名、更新与回滚方案](RELEASE-SIGNING.md)
- [发布恢复指南](RELEASE-RECOVERY.md)
- [隐私说明](PRIVACY.md)
- [支持范围](SUPPORT.md)
- [首次成功受控试用](USER-TRIAL-0.7.1.md)
- [故障处理](TROUBLESHOOTING.md)
- [第三方软件声明](THIRD-PARTY-NOTICES.md)

## 验证证据

`docs/verification/` 保存可复核的测试、性能、Provider、Cloud、升级和发布证据。
当前仍未完成的正式门禁以生产任务账本为准，不能用较早版本的通过记录替代。

## 开发记录

`docs/dev-records/` 保存按日期形成的实现记录。它们用于追溯，不承担当前状态维护职责。
