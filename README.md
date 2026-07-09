# Reflex Next

Reflex Next 是 Reflex 的轻量化重做项目。

目标不是继续维护 PyQt 大工作台，而是把提示词优化能力抽成可嵌入、可插件化的本地运行时：

```text
Python Core + Tauri 轻量桌面宿主 + Python 插件系统
```

## 当前定位

- 旧版参考实现：`D:\Desktop\AI\11_Products\prod\Reflex`
- 新版项目位置：`D:\Desktop\AI\11_Products\lab\Reflex-Next`
- 当前阶段：实验室重做项目，架构初始化与迁移基线
- 首个产品切片：Tauri 小浮窗调用 Python Core，通过 MiniMax Provider 流式优化提示词

## 核心原则

- Core 不依赖 PyQt、Tauri、SQLite、torch 或 sentence-transformers。
- 桌面宿主只负责托盘、快捷键、剪贴板、小浮窗和设置入口。
- Provider、模板包、语义识别、历史、翻译、批处理全部插件化。
- 语义场景自动识别进入核心体验，但重模型实现必须懒加载、可关闭、可替换。
- 旧 Reflex 只作为行为基线和资产来源，不把旧工作台结构迁入新项目。

## 目录结构

```text
apps/
  tauri-host/                 # Tauri 小宿主规划入口
packages/
  reflex-core/                # 无 UI Python 核心
plugins/
  provider-minimax/           # MiniMax Provider 插件
  semantic-detector/          # 语义场景识别插件
template-packs/
  builtin/                    # 内置模板包
docs/
  ARCHITECTURE.md             # Reflex Next 架构设计
  MIGRATION.md                # 功能迁移路线
  CLASSIC-REFERENCE.md        # 旧 Reflex 可迁移资产映射
  dev-records/                # 开发记录
workbench/
  readme.md                   # 当前状态
  known-pitfalls.md           # 已知坑点
```

## 先读文档

1. [docs\ARCHITECTURE.md](docs/ARCHITECTURE.md)
2. [docs\MIGRATION.md](docs/MIGRATION.md)
3. [docs\CLASSIC-REFERENCE.md](docs/CLASSIC-REFERENCE.md)
4. [workbench\readme.md](workbench/readme.md)

## 最小开发目标

首版只做这条链：

```text
快捷键呼出 Tauri 小浮窗
  -> 读取输入或剪贴板
  -> Reflex Core 自动识别场景
  -> 内置模板包生成模型请求
  -> MiniMax Provider 流式返回
  -> 一键复制结果
```

暂不做：

- 大工作台
- 历史管理大窗
- 批处理
- Markdown 预览
- 本地语义模型默认加载
- 复杂主题系统

## 开发入口

当前只是初始化骨架，尚未进入可运行实现阶段。

后续建议顺序：

1. 完成 `packages\reflex-core` 的事件流与优化用例。
2. 完成 `plugins\provider-minimax` 的 Provider 协议实现。
3. 完成 `template-packs\builtin` 的模板包迁移。
4. 再启动 `apps\tauri-host`。
