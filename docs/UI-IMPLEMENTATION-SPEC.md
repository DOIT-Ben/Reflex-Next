# Reflex Next UI 实现规格

更新时间：2026-07-09  
状态：实现基线

## 1. 目的与约束

本规格把设计稿的 `Current` 区域转换为可实现、可测试的 Tauri Host 契约。设计源文件由维护者私有保留，公开仓库不附带设计稿；界面形态以本文规格与发布物截图为准。

本规格不改变既有架构结论：

```text
Python Core + Tauri 2 轻量桌面宿主 + Python 插件系统
```

Tauri Host 只负责：

- 浮窗、托盘、全局快捷键和窗口生命周期；
- 剪贴板读写和首次覆盖确认；
- 用户输入、参数调整、事件渲染和用户反馈；
- 设置入口、插件入口和最近一次结果入口；
- 启动、管理 Python Sidecar，并转发 Host/Core 消息。

Tauri Host 禁止承载：

- Prompt 构建与模板渲染；
- Provider 请求、流式解析和错误分类；
- 场景识别业务；
- 输入安全校验、响应清洗和密钥脱敏策略；
- 历史数据库业务。

## 2. 唯一设计真值

开发只使用设计稿的 `Current` 页面组。当前页面集合：

| 设计稿页面 | 产品状态 | 说明 |
|---|---|---|
| `Current / Empty` | `empty` | 输入为空，主操作不可用 |
| `Current / Default` | `ready` | 有有效输入，可以生成 |
| `Current / Adjust` | `adjusting` | 修改模式、风格、场景和模型 |
| `Current / Generating` | `analyzing / connecting / streaming` | 同一视觉结构承载三个生成阶段 |
| `Current / Complete` | `completed` | 生成完成，展示结果操作 |
| `Current / Copied` | `completed + copied toast` | 复制成功的瞬时反馈 |
| `Current / Clipboard Confirm` | `completed + clipboard modal` | 首次覆盖剪贴板确认 |

旧版本、归档 Frame、探索稿和支撑页不得作为开发基线。

## 3. Host 技术基线

首个 Tauri Host 实现采用：

```text
Tauri 2 + Svelte + TypeScript
```

除非后续 ADR 明确推翻，不建立 React/Svelte 双轨。

建议目录：

```text
apps/tauri-host/
  package.json
  vite.config.ts
  svelte.config.js
  src/
    app.css
    App.svelte
    lib/
      components/
        AppShell.svelte
        TopBar.svelte
        InputCard.svelte
        ConfigSummary.svelte
        AdjustPanel.svelte
        GenerationStatus.svelte
        ResultCard.svelte
        ResultActions.svelte
        ClipboardConfirmDialog.svelte
        ErrorPanel.svelte
        Toast.svelte
      stores/
        app-state.ts
        settings.ts
      bridge/
        core-client.ts
        event-mapper.ts
        mock-event-source.ts
      types/
        core.ts
        host.ts
  src-tauri/
    Cargo.toml
    tauri.conf.json
    capabilities/
    src/
      main.rs
      commands.rs
      sidecar.rs
      tray.rs
      hotkey.rs
      clipboard.rs
      window.rs
      secrets.rs
```

## 4. 窗口规格

### 4.1 逻辑尺寸

所有尺寸使用 Tauri/WebView 逻辑像素，不按物理像素硬编码。

| 项目 | 数值 |
|---|---:|
| 推荐内容尺寸 | `760 × 540` |
| 最小尺寸 | `680 × 480` |
| 建议最大尺寸 | `920 × 720` |
| 顶部栏高度 | `60` |
| 页面水平边距 | `28` |
| 主输入区宽度 | `704` |
| 主按钮宽度 | `704` |
| 主按钮高度 | `50` |

### 4.2 窗口行为

- 默认使用无系统标题栏的轻量浮窗，窗口阴影开启，背景不透明。
- 顶部栏提供拖拽区域；交互按钮必须标记为非拖拽区域。
- 全局快捷键触发时：若窗口隐藏则显示并聚焦；若已显示则只聚焦，不创建第二实例。
- `Esc`：关闭调整面板或确认弹窗；无覆盖层时隐藏浮窗，不退出程序。
- 窗口位置越界时回退到当前显示器可见区域。
- 100%、125%、150% DPI 下不得出现裁切、重叠和不可点击控件。
- 小于推荐尺寸时优先压缩输入/结果高度，不压缩主按钮和关键操作高度。

## 5. 视觉令牌

首版只实现一套柔和浅色主题，不实现复杂主题编辑器。

```css
:root {
  --page: #eeece7;
  --window: #f8f7f4;
  --surface: #ffffff;
  --line: #e5e2da;
  --line-strong: #d8d4ca;
  --text: #1c1d20;
  --muted: #73767d;
  --weak: #a2a5ab;
  --accent: #5361c8;
  --accent-soft: #eef0fc;
  --success: #4f8a68;
  --danger: #b75c5c;
  --toast: #24262b;

  --radius-sm: 10px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-window: 20px;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-7: 28px;
}
```

