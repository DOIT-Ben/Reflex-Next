# Reflex Next 插件与历史资源浸泡基线

更新时间：2026-07-14
对应任务：`P3-003`

## 1. 负载范围

`tools/soak_plugin_history.py` 在单个本地 Python 进程中通过 Runtime `CapabilityRegistry` 交错执行真实插件操作：

- Batch Runner：`parse`；
- History SQLite：`save`、`list`、`detail`、`rate`、`export`。

默认计划为预热 100 次、正式 1,000 次、每 100 次采样。工具使用临时历史目录和固定假数据，不读取 Provider 凭据，不联网，不在报告中保留正文、记录 ID、数据库路径或密钥。

## 2. 指标与阈值

Windows 资源采样器 `tools/windows_resource_probe.py` 只使用标准库和 `ctypes`，按 PID 读取：

- Private Bytes；
- Working Set；
- 句柄数；
- OS 线程数。

History 仓储同时记录 SQLite 打开次数、当前活动连接、峰值活动连接、数据库大小和 WAL 大小。

固定阈值：

| 指标 | 阈值 |
|---|---:|
| 最终 Private Bytes 增量 | 不超过基线 20% 或 50 MiB，取更严格者 |
| 检查点句柄增量 | `<= 16` |
| 最终句柄增量 | `<= 8` |
| 检查点线程增量 | `<= 1` |
| 最终线程增量 | `0` |
| 检查点/最终 SQLite 活动连接 | `0` |
| SQLite 峰值活动连接 | `<= 4` |

## 3. 连续三轮正式结果

三轮使用完全相同的参数连续执行，不挑选最好结果：

```powershell
uv run --frozen --project plugins\history-sqlite --extra dev python tools\soak_plugin_history.py `
  --iterations 1000 `
  --warmup-iterations 100 `
  --sample-every 100 `
  --json-output <report.json>
```

| 指标 | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| 结论 | 通过 | 通过 | 通过 |
| Private Bytes 增量 | 454,656 B | 319,488 B | 454,656 B |
| Working Set 增量 | 958,464 B | 720,896 B | 933,888 B |
| 句柄增量 | 0 | 0 | 0 |
| 线程增量 | 0 | 0 | 0 |
| SQLite 打开次数增量 | 1,252 | 1,252 | 1,252 |
| 最终活动连接 | 0 | 0 | 0 |
| 峰值活动连接 | 1 | 1 | 1 |
| 数据库大小 | 114,688 B | 114,688 B | 114,688 B |
| WAL 大小 | 0 B | 0 B | 0 B |
| 资源检查点 | 10 | 10 | 10 |

三轮均未观察到持续句柄增长、线程残留、SQLite 连接泄漏或 WAL 残留。

## 4. 自动门禁

统一后端验证新增：

- `tools:plugin-history-soak-contract`：资源采样器和混合浸泡共 40 项契约；
- `tools:plugin-history-soak-smoke`：预热 20 次、正式 100 次、每 20 次采样的真实短烟测。

本机统一门禁结果：

- 混合短烟测 Private Bytes `+90,112 B`；
- Working Set `+172,032 B`；
- 句柄 `+0`、线程 `+0`；
- SQLite 最终活动连接 `0`、峰值 `1`；
- 数据库 `65,536 B`、WAL `0 B`；
- Python 9 包 681 项、Rust 184 项加 3 项默认忽略以及全部既有安全、依赖、SBOM 门禁通过。

## 5. 边界

本基线证明 Batch Runner 与 History SQLite 在 1,000 次混合调用下达到当前资源预算，不替代：

- `P3-002` 的 72 小时 Runtime 请求/取消持续运行；
- `P3-007` 的语义模型加载、下载、删除 single-flight 与互斥；
- `P3-008` 的 1 万条历史保存、分页、搜索、导出和保留策略基准。
