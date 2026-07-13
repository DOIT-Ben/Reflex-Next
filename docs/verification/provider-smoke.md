# Provider 脱敏冒烟验证

## 目的

`tools\provider_smoke.py` 通过正式 Runtime NDJSON 协议验证以下链路：

1. 读取可信 Provider/模型目录；
2. 执行一次流式优化；
3. 发起一次定时取消并测量取消时延。

工具不会保存请求或响应正文。输出只包含可信 Provider/模型 ID、结果分类、时延、分片数和稳定错误码。

## 凭据边界

- 真实模式只读取产品已经保存在 Windows Credential Manager 中的 Provider 凭据；
- 必须先通过产品设置页保存凭据；
- 命令行不提供 Key、Secret、Token、Prompt、Endpoint 或 Base URL 参数；
- 工具不会读取 `.env` 或 Provider 环境变量；
- Runtime stderr 被直接丢弃，Runtime 错误消息不会进入冒烟结果；
- 工具只保留符合稳定格式的 `error_code`，不输出错误正文。

## 自动化契约验证

本地 fixture 不访问网络，也不读取 Windows Credential Manager：

```powershell
py -3 -m unittest tools.tests.test_provider_smoke -v
```

契约验证覆盖：

- 严格解析 `provider_catalog`；
- 只允许目录中的 Provider 和模型 ID；
- 记录首状态、首包、总时延和分片数；
- 定时取消后记录取消时延并拒绝迟到完成事件；
- Runtime 错误只保留稳定错误码；
- 成功和失败输出均不包含 fixture 正文、凭据或端点；
- CLI 拒绝所有明文凭据、正文和端点参数。

## 真实模式

先进行不读取凭据、不访问 Provider 网络的目录检查：

```powershell
py -3 tools\provider_smoke.py --operation list
```

完成产品设置页配置后，运行完整冒烟：

```powershell
py -3 tools\provider_smoke.py --operation all --provider minimax
```

默认使用打包在 Tauri Host 资源目录中的正式 Runtime。验证其他受控 Runtime 构建时可以显式指定可执行文件：

```powershell
py -3 tools\provider_smoke.py --operation all --provider minimax --runtime D:\path\to\reflex-runtime.exe
```

流式请求会产生一次完整 Provider 调用；取消请求也可能产生 Provider 费用。正式门禁应在受控账号和明确预算下执行。

## 输出契约

每行是一个 JSON 对象，字段固定为：

| 字段 | 含义 |
|---|---|
| `operation` | `list`、`stream`、`cancel` 或启动阶段 |
| `provider_id` | 来自 Runtime 可信目录的 Provider ID |
| `model_id` | 来自 Runtime 可信目录的模型 ID |
| `classification` | `catalog_ok`、`success`、`cancelled`、`error` 或 `tool_error` |
| `first_status_ms` | 首个状态事件时延 |
| `first_chunk_ms` | 首个文本分片时延 |
| `total_ms` | 请求终态总时延 |
| `chunk_count` | 文本分片数量，不含正文 |
| `cancel_latency_ms` | 发出取消到收到取消终态的时延 |
| `error_code` | Runtime 稳定错误码；成功时为空 |

禁止在验证记录中追加 Runtime 原始事件、stderr、用户输入、响应正文、凭据、请求头或端点。

## 退出码

| 退出码 | 含义 |
|---:|---|
| `0` | 所选检查完成，且没有 Provider 错误 |
| `1` | Runtime 返回稳定 Provider 错误 |
| `2` | 工具、目录、凭据、协议或 Runtime 生命周期检查失败 |

若默认打包 Sidecar 尚未包含 `list_providers` 正式协议，工具会返回 `runtime_contract_outdated`。此时应先用当前提交重新生成候选 Sidecar，再执行真实门禁；不得通过放宽目录校验绕过版本不一致。

## P1-008 证据要求

真实门禁记录只保留本工具 JSON 输出，并附运行时间、构建提交和测试机器说明。凭据必须由用户在设置页新建或轮换；不得从聊天、命令历史、文档或环境文件复制旧凭据。