规则：

- 强调色只用于主要操作、进度和明确选中态。
- 默认页不得同时出现多个实心强调按钮。
- 不使用大面积渐变、重玻璃拟态、发光边框或装饰性插画。
- 边框承担分组，阴影只用于窗口和模态层，不给每个控件堆阴影。

## 6. 主界面信息层级

默认页只允许三层：

```text
输入内容
  -> 当前配置摘要 / 调整
  -> 优化文本
```

不得在默认页平铺模式、四种风格、完整场景列表和模型列表。

### 6.1 TopBar

展示：

- Reflex 标识；
- 当前 Provider 状态；
- 设置入口。

不展示：

- 历史、批处理、模板管理等多枚工具栏图标；
- API Key、Endpoint、调试状态；
- 大型导航。

### 6.2 InputCard

- 支持手动输入和“读取剪贴板”。
- 显示字符数，不显示 token 估算。
- 输入为空时主按钮 disabled。
- 过短文本可以生成，但显示弱提示，不阻断。
- 技术校验错误不得直接展示堆栈或原始异常。

### 6.3 ConfigSummary

单行展示：

```text
内容优化 · 平衡 · 报告写作 · MiniMax
```

右侧只有“调整”。

### 6.4 AdjustPanel

调整字段必须与 `OptimizeRequest` 对齐：

| UI 字段 | Core 字段 | 值 |
|---|---|---|
| 模式 | `mode` | `content / prompt` |
| 风格 | `style` | `concise / balanced / detailed / creative` |
| 场景 | `scene` | 场景 ID 或 `null` |
| 场景策略 | `scene_policy` | `auto / manual / ask` |
| Provider | `provider` | Provider ID 或 `null` |
| 模型 | `model` | Model ID 或 `null` |
| 流式输出 | `stream` | 首版固定 `true`，不在主面板暴露 |

“应用”只修改当前请求草稿；是否写入默认值由设置页负责。

## 7. Host 状态机

```ts
type HostPhase =
  | 'booting'
  | 'empty'
  | 'ready'
  | 'adjusting'
  | 'analyzing_scene'
  | 'connecting_provider'
  | 'streaming'
  | 'completed'
  | 'cancelled'
  | 'error';
```

UI 覆盖层单独表达，不污染主 phase：

```ts
type Overlay =
  | null
  | 'clipboard_confirm'
  | 'settings'
  | 'plugin_manager';
```

关键转换：

```text
booting -> empty / ready
empty + valid input -> ready
ready + adjust -> adjusting
adjusting + apply/cancel -> ready
ready + generate -> analyzing_scene / connecting_provider
analyzing_scene -> connecting_provider
connecting_provider -> streaming
streaming -> completed
analyzing/connecting/streaming + cancel -> cancelled -> ready
任意执行阶段 + error -> error
error + retry -> 上一次可执行请求
completed + copy -> completed + toast
completed + replace -> clipboard_confirm -> completed
```

开始新请求时必须清空旧流式缓冲区；取消后迟到的 chunk/done 必须按 `request_id` 丢弃。

## 8. Core 事件到 UI 的映射

Host 不得通过解析中文状态字符串判断阶段。事件必须包含稳定字段。

建议事件数据：

```json
{"type":"status","data":{"phase":"analyzing_scene","message":"正在分析场景"}}
{"type":"scene","data":{"scene":"report_writing","confidence":0.86,"method":"rule"}}
{"type":"request","data":{"provider":"minimax","model":"MiniMax-M2.7-highspeed"}}
{"type":"chunk","data":{"text":"..."}}
{"type":"done","data":{"text":"...","scene":"report_writing","provider":"minimax","model":"..."}}
{"type":"error","data":{"code":"provider_unavailable","message":"模型服务暂时不可用","recoverable":true,"action":"retry"}}
{"type":"metric","data":{"elapsed_seconds":2.4}}
```

映射规则：

| Core Event | Host 行为 |
|---|---|
| `status.analyzing_scene` | phase=`analyzing_scene` |
| `scene` | 更新识别场景；不强制覆盖用户手动场景 |
| `request` | phase=`connecting_provider`，更新 Provider/模型摘要 |
| 首个 `chunk` | phase=`streaming`，开始追加结果 |
| 后续 `chunk` | 按顺序追加，批量节流渲染 |
| `done` | phase=`completed`，固化最终结果 |
| `error` | phase=`error`，只展示脱敏 message 和恢复动作 |
| `metric` | 更新耗时等弱信息，不抢占主视觉 |

场景识别失败时 Core 应回退 `general` 并继续执行，Host 只显示弱提示。

## 9. Tauri 与 Python Core 边界

首版采用 Python Sidecar + NDJSON 标准输入输出，不开放本地 HTTP 端口。

```text
Svelte UI
  -> invoke Tauri Command
Rust Host
  -> 启动/复用 Python Sidecar
  -> stdin 写入 command envelope
Python Runtime/Core
  -> stdout 输出 event envelope
Rust Host
  -> 转为 Tauri event
Svelte UI
  -> event mapper -> store -> render
```

