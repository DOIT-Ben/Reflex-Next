# Reflex 升级与恢复指南

本指南适用于 Windows 桌面版 Reflex。升级、回滚或恢复数据前，请先从托盘菜单退出 Reflex，
并在任务管理器中确认 `Reflex.exe` 和 `reflex-runtime.exe` 已结束。

## 1. 验证安装包

发布目录包含 `SHA256SUMS.txt` 和 `release-manifest.json`。安装前在发布目录运行：

```powershell
Get-FileHash .\artifacts\Reflex_*_x64-setup.exe -Algorithm SHA256
```

结果应与 `SHA256SUMS.txt` 中对应文件完全一致。哈希不一致、来源不明或签名状态不符合
发布说明时，不要运行安装包。

## 2. 升级前备份

Reflex 的本地配置和历史通常位于：

```text
%APPDATA%\com.reflex.next
```

退出应用后，可在 PowerShell 中备份整个目录：

```powershell
$source = Join-Path $env:APPDATA "com.reflex.next"
$backup = Join-Path $env:USERPROFILE ("Documents\Reflex-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
Copy-Item -LiteralPath $source -Destination $backup -Recurse
```

备份应至少包含以下已有文件：

- `config.json` 和 `config.json.bak`；
- `history\history.sqlite3`；
- `history\history.sqlite3.migration-v*.bak`；
- 需要保留的本地诊断和历史备份目录。

Provider 密钥保存在 Windows 凭据管理器中，不会进入上述目录备份，也不应导出到文本文件。

## 3. 正常升级

1. 完成数据目录备份。
2. 运行新版本安装包并保留默认安装目录。
3. 启动 Reflex，确认设置、Provider 状态和历史列表可读取。
4. 执行一次短文本优化，确认结果可以生成、取消和保存。
5. 在确认新版本稳定前，不要删除升级前备份。

## 4. 回滚

只有来源和哈希均已验证的上一版本安装包可以用于回滚。

1. 退出 Reflex，并再次备份当前数据目录。
2. 通过 Windows“已安装的应用”卸载当前版本。
3. 安装上一版本。
4. 首次启动前，恢复升级前保存的完整数据目录。
5. 启动后检查设置和历史；Provider 密钥状态异常时在设置页重新录入，不要从文本备份恢复密钥。

不要让旧版本直接写入已被新版本迁移、但没有兼容证据的历史库。若没有升级前完整备份，
应保留当前数据目录并停止回滚，避免覆盖仍可恢复的数据。

## 5. 历史恢复

历史迁移会在数据库旁保留类似以下文件：

```text
history.sqlite3.migration-v1.bak
```

优先恢复升级前保存的完整数据目录。只有在确认备份版本、密钥版本和目标应用兼容后，
才可将迁移备份复制为 `history.sqlite3`。恢复前必须退出 Reflex，并把当前数据库、
`history.sqlite3-wal` 和 `history.sqlite3-shm` 一并移到独立保留目录，不要直接覆盖或删除。

## 6. 恢复失败

如果应用无法启动、历史无法读取或反复提示配置恢复：

1. 停止继续写入或重复安装。
2. 保留当前数据目录、升级前备份和安装包校验信息。
3. 从应用导出脱敏诊断包；诊断包不应包含 Provider 密钥或完整正文。
4. 提交问题时说明 Windows 版本、Reflex 版本和错误页面中的诊断编号。

在数据恢复完成前，不要清理 Windows 凭据管理器、历史数据库或迁移备份。
