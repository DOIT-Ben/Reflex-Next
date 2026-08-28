# Reflex Next 本地 HTTP 宿主（SSE）验证记录

更新时间：2026-08-28

## 1. 目的

`packages/reflex-http-host` 把本地 Runtime sidecar 以 HTTP 服务形态暴露：本地应用/脚本可通过
`POST /v1/optimize` 发起流式优化并消费 SSE 事件流，支持按 `request_id` 取消、Provider 目录查询、
健康检查与可选 Bearer 鉴权。形态与 Tauri 宿主同构（网关进程消费同一套 NDJSON 协议），
**零侵入** Core/Runtime——不修改任何现有包代码。

## 2. 形态与端点

- `POST /v1/optimize`：JSON 请求（`text` 必填；`style/mode/scene/scene_policy/stream/provider/model/metadata` 可选；
  `request_id` 可选，客户端可自选以支持确定性取消），响应 `text/event-stream`，事件信封与
  sidecar 协议一致（`status/scene/request/chunk/done/metric/error` 及 runtime 专属信封）；
  连接断开自动发送 `cancel`；单请求 120 秒超时（`REFLEX_HTTP_REQUEST_TIMEOUT` 可配）。

场景分层（2026-08-14 起，模板包 `template-packs/builtin`）：

- `scene` 支持一级分类与二级子场景，冒号形式：`"business:email"`（大类:子场景）、
  `"business"`（仅大类，使用分类默认模板）、`"email"`（旧形式，自动归类）；
- 十大一级分类：business 商务沟通 / marketing 营销文案 / market_analysis 市场分析 /
  tech_doc 技术文档 / code 代码工程 / diagnosis 问题诊断 / academic 学术研究 /
  education 学习教育 / creative 创意写作 / translation 翻译本地化；
- 49 个场景中有 42 个二级子场景映射到十大分类；`scene_policy: manual` 时使用手动指定场景，
  `auto`（默认）时由内置规则检测器自动识别并输出 `category` 元数据；
- `scene` 事件新增 `category` 字段（附加字段，旧客户端可忽略）；场景处理按策略区分：
  `manual`/`ask` 提供未知场景时返回 422，`auto` 时忽略手动场景并交给检测器，只有自动检测失败才回退 `general`。
- `POST /v1/requests/{request_id}/cancel`：发送取消命令。
- `POST /v1/ping`、`GET /v1/providers`、`GET /v1/health`。
- `GET /v1/scenes`：场景库目录（10 个一级分类分组 + 49 个场景清单 + 未分类项），
  客户端可据此构建场景选择 UI；模板包路径可用 `REFLEX_TEMPLATE_PACK_ROOT` 覆盖。
- 默认绑定 `127.0.0.1:8790`；`REFLEX_HTTP_TOKEN` 非空时所有端点要求 `Authorization: Bearer <token>`。
  绑定到非 loopback 地址时必须配置 Token，否则宿主拒绝启动。
- 子进程环境为白名单（不继承 Provider 凭据），默认关闭开发 Mock；仅显式设置
  `REFLEX_RUNTIME_DEVELOPMENT=1` 才启用。

启动：

```powershell
cd packages\reflex-http-host
uv run --frozen reflex-http-host
```

## 3. 契约测试证据

- 包内测试 `packages/reflex-http-host/tests/`：44 项，覆盖 SidecarGateway 路由/终态判定/关闭链/
  凭据不继承，FastAPI 端点/SSE 帧/取消/超时/鉴权，以及 4 项真实子进程集成测试
  （ping/providers/完整事件序列/未配置 Provider 错误）。
- 压力工具契约 `tools/tests/test_http_soak_backend.py`：17 项，覆盖完成/取消计数、busy 计数、
  串线检测、缺终态检测、取消缺失判定、http_error 单次重试、限值拒绝、报告无正文。
- 当前包级命令：`uv run --frozen --project packages\reflex-http-host --extra dev pytest packages\reflex-http-host\tests -q`
- 当前结果（2026-08-28）：`44 passed, 1 warning`。
- 压力工具契约仍为历史独立门禁：`tools/tests/test_http_soak_backend.py` 17 项；当前包级测试与压力工具契约分开统计，不再使用历史合并命令的 `40 passed` 作为结果。
- 统一门禁：`verify_backend.ps1 -PythonProject reflex-http-host` → `Backend verification passed.`；
  `check_version_consistency.ps1` 通过（0.7.0-alpha.8）。

## 4. 分级并发压力证据

命令（服务运行中）：

```powershell
uv run --frozen --project packages\reflex-http-host --extra dev python tools/http_soak_backend.py `
  --levels "1,4,16,32" --iterations 20 --cancel-every 4 --timeout-seconds 15 `
  --json-output workbench\http-soak-graded-20260814-0400.json
```

报告 `workbench/http-soak-graded-20260814-0400.json`，`passed=true`：

| 并发 | 完成 | 取消 | busy | 重试 | 串线 | 缺终态 | P50 (ms) | P95 (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 15 | 5 | 0 | 0 | 0 | 0 | 80.5 | 1002.8 |
| 4 | 15 | 5 | 0 | 0 | 0 | 0 | 90.1 | 883.6 |
| 16 | 15 | 5 | 0 | 5 | 0 | 0 | 275.8 | 982.1 |
| 32 | 15 | 5 | 0 | 0 | 0 | 0 | 757.6 | 1488.4 |

说明：

- 每档 20 次请求，每 4 次发起一次取消（mock 延迟夹具 400ms），取消全部命中
  （`status/cancelled` 终态），无串线、无缺终态、无失败；
- 连接级偶发抖动（ReadTimeout）通过工具的单次重试消化（conc=16 档 5 次），重试后全部成功；
- Runtime sidecar 容量上限（4 活跃 optimize + 32 排队）是 HTTP 并发承诺的硬边界，超限由
  `runtime_busy` 稳定错误语义表达（工具按 busy 计数而非失败）。

## 5. 边界与后续

- 2026-08-28 回归：HTTP Host 的命令订阅已统一为“先订阅、后发送”，并新增非 loopback 无 Token 拒绝、显式开发 Mock 和快速响应回归；当前实现仍需与 Rust Host 做完整事件/取消/超时等价性发布验证。

- 本形态未改变 P3-002 等现有门禁状态；7 天正式浸泡继续按文档配置运行；
- 后续方向：WebSocket 通道、并发参数化（`max_active_optimize` 可配置）、远程部署适配层。
