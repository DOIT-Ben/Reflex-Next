# alpha.8 当前提交构建物与 SBOM 复核

验证日期：2026-07-15  
验证基线：`4576e5f`  
版本：`0.7.0-alpha.8`  
平台：Windows 11 x64

## 本机证据

| 检查 | 命令 | 结果 |
|---|---|---|
| 12 组件 SBOM 生成与校验 | `powershell -NoProfile -ExecutionPolicy Bypass -File tools\generate_release_sbom.ps1 -Verify` | 通过；12 个 CycloneDX 1.5 组件，0 个额外发布路径 |
| 前端生产构建物扫描 | `powershell -NoProfile -ExecutionPolicy Bypass -File tools\scan_release_secrets.ps1 -RepositoryRoot . -SkipTrackedFiles -ReleasePath apps\tauri-host\dist` | 通过；无敏感信息命中 |
| 敏感扫描契约 | `powershell -NoProfile -ExecutionPolicy Bypass -File tools\tests\scan_release_secrets_contract.ps1` | 通过 |
| SBOM 契约 | `powershell -NoProfile -ExecutionPolicy Bypass -File tools\tests\generate_release_sbom_contract.ps1` | 通过 |
| 统一验证脚本契约 | `powershell -NoProfile -ExecutionPolicy Bypass -File tools\tests\verify_backend_contract.ps1` | 通过 |

## 门禁判断

`.github\workflows\backend-ci.yml` 已包含前端生产构建、构建物扫描、12 组件 SBOM 生成和 Artifact 上传步骤。当前本机证据证明这些脚本在 `4576e5f` 工作树上可运行，但本次提交对应的远端 Windows CI Artifact 尚未取得可核验记录，因此 `P2-006` 继续保持“待验证”。

本记录不替代正式发布候选物料验证，也不改变签名、标签、Windows 10、更新和回滚门禁状态。