命令信封：

```json
{
  "version": 1,
  "request_id": "uuid",
  "type": "optimize",
  "payload": {
    "text": "...",
    "mode": "content",
    "style": "balanced",
    "scene": null,
    "scene_policy": "auto",
    "provider": "minimax",
    "model": null,
    "stream": true
  }
}
```

取消：

```json
{"version":1,"request_id":"uuid","type":"cancel","payload":{}}
```

事件信封：

```json
{
  "version": 1,
  "request_id": "uuid",
  "event": {"type":"chunk","data":{"text":"..."}}
}
```

安全要求：

- API Key 不得通过命令行参数传递。
- API Key 不得写入 stdout/stderr、前端 store、localStorage 或诊断日志。
- Rust Host 负责平台安全存储；需要交给 Python Provider 时通过匿名管道内存传递，并在使用后释放引用。
- Sidecar stderr 只允许脱敏诊断信息。
- 每个消息必须带 `version` 和 `request_id`。

## 10. Mock Event Source

Tauri UI 开发不能阻塞在真实 Provider。

`mock-event-source.ts` 必须支持：

- 正常链：status -> scene -> request -> chunk×N -> done -> metric；
- 场景识别失败但回退成功；
- Provider 未配置；
- Provider 暂不可用；
- 流式中取消；
- 迟到 chunk；
- 空结果；
- 长结果与快速 chunk。

Mock 数据不得调用网络，不得要求 API Key。

## 11. 剪贴板规则

- “读取剪贴板”属于明确用户动作，首版默认不在窗口打开时静默读取。
- 复制结果：直接执行，成功 Toast 保留约 2 秒。
- 替换剪贴板：首次使用显示确认；用户可在设置中选择是否以后继续确认。
- 自动替换剪贴板不作为首版默认值。
- 读取或写入失败时显示用户可理解错误，不展示系统 API 原始异常。

## 12. 托盘与快捷键

托盘最小菜单：

- 打开 Reflex；
- 最近一次结果；
- 插件管理；
- 设置；
- 退出。

全局快捷键：

- 必须使用 Tauri 全局快捷键能力，而不是 Web `keydown` 冒充系统热键。
- 默认值需在实施 Issue 中确定并做冲突处理。
- 注册失败不得导致应用退出；应提示用户修改快捷键。

窗口内快捷键：

- `Ctrl + Enter`：有效输入时生成；
- `Esc`：关闭覆盖层或隐藏窗口；
- 生成中再次按 `Ctrl + Enter`：不重复提交。

## 13. 错误呈现

错误 UI 只展示：

- 用户可理解标题；
- 脱敏说明；
- 是否可重试；
- 可执行动作：重试、打开设置、复制诊断 ID。

禁止展示：

- API Key、Bearer Token；
- Endpoint 查询参数；
- 请求体和完整用户输入；
- Python/Rust/JS 堆栈；
- Provider 原始响应全文。

## 14. 最近一次结果

首版只保留内存中的最近一次成功结果：

```ts
interface RecentResult {
  requestId: string;
  inputSummary: string;
  output: string;
  createdAt: string;
  scene: string;
  provider: string;
  model?: string;
}
```

不建立 SQLite，不实现搜索、评分、导出和大历史页面。

## 15. 测试与验收

### 15.1 前端自动测试

- Host 状态机转换单测；
- Core Event 映射单测；
- `request_id` 过滤迟到事件；
- Empty/Ready/Generating/Complete/Error 组件测试；
- 调整面板字段到 `OptimizeRequest` 的映射测试；
- 剪贴板首次确认策略测试。

建议：Vitest + Svelte Testing Library。

### 15.2 Rust 自动测试

- Sidecar 命令/事件序列化；
- 进程启动失败和退出处理；
- 全局快捷键注册失败回退；
- 剪贴板错误转换；
- 日志脱敏边界。

### 15.3 Python 契约测试

- Event envelope 包含 version/request_id；
- status.phase 使用稳定枚举；
- 取消后不再发送有效 done；
- 场景失败回退 general；
- 导入 Core 不引入被禁止依赖。

### 15.4 手工视觉验收

必须提交截图或录屏证据：

- 760×540：100%、125%、150% 缩放；
- 680×480 最小窗口；
- 空态、默认态、调整态、生成中、完成、复制、确认、错误；
- 长输入、长结果和快速流式输出；
- 键盘完整操作路径；
- 全局快捷键显示/聚焦行为。

## 16. 完成定义

UI 实现只有同时满足以下条件才能宣布完成：

1. 设计稿 Current 页面状态全部可复现；
2. 默认页没有退化成参数表单；
3. Host 不承载 Core 业务；
4. 使用 Mock Event Source 可跑通完整交互；
5. 真实事件协议与 Mock 协议一致；
6. 自动测试通过；
7. DPI/最小尺寸和键盘路径有证据；
8. 无真实密钥、完整输入或原始 Provider 错误泄露。