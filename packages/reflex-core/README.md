# reflex-core

`reflex-core` 是 Reflex Next 的无 UI Python 内核。

它只负责：

- 输入校验
- 场景路由
- 模板解析
- Provider 协议调用
- 事件流输出
- 响应清洗
- 错误脱敏

它不负责：

- 窗口
- 托盘
- 快捷键
- 剪贴板
- 历史库
- 本地语义模型下载

## 当前能力

当前已建立第一阶段最小闭环：

- `OptimizeUseCase` 可在无 UI 环境中执行一次优化。
- 内置 L0 规则场景识别，支持邮件、代码、翻译、报告等常用场景，未命中时回退 `general`。
- 统一输出 `status`、`scene`、`request`、`chunk`、`done`、`metric`、`error` 事件。
- 输入为空时返回用户可见错误事件。
- Provider 类错误进入事件前会脱敏。
- `python -m reflex_core.sidecar` 可输出宿主可消费的 NDJSON 事件流。

## 本地验证

```powershell
cd packages\reflex-core
uv run --python 3.12 --with pytest pytest
```

Sidecar 示例：

```powershell
cd packages\reflex-core
$env:PYTHONPATH = "src"
python -m reflex_core.sidecar --request-json '{"text":"请写一封商务邮件确认会议时间。"}'
```
