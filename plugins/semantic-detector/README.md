# reflex-plugin-semantic-detector

语义场景识别插件规划目录。

定位：

- 它是核心体验的一部分，但不是核心依赖。
- 默认 Core 只内置 L0 规则识别。
- 本插件提供 L1 本地语义识别。

迁移来源：

- `D:\Desktop\AI\11_Products\prod\Reflex\utils\scene_classifier.py`
- `D:\Desktop\AI\11_Products\prod\Reflex\utils\model_downloader.py`

首版约束：

- 懒加载。
- 未启用时不得导入 `torch` 或 `sentence-transformers`。
- 模型未下载时不得阻塞优化。
- 失败时回退 `general`。

