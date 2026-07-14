# Reflex Next 语义模型生命周期基线

更新时间：2026-07-14
对应任务：`P3-007`

## 1. 目标

可选语义模型不得因并发优化、下载或删除重复加载重型运行时，也不得在模型缓存变化后继续使用已失效的内存对象。模型不可用或生命周期繁忙时，优化主链必须立即回退 Core L0 场景识别。

## 2. 生命周期语义

- 同一个 `SemanticSceneDetector` 的并发首次检测采用 single-flight，只有一个线程调用模型工厂；其余调用等待同一结果，不重复加载；
- 场景向量首次编码同样只执行一次，并发调用复用同一结果；
- 模型加载、下载、删除和状态读取共享进程内生命周期锁；
- 下载或删除期间，管理命令返回稳定安全错误 `model_busy`；
- 下载或删除期间，优化检测不等待管理操作，直接返回 `None`，由 Runtime 回退 L0；
- 下载成功和删除完成都会递增缓存代际；已加载检测器在下一次使用前发现代际变化，清空模型和场景向量；
- 下载中途取消、下载失败、删除失败和模型工厂异常均释放生命周期锁；
- 默认导入仍不加载 `sentence_transformers`、`torch` 或 `huggingface_hub`。

## 3. 并发证据

自动测试覆盖：

- 4 路并发检测只调用一次模型工厂，4 个调用均复用加载结果；
- 下载占锁时，`status`、`delete` 返回 `model_busy`，检测器不调用模型工厂并立即回退；
- 模型加载占锁时，`status`、`delete` 返回 `model_busy`；
- 删除后 `model_loaded` 立即失效，下一次检测重新加载；
- 下载中途取消后可立即执行删除，证明锁已释放；
- 本地模型缺失、低置信和编码异常继续安全回退。

## 4. 验证结果

```powershell
uv run --frozen --project plugins\semantic-detector --extra dev pytest plugins\semantic-detector\tests -q
# 14 passed

uv run --frozen --project packages\reflex-runtime --extra dev pytest packages\reflex-runtime\tests -q
# 309 passed

.\tools\verify_backend.ps1 -SkipFrontend
# Backend verification passed
```

统一门禁结果：Python 9 包共 686 项通过，Rust Host 184 项通过、3 项默认忽略；Provider、性能、Runtime 浸泡、插件/历史资源浸泡、安全扫描、依赖审计和 11 组件 SBOM 均通过。

远端独立复现：GitHub Actions Backend CI Run `29306300319`，结论 `success`，完成统一门禁、前端测试与构建、构建物扫描、SBOM 生成和上传。

## 5. 边界

- 正式安装包仍不默认携带重型语义依赖和模型；
- 本任务不改变模型下载来源或商业策略；
- 不受信任第三方模型与插件市场不在 `v1.0` 范围；
- 1 万条历史性能和 72 小时 Runtime 浸泡由独立任务继续验证。
