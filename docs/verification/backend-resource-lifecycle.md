# Reflex Next 后端资源生命周期基线

更新时间：2026-07-14
对应任务：`P3-004`

## 1. Runtime 任务边界

Runtime 的 Optimize 与插件调用共用一个固定调度器：

| 资源 | 默认上限 | 超限行为 |
|---|---:|---|
| 活动 worker | 4 | 不再创建线程 |
| FIFO 等待队列 | 32 | 返回 `runtime_busy` |
| 总接纳任务 | 36 | 第 37 个任务稳定拒绝 |

等待任务不会创建阻塞线程。等待中的取消会从队列移除任务、释放请求 ID 并产生唯一取消终态；关闭会原子禁止新提交、取消活动任务、清空等待队列并等待固定 worker 退出。任务函数或取消回调异常不能杀死 worker 或跳过注册表清理。

## 2. 插件调用边界

插件调用在共享调度器之外增加固定隔离执行层，避免不合作插件占住 Runtime worker：

| 资源 | 默认上限 | 稳定错误码 |
|---|---:|---|
| 插件执行线程 | 4 | `plugin_busy` |
| 单调用总时限 | 120 秒 | `plugin_timeout` |
| 单调用流事件 | 50,000 | `plugin_event_limit` |
| 单调用累计 UTF-8 JSON 输出 | 2 MiB | `plugin_output_too_large` |
| 已预算事件缓冲 | 64 | 取消执行并释放调用方 |

预算错误、用户取消、插件错误和正常结果只允许一个终态。完全忽略取消的可信插件到期后，调用方仍立即得到 `plugin_timeout` 并释放 Runtime worker；对应隔离线程最多占用固定 4 个槽，后续调用返回 `plugin_busy`，不会继续创建线程。线程在插件返回或 Runtime 进程结束时释放。`v1.0` 不开放不受信任第三方插件安装，因此进程重启仍是顽固插件的最终恢复边界。

## 3. Host 路由与会话边界

- Host 最多维护 64 个活动请求路由，第 65 个请求在写入 Sidecar 前返回安全忙碌错误；
- 每个私有调用最多缓冲 64 个普通事件，并保留第 65 个槽用于唯一安全终态；慢消费者溢出后路由立即终止并清理；
- Host 对 stdout 单行继续保持 8 MiB 上限，Provider 目录继续保持 2 MiB 上限；
- 防重放历史每个 Runtime 会话最多记录 100,000 个请求 ID，不再滚动淘汰后复用旧 ID；
- 防重放窗口耗尽时，有活动路由则拒绝轮转；活动路由归零后，Host 先停止旧 Runtime、等待 stdout/stderr reader，再清空历史并启动新会话；
- 普通崩溃重启和控制器重建不会清空防重放历史，只有上述完整停止后的安全会话轮转可以清空；
- stdout/stderr reader 持有完成信号和 JoinHandle，正常关闭、重启和异常恢复路径均执行有界等待。

## 4. 历史连接证据

History SQLite 测试对真实 `_open_connection` 增加只读计数代理，不向生产实现加入测试钩子。覆盖：

- 重复 list、detail、rate 后 `opened == closed`、`active == 0`；
- 写锁等待期间可观察到活动写连接，取消后活动连接回到 0；
- 仓储内部异常、导出超限和导出中途取消后连接回到 0；
- JSON、CSV、Markdown 重复导出后所有连接关闭。

## 5. 验证证据

本机定向与统一门禁：

```powershell
uv run --frozen --project packages\reflex-runtime --extra dev pytest packages\reflex-runtime\tests -q
# 309 passed

uv run --frozen --project plugins\history-sqlite --extra dev pytest plugins\history-sqlite\tests -q
# 133 passed

Set-Location apps\tauri-host\src-tauri
cargo test -- --test-threads=2
# 184 passed, 3 ignored

Set-Location ..\..\..
.\tools\verify_backend.ps1 -SkipFrontend
# Backend verification passed
```

统一门禁实际结果：

- Python 9 包共 681 项通过；
- Rust Host 184 项通过，3 项 Credential Manager 实机测试按常规门禁忽略；
- Provider 冒烟 8 项加 2 个子用例、性能工具 9 项、浸泡工具 14 项通过；
- 100 次 Runtime 短浸泡完成/取消各 50 次，无迟到事件并安全退出；
- 依赖审计、源码敏感扫描和 11 组件 SBOM 通过。

远端独立复现：GitHub Actions Backend CI Run `29300400632`，结论 `success`，完成统一门禁、前端构建、构建物扫描、SBOM 生成与上传。

## 6. 后续任务

本基线关闭线程、队列、请求 ID、插件流和 Host 私有缓冲的有界性审查，不替代：

- `P3-003` 的 1,000 次插件/历史混合资源浸泡和 Windows Private Bytes、句柄、线程基线；
- `P3-002` 的 72 小时持续运行门禁；
- `P3-007` 的语义模型 single-flight 与下载、加载、删除互斥。
