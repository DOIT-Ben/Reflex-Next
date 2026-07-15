# alpha.8 当前提交构建物与 SBOM 复核

验证日期：2026-07-15

验证基线：`cf455306dade9e01c6414326ac4de64ed861903b`

版本：`0.7.0-alpha.8`

平台：Windows 11 x64

## 来源隔离

验证在 detached 干净工作树执行，`git status --porcelain` 为空。主工作区已有的
`config_store.rs` 用户修改未进入构建、扫描或 SBOM 证据。

## 本机证据

| 检查 | 结果 |
|---|---|
| `npm ci` | 安装 70 个包，审计 71 个包，0 个漏洞 |
| 前端测试 | 26 个文件、168 项通过，最大 2 workers |
| Vite 生产构建 | 242 个模块，生成 6 个文件、357,528 B |
| 前端构建物敏感扫描 | 通过，0 个命中 |
| 受版本控制文件敏感扫描 | 通过，0 个命中 |
| 敏感扫描契约 | 通过 |
| SBOM 契约 | 通过 |
| 统一验证脚本契约 | 通过 |
| 版本一致性 | 14 个版本来源统一为 `0.7.0-alpha.8` |
| 12 组件 SBOM 生成与校验 | 通过，12 份 CycloneDX 1.5 BOM 和 1 份清单 |

SBOM 清单 SHA-256：

```text
e97b72303c594066c343c32197db54ba3ba6d65dad8ec4d5bfea1a86d5c360fe
```

独立复核重新计算了 12 份 BOM、12 个源锁文件和清单记录的 SHA-256，并重新解析
CycloneDX schema；错误数为 0。SBOM 生成器同时对 SBOM 目录和前端 `dist` 执行了
二次敏感信息扫描。

## 远端 CI

手动触发 Windows CI Run `29422634887`，Run 精确绑定上述 `cf45530`：

- Job：`87376766567`；
- Runner ID：`0`，未分配 Runner；
- 执行步骤：`0`；
- Artifact：`0`；
- GitHub 注解：账户近期付款失败或 Actions spending limit 需要提高。

该失败发生在代码检出和任何项目命令之前，不是测试、构建、扫描或 SBOM 失败。由于
GitHub 没有启动 Runner，当前提交仍无法取得 CI 上传的 SBOM Artifact。

## 门禁判断

`cf45530` 的本机供应链复核全部通过，但 `P2-006` 仍保持“阻塞”，不能在缺少远端
Artifact 时标记完成。恢复 GitHub Actions 计费后，应重新运行同一 workflow，并下载
核对 `reflex-next-sbom-<commit>` Artifact 后关闭任务。

本记录不替代正式发布候选物料验证，也不改变签名、标签、Windows 10、更新和回滚门禁。
