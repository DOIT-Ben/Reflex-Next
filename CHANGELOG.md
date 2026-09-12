# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号采用语义化版本（`MAJOR.MINOR.PATCH-阶段.N`）。

## [Unreleased]

### 变更

- 前端架构重构：App.svelte 从 2851 行拆解至约 1750 行，全部功能流下沉为
  `domain/` 下的可注入、可单测控制器（优化主链、设置、批处理、翻译、模板、
  Markdown 预览、语义模型、剪贴板、反馈、首启激活、云隐私、诊断包、
  窗口控制、滚动同步、toast、视图缩放、下载助手），键盘策略与工作台
  视图模型亦纯函数化，并新增架构测试守护分层与行数预算；
- 抽取 `i18nStore` 统一组件翻译注入，支持运行时切换 UI 语言；
- 统一 `DialogShell` 弹窗外壳（背板层/尺寸档/关闭按钮/Esc/自动聚焦）并抽取 `Spinner` 组件；
- 修复 StatusBar 与窗口底边空隙；生成完成/失败时结果区自动滚入视野。

## [0.7.0-alpha.8] — 2026-09-01

### 新增

- 新增原生协议与 Responses Provider 插件，语义检测对齐场景库；
- 完成首次成功与结果采用闭环、完整功能合并；
- 前端工作台与反馈链路对齐；Cloud 质量发布与反馈链路完善。

### 修复

- 收口 Runtime 启动握手与发布门禁；
- 闭环审查质量门禁与架构审查修复；
- 收口首次激活测试密钥扫描。

## [0.7.0-alpha.7] — 2026-07-15

- 统一产品版本与发布门禁。

## [0.7.0-alpha.6] — 2026-07-15

- 加固云端预算与发布运维链路。

## [0.7.0-alpha.5] — 2026-07-15

- 加固云端 Beta 发布链路。

## [0.7.0-alpha.4] — 2026-07-14

- 接通桌面云端生成与隐私控制。

## [0.7.0-alpha.3] — 2026-07-14

- 打通云端生成与质量分析。

## [0.7.0-alpha.2] — 2026-07-14

- 建立云端免费额度账本；
- 打通反馈闭环与云端管理；
- 兼容 MiniMax 流式结束事件，修复前端历史查询与 Runtime 协议错位。

## [0.6.0-beta.11] — 2026-07-13

- 接入视图缩放与窗口控制；
- 收紧窗口与浮层交互密度。

## [0.6.0-beta.7] — 2026-07-13

- 重做模板管理视觉与交互层级；
- 统一主界面与模板编辑视觉体验。

## [0.6.0-beta.4] — 2026-07-13

- 接入语义模型管理界面并补齐后端；
- 加固插件桥接与用户错误提示。

## [0.6.0-beta.1] — 2026-07-12

- 首个 beta 基线：Core、Provider 插件、模板包、L0 场景识别与 Tauri 桌面宿主。

[Unreleased]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.8...HEAD
[0.7.0-alpha.8]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.7...v0.7.0-alpha.8
[0.7.0-alpha.7]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.6...v0.7.0-alpha.7
[0.7.0-alpha.6]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.5...v0.7.0-alpha.6
[0.7.0-alpha.5]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.4...v0.7.0-alpha.5
[0.7.0-alpha.4]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.3...v0.7.0-alpha.4
[0.7.0-alpha.3]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.2...v0.7.0-alpha.3
[0.7.0-alpha.2]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.6.0-beta.11...v0.7.0-alpha.2
[0.6.0-beta.11]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.6.0-beta.7...v0.6.0-beta.11
[0.6.0-beta.7]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.6.0-beta.4...v0.6.0-beta.7
[0.6.0-beta.4]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.6.0-beta.1...v0.6.0-beta.4
[0.6.0-beta.1]: https://github.com/DOIT-Ben/Reflex-Next/releases/tag/v0.6.0-beta.1
