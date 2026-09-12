# Reflex Next Runtime 请求/取消浸泡（历史证据；当前门禁状态 2026-08-28）

更新时间：2026-08-28

> 历史证据提示：本文记录的长时间浸泡结果来自旧工作树，不代表当前工作树已完成正式 72 小时发布门禁。

## 1. 目的

`tools/soak_backend.py` 在单个本地 Runtime 进程中持续交错执行 Mock 优化与取消，用于发现：

- 请求串线或错误路由；
- 取消后迟到 `chunk` / `done`；
- 请求缺少唯一终态或终态顺序异常；
- 协议队列失控、Runtime 死锁或提前退出；
- 浸泡结束后 Runtime 无法安全退出。

工具只启用开发模式内置 Mock，不读取或继承 Provider 凭据，不把请求正文、分片正文、请求 ID 或异常详情写入报告。
运行时报告采用原子替换写入：启动后立即写出 `status=running`，每批次更新最近心跳，结束时写出
`status=passed` 或 `status=failed`。状态报告要求严格的固定字段、有限数值、UTC 时间、终态一致性，
并记录 Windows 进程创建时间用于 PID 复用校验。可使用 `--status <report.json>` 读取最近一次状态；报告停在
`running` 通常表示进程被中断或机器掉电，不能视为通过。

## 2. 历史 10,000 次证据

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

## 3. 手动 heavy 短门禁（历史流程说明）

统一后端验证中的 100 次实时短浸泡属于 `heavy` 步骤：默认 push/PR 只执行浸泡工具契约，
手动触发 workflow 并设置 `run_heavy=true` 时才执行实时短浸泡；本地不带 `-SkipHeavy` 也会执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\verify_backend.ps1
```

短门禁固定使用 4 并发、完成/取消各半、单批次超时 15 秒，并执行 500 ms 最终观察。
它用于发现确定性回归，不替代发布前长时间浸泡；放宽单批次超时是为了避免受限 CI 主机把调度抖动误报为 Runtime 协议失败。

### 当前工作树复验（2026-08-28，非历史基线）

当前工作树的独立短浸泡结果：100 次迭代，完成 50 次、取消 50 次，650 个协议事件，队列峰值 5，
安全退出，耗时约 7.3 秒；报告为 `status=passed`。该报告是本地运行产物，不提交到版本库。

### 当前工作树正式门禁状态

当前工作树的 72 小时门禁需单独启动并持续观察；在报告写出 `status=passed` 前，不得将其计为通过。
状态读取命令：

```powershell
uv run --frozen --project packages\reflex-runtime --extra dev python tools\soak_backend.py `
  --status <soak-report>.json
```

 soak 报告为本机运行产物，不入库。

状态工具同时检查报告版本、固定字段和值、Runtime 进程存活、进程创建时间、最近心跳和时钟偏移；
进程仍存在但心跳过期、PID 身份不匹配或报告时间异常时报告为 stale。

## 4. 72 小时正式门禁

当前正式发布门禁的唯一目标时长是 72 小时；工作台中出现的 `168h` 报告属于此前的
探索性长跑记录，不改变当前目标，也不能替代本节的 72 小时报告。

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

### 历史失败记录

以下记录均来自旧工作树，且早于当前严格状态报告 schema；它们用于解释 P3-002 为什么仍开放，
不能用当前 `--status` 命令重新验证：

| 日期 | 迭代 | 结果 | 失败类别 |
|---|---:|---|---|
| 2026-07-15 | 824 | 完成 412、取消 412，Runtime 安全退出 | `completed_instead_of_cancelled` |
| 2026-08-17 | 2,920 | 完成 1,460、取消 1,460 | `completed_instead_of_cancelled` |
| 2026-08-18 | 76 | 完成 38、取消 38 | `completed_instead_of_cancelled` |
| 2026-08-18 | 0 | 未完成首批 | `batch_timeout` |
| 2026-08-18 | 0 | 未完成首批 | `batch_timeout` |

2026-08-17 的记录约运行 16.22 小时，仍未达到 10,000 次和 168 小时双门槛；其余记录更早结束，
均不能作为通过证据。取消夹具随后将首个 chunk 后的处理窗口从 10ms 调整为 100ms，仍坚持首个
`chunk` 后发送取消，并继续严格拒绝取消后的迟到 `chunk` / `done`，没有放宽终态断言。

修复提交：`185d723`

修复后 2,000 次有界复验通过：完成 1,000 次、取消 1,000 次、13,000 个协议事件、
最终观察窗口迟到事件 0、Runtime 安全退出。正式 72 小时门禁仍需重新运行，因此 P3-002
保持进行中。
