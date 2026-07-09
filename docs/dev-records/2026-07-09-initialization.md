# 2026-07-09 初始化记录

## 目标

创建 Reflex Next 项目，用于承接 Reflex 的轻量化重做。

## 决策

- 项目归属：`D:\Desktop\AI\11_Products\lab\Reflex-Next`
- 旧项目定位：`D:\Desktop\AI\11_Products\prod\Reflex` 作为 Classic 参考实现
- 技术路线：Python Core + Tauri 轻量宿主 + Python 插件系统
- 首版范围：Core、MiniMax Provider、内置模板包、L0 场景识别、Tauri 小浮窗

## 已创建

- `README.md`
- `AGENTS.md`
- `docs\ARCHITECTURE.md`
- `docs\MIGRATION.md`
- `docs\CLASSIC-REFERENCE.md`
- `packages\reflex-core`
- `plugins\provider-minimax`
- `plugins\semantic-detector`
- `apps\tauri-host`
- `template-packs\builtin`
- `workbench`

## 下一步

1. 在 `packages\reflex-core` 中实现事件流协议。
2. 迁移输入校验、响应清洗和脱敏策略。
3. 实现 L0 规则场景识别。
4. 实现 MiniMax Provider 插件。
