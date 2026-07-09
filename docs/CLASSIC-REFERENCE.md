# Reflex Classic 参考映射

旧版参考实现位置：

```text
D:\Desktop\AI\11_Products\prod\Reflex
```

## 可迁移资产

| 能力 | 旧位置 | 新位置 |
|---|---|---|
| MiniMax 流式请求 | `api\minimax_client.py` | `plugins\provider-minimax` |
| Provider 通用脱敏与 HTTP 错误处理 | `api\base_client.py` | `packages\reflex-core\src\reflex_core\safety` |
| Provider 工厂思路 | `api\factory.py` | `runtime\plugin_manager.py` |
| Prompt 构建 | `api\prompt_builder.py` | `packages\reflex-core\template` |
| 旧模板资产 | `resources\templates` | `template-packs\builtin` |
| 场景注册表 | `core\scene_registry.py` | `packages\reflex-core\scene` |
| 输入校验与响应清洗 | `api\validators.py` | `packages\reflex-core\safety` |
| 语义识别 | `utils\scene_classifier.py` | `plugins\semantic-detector` |
| 模型下载 | `utils\model_downloader.py` | `plugins\semantic-detector` |
| 历史记录 | `database\history_manager.py` | `plugins\history-sqlite` |

## 不应迁移的结构

- `ui\main_window.py`
- `ui\viewmodels\main_viewmodel.py`
- `core\optimization_worker.py` 中的 `QThread` 实现
- 各类 PyQt `QDialog`
- 大设置页
- 欢迎页
- 复杂主题系统

## 参考测试

优先参考旧项目中这些测试意图：

- MiniMax 请求可观测性和脱敏
- 配置保存与迁移
- 优化线程状态反馈
- 取消回调只触发一次
- 语义识别关闭自动下载时不能下载大模型

这些测试不一定直接复制，但要转化为 Reflex Next 的核心契约测试。

