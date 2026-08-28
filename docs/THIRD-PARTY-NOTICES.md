# Reflex 第三方软件声明

Reflex 包含 Python、Rust 和 JavaScript 生态的第三方开源软件。本文件用于说明依赖边界，不替代各项目随包提供的原始许可证文本。

## 1. 主要技术组件

- 桌面宿主：Tauri、WebView2 相关 Rust 组件；
- 前端：Svelte、Vite、Lucide；
- Python Runtime：HTTP、配置、模板和插件运行所需组件；
- Reflex Cloud：FastAPI、SQLAlchemy、Pydantic、Uvicorn 等服务端组件；
- 发布物料：用于公开依赖信息的 CycloneDX SBOM。

## 2. 完整依赖清单

每个发布候选目录中的 `sbom` 文件夹是当前构建的完整机器可读依赖清单：

- `sbom-manifest.json` 记录由 `tools/project-registry.json` 注册的产品组件、源锁文件及 SHA-256；
- 每个 `*.cdx.json` 文件使用 CycloneDX 1.5 格式记录对应组件的依赖；
- `SHA256SUMS.txt` 用于验证 SBOM、用户文档和可执行物没有被替换。

版本、许可证表达式和传递依赖以候选包内 SBOM 及各依赖附带的许可证文件为准。

## 3. 许可证类别

当前发布仅包含经过核对的宽松或弱互惠许可证，包括：

- MIT、Apache-2.0；
- BSD-2-Clause、BSD-3-Clause、0BSD；
- ISC、Zlib、BSL-1.0；
- MPL-2.0、PSF-2.0、Unicode-3.0；
- CDLA-Permissive-2.0 及经核对的兼容组合。

未知、未分类或不符合发布政策的许可证不能静默进入候选包。

## 4. 外部服务

MiniMax、OpenAI-compatible 服务和 Reflex Cloud 上游 Provider 属于外部网络服务，不是随安装包分发的开源组件。使用这些服务时，用户还需遵守对应服务商的条款、隐私政策和计费规则。

## 5. 权利边界

第三方组件仍由各自权利人拥有。本声明不授予 Reflex 自有代码的额外许可，也不改变第三方许可证已经授予或要求的权利与义务。
