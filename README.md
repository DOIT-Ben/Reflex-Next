# Reflex Next

Reflex Next 是 Reflex 的轻量化重做项目。

目标不是继续维护 PyQt 大工作台，而是把提示词优化能力抽成可嵌入、可插件化的本地运行时：

```text
Python Core + Tauri 轻量桌面宿主 + Python 插件系统
```

## 当前定位

- 旧版参考实现：`D:\Desktop\AI\11_Products\prod\Reflex`
- 新版项目位置：`D:\Desktop\AI\11_Products\lab\Reflex-Next`
- 当前能力：Core、Runtime Sidecar、MiniMax Provider、内置模板包和 Tauri 小宿主已打通；桌面端支持单实例、托盘、全局快捷键、窗口恢复和剪贴板策略
- 当前产品切片：支持内容优化与提示词生成、四种主风格、42 个场景的自动或手动选择，以及中英文模板输出
- 当前边界：离线主链、设置持久化和安全存储已验证；真实 MiniMax 网络请求仍需在应用中手动配置密钥后执行

## 核心原则

- Core 不依赖 PyQt、Tauri、SQLite、torch 或 sentence-transformers。
- 桌面宿主只负责托盘、快捷键、剪贴板、小浮窗和设置入口。
- Provider、模板包、语义识别、历史、翻译、批处理全部插件化。
- 语义场景自动识别进入核心体验，但重模型实现必须懒加载、可关闭、可替换。
- 旧 Reflex 只作为行为基线和资产来源，不把旧工作台结构迁入新项目。

## 目录结构

```text
apps/
  tauri-host/                 # Tauri 轻量桌面宿主
packages/
  reflex-core/                # 无 UI Python 核心
  reflex-runtime/             # Python Sidecar 与 Mock Runtime
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

## 用户文档

- [隐私说明](docs/PRIVACY.md)
- [支持范围](docs/SUPPORT.md)
- [故障处理](docs/TROUBLESHOOTING.md)
- [第三方软件声明](docs/THIRD-PARTY-NOTICES.md)
- [发布恢复指南](docs/RELEASE-RECOVERY.md)

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

以下增强能力不回填主浮窗，将通过独立插件或工作视图接入：

- 大工作台
- 历史管理
- 批处理
- Markdown 预览
- 按需加载的本地语义模型
- 主题与国际化设置

## 开发入口

当前已有可验证的 Core、Runtime、MiniMax Provider、前端和 Rust Host。

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

桌面开发入口：

```powershell
cd apps\tauri-host
npm run tauri:dev
```

密钥只通过应用设置页写入系统安全存储，不放入环境变量、配置文件、终端命令、日志或仓库。
