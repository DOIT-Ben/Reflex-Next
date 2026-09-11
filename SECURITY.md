# 安全策略

## 支持的版本

| 版本 | 支持情况 |
|---|---|
| 0.7.0-alpha.x | ✅ 安全修复 |
| 0.6.0-beta.x | ❌ 仅重大问题回溯 |

## 如何报告漏洞

**不要通过公开 Issue 报告安全问题。**

请使用 GitHub 的"私密漏洞报告"（Security Advisories → Report a vulnerability），
或在无法使用时通过仓库主页联系方式私下联系维护者。

请在报告中包含：

- 受影响组件（reflex-core / reflex-runtime / tauri-host / reflex-cloud / 具体插件）；
- 复现步骤或 PoC；
- 影响评估与可能含有的前提条件。

维护者会在 7 天内确认收到，并在修复发布前对报告内容保密。

## 密钥与数据处理边界（设计承诺）

- Provider API Key 通过 Windows Credential Manager 存储，不落明文配置文件；
- Provider 错误、日志、诊断与反馈数据在出口处统一脱敏；
- Cloud 上传（反馈/截图/诊断）遵守分项授权，用户可随时请求删除数据；
- 仓库内置 `tools/scan_release_secrets.ps1`，发布前对产物做密钥扫描；
  历史与测试中的形如 `sk-...` / `AKIA...` 的字符串均为 fixture 假密钥。

## 范围外

- 用户本机被物理接触或已植入恶意软件的场景；
- 用户主动将 API Key 粘贴到模板/输入内容中导致的泄漏（产品已有脱敏缓解，但无法完全防御）；
- 未按文档部署 `services/reflex-cloud` 造成的服务端暴露。
