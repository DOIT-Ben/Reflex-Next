# Reflex Next alpha.8 Windows 发布与生命周期验证

验证日期：2026-07-15
验证提交：`8310736`
验证版本：`0.7.0-alpha.8`
验证环境：Windows 11 `10.0.26200`，x64，PowerShell 5.1

## 1. 干净构建

验证副本来自最新提交的干净克隆：

```text
C:\Users\DOIT\AppData\Local\Temp\reflex-next-clean-alpha8-final-20260715041345
```

副本内部临时创建 `v0.7.0-alpha.8` 标签后执行：

```powershell
uv sync --frozen --extra dev --extra builtins --project packages\reflex-runtime
cd apps\tauri-host
npm ci --no-audit --no-fund
npm run runtime:build
cd src-tauri
cargo build --locked
cd ..
npm run tauri:build
```

结果：全部退出码为 `0`。Vite 生产构建、Rust release 构建、Runtime 单文件构建和 NSIS 安装包均成功。

## 2. 发布物

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `Reflex.exe` | 14,746,624 | `5cc4206e39abaa9258d120b3d75a5018a381e23bf701b22d964784e4f85a18fe` |
| `runtime\reflex-runtime.exe` | 18,671,960 | `4fe817a7a8a15411f11b19b06edefd3cb653f13702c008a086ba941097c6069b` |
| `Reflex_0.7.0-alpha.8_x64-setup.exe` | 21,784,857 | `4df9d954764586cfa09220e553581cad104889f867d0f233f1823d9adfbd6054` |

发布物版本检查：

- `VERSION`、Tauri、Cargo、npm、Python 清单和锁文件一致；
- `check_version_consistency.ps1 -RequireTag` 通过；
- `scan_release_secrets.ps1` 扫描三件发布物和受版本控制文件，0 命中；
- `generate_release_sbom.ps1 -Verify` 通过，生成并验证 11 个 CycloneDX 组件清单，扫描 3 个发布路径。

## 3. 隔离生命周期

验证安装目录：

```text
C:\Users\DOIT\AppData\Local\Temp\reflex-lifecycle-alpha8-20260715043146\install
```

可重复验证命令：

```powershell
.\tools\verify_windows_lifecycle.ps1 `
  -InstallerPath "<alpha8-installer>" `
  -KeepWorkRoot
```

本次脚本实跑结果：7 个阶段全部通过，退出码 `0`。脚本契约检查
`tools\tests\verify_windows_lifecycle_contract.ps1` 同时通过。

验证结果：

1. 首次静默安装：`/S /D=<install>`，退出码 `0`；`Reflex.exe`、`runtime\reflex-runtime.exe`、`uninstall.exe` 均存在。
2. 发布版 Sidecar：发送 `ping` 和 `shutdown` NDJSON，进程退出码 `0`，收到 2 个对应终态事件，stderr 为空。
3. 发布版 Host 启动：隔离环境启动后保持运行 6 秒；关闭请求后应用仍保持托盘/窗口进程，脚本只终止本次验证创建的进程，安装目录下无 Sidecar 残留。
4. 同版本覆盖安装：退出码 `0`，产品文件和卸载器恢复；安装目录中的未知哨兵文件保持不变。
5. 卸载：退出码 `0`，产品文件和卸载器全部移除；未知用户文件按 NSIS 保留策略保留，随后已单独清理测试哨兵。
6. 重装：退出码 `0`，三个预期产品文件重新出现。
7. 最终卸载：退出码 `0`，安装目录剩余文件数为 `0`，HKCU 卸载项匹配数为 `0`，验证目录下无发布版进程。

验证期间机器上已有仓库开发态 `target\debug\Reflex.exe`，未被终止或修改；生命周期检查只操作隔离安装目录创建的进程。

## 4. 尚未覆盖

- 本记录覆盖首次安装、同版本覆盖安装、卸载和重装，不等同于跨版本升级兼容验证；
- 配置/历史迁移夹具仍属于 P4-004；
- 代码签名、更新包和真实回滚演练仍属于 P4-005；
- 真实 Provider 流式请求与取消仍需要新凭据门禁，不在本次离线发布包验证中完成。

结论：alpha.8 在当前 Windows 11 实机上的 P4-002/P4-003 验证项通过；Windows 10 同等级证据尚缺，因此两项仍保持待验证，项目也不是 `v1.0.0` 正式发布状态。
