# Reflex Next Runtime 请求/取消浸泡基线

更新时间：2026-07-14

## 1. 目的

`tools/soak_backend.py` 在单个本地 Runtime 进程中持续交错执行 Mock 优化与取消，用于发现：

- 请求串线或错误路由；
- 取消后迟到 `chunk` / `done`；
- 请求缺少唯一终态或终态顺序异常；
- 协议队列失控、Runtime 死锁或提前退出；
- 浸泡结束后 Runtime 无法安全退出。

工具只启用开发模式内置 Mock，不读取或继承 Provider 凭据，不把请求正文、分片正文、请求 ID 或异常详情写入报告。

## 2. 当前 10,000 次证据

执行命令：

```powershell
uv run --frozen --project packages\reflex-runtime --extra dev python tools\soak_backend.py `
  --iterations 10000 `
  --batch-size 4 `
  --timeout-seconds 5 `
  --cancel-every 2 `
  --json-output <report.json>
```

2026-07-14 本机结果：

| 指标 | 结果 |
|---|---:|
| 总迭代 | 10,000 |
| 正常完成 | 5,000 |
| 主动取消 | 5,000 |
| 协议事件 | 65,002 |
| 协议队列峰值 | 8 |
| 最终观察窗口迟到事件 | 0 |
| 耗时 | 64.672 秒 |
| 安全退出 | 是 |
| 失败类别 | 无 |

本轮证明 10,000 次次数门禁通过，未观察到死锁、请求串线、取消后迟到有效事件或残留 Runtime 进程。

## 3. CI 短门禁

统一后端验证执行 100 次短浸泡：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\verify_backend.ps1
```

短门禁固定使用 4 并发、完成/取消各半，并执行 500 ms 最终观察。它用于发现确定性回归，不替代发布前长时间浸泡。

## 4. 72 小时正式门禁

正式候选版本使用以下受控速率运行：

```powershell
uv run --frozen --project packages\reflex-runtime --extra dev python tools\soak_backend.py `
  --iterations 10000 `
  --duration-hours 72 `
  --rate-per-minute 3 `
  --batch-size 4 `
  --timeout-seconds 5 `
  --cancel-every 2 `
  --json-output <report.json>
```

只有 72 小时报告也满足以下条件，`P3-002` 才能关闭：

- 运行时间不少于 72 小时且总迭代不少于 10,000；
- 正常完成与主动取消均大于 0；
- 没有请求串线、迟到终态、未知请求事件或批次超时；
- 最终观察窗口无迟到事件；
- Runtime 安全退出且无残留进程。

当前尚未执行 72 小时正式门禁，因此阶段 3 长期运行门禁仍为进行中。
