# Tauri Host

Tauri Host 是 Reflex Next 的轻量桌面外壳。

职责：

- 托盘
- 全局快捷键
- 小浮窗
- 剪贴板读写
- 设置入口
- 插件开关界面

禁止承载：

- Prompt 构建业务
- Provider 请求逻辑
- 场景识别逻辑
- 历史存储业务

宿主只消费 `reflex-core` 事件流，并把事件渲染给用户。

