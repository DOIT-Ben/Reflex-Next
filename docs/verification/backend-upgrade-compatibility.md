# Reflex Next 配置与历史升级兼容验证

验证日期：2026-07-15
验证分支：`codex/full-feature-parity`
验证提交：`c68c528`

## 已验证

### 配置

命令：

```powershell
cd apps\tauri-host\src-tauri
cargo test config_store --locked -- --test-threads=2
```

结果：11 项通过。

覆盖内容：

- v0 `default_provider/default_model/default_mode/default_style` 到当前字段的迁移；
- v1 历史策略安全回退；
- v2 显式历史策略和插件列表保留；
- 非法配置恢复、备份恢复和敏感扩展字段拒绝；
- 配置迁移后的当前版本归一化。

### 历史数据库

命令：

```powershell
uv run --frozen --project plugins\history-sqlite --extra dev pytest plugins\history-sqlite\tests\test_repository.py -q
uv run --frozen --project plugins\history-sqlite --extra dev pytest plugins\history-sqlite\tests -q
```

结果：目标文件 26 项通过，插件全套 158 项通过。

新增旧版本夹具会创建：

- `user_version=0`；
- 旧索引布局；
- 一条真实 AES-GCM 加密历史记录；
- 旧版本迁移前备份。

验证会执行一次新记录写入触发迁移，然后确认：

- 迁移备份仍含旧记录，且保留 `user_version=0`；
- 当前库升级到 `user_version=1` 和最新索引布局；
- 旧记录仍可被当前 Runtime 解密读取；
- 既有恢复和损坏处理测试不回归。

## 尚缺验证

当前证据是数据层和宿主配置层契约测试，尚未把旧版本 `config.json`、历史数据库、安装包和新版本首次启动串成一条真实跨版本覆盖安装流程。P4-004 仍保持进行中，下一步需要：

1. 准备来自上一发布版本的隔离配置和历史目录夹具；
2. 在发布版安装/覆盖安装后启动 Host，验证配置加载、历史列表、详情和新写入；
3. 记录迁移前后文件、版本、备份和脱敏诊断结果。

结论：配置与历史的迁移契约已通过，跨版本安装实机证据尚未完成；不能据此宣布正式升级兼容。
