# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号采用语义化版本（`MAJOR.MINOR.PATCH-阶段.N`）。

## [Unreleased]

### 新增

- 快捷面板：预创建的置顶小窗口（默认 `Alt+Q` 唤起/收起，可在设置中改键），
  唤起时自动带入剪贴板文字，`Ctrl+Enter` 直接优化，完成后一键复制或按
  auto_replace 策略写回剪贴板，Esc 与失焦自动隐藏；托盘菜单新增「快捷面板」入口；
- 开机自启（设置开关）与启动静默进托盘：主窗口启动时不再自动弹出，
  通过快捷键、托盘或二次启动唤起；
- Runtime Sidecar 预热：主窗口与快捷面板就绪后后台预热 Sidecar，
  消除首次优化的冷启动延迟（实测冷启动 P50 约 0.6s）；
- 新增三项前端架构契约测试：空状态只有一套配方（并禁止退役的
  `.app-shell .result-pane .center-state` 代际回归）、禁止把浏览器原生
  disclosure marker 当作折叠指示（含 CSS 边框三角替身）、组件 `<style>`
  内的间距必须落在共享 4px 刻度上、圆角必须落在共享圆角刻度上——
  此前契约只覆盖 styles.css，组件内碎片值不受约束。

### 修复

- 第二轮对标审查（三子智能体并发 + 逐条真机验证）修掉的硬缺陷：
  - **关闭 preflight 的按钮 UA padding 漏网**：浏览器默认 `button { padding: 1px 6px }`
    没被重置，shadcn Switch 轨道被撑出 6px 内容边距，选中态滑块平移 20px 后
    溢出轨道（视觉上是一个月牙）；在 `app.css` 基座补 `padding: 0` 后，
    滑块回到 2px 内缩、两端对齐（真机实测 track 44×24、thumb 20×20、选中 x=22）；
  - **暗色工作台被玻璃白罩刷灰**：遗留「White studio glass」层用
    `rgb(255 255 255 / 40%) !important` 涂 `result-pane::before`/`input-pane::before`/
    `result-body`，亮色下不可见、暗色下整个结果区变成一片灰（`elementsFromPoint`
    实锤）；删除白罩与 `result-body` 渐变后暗色工作台恢复干净实色；
  - **卡片表面写死 `#fff`/`#e4e7eb` 字面量**：白页改造时留下的 8 处字面量在暗色下
    仍是白面板（设置页白底配亮字直接不可读），全部换成 `hsl(var(--background))` /
    `var(--line)` 令牌——亮色仍是纯白，暗色自动跟随；
  - **DialogShell 混用 `<slot>` 与 `{@render}`**：Svelte 5 禁止同组件混用，
    9 个调用方还停在旧 `slot="footer"` 写法；全部迁移到 snippet（`children`/
    `actions`/`footer`），`svelte-check` 的 17 个级联错误归零；
  - **评分按钮在组件上用 `class:` 指令**：Svelte 5 不允许，改为模板字符串 class；
  - 设置页 h3 被第三层遗留规则改回 `font-weight: 700 / margin 20px`（与
    CC 分节头配方打架），删除该层后统一为 500/16px；
  - 设置页脚的浅色渐变横带在暗色下漏白，改为透明；
  - 清理死样式：`.confirm-icon.warning`、`.confirm-actions`、
    `.desktop-hotkey.checkbox-row`（标记已迁移后无引用）。

- 依赖审计门禁（release 级 `run_heavy` 才跑）此前无法通过：两个 npm 依赖的许可证
  没被策略分类。`svelte-toolbelt@0.10.6` 上游 `package.json` 缺 `license` 字段，
  锁文件里是空值被判为 `unknown`（实为 MIT，按仓库既有做法补
  `licenses/package_overrides/npm` 条目，与 `argparse@2.0.1 -> Python-2.0` 等同款）；
  `caniuse-lite` 的真实许可证是 `CC-BY-4.0`（autoprefixer / browserslist /
  lightningcss 的构建期依赖，不进产物），此前未列入白名单被判为 `unclassified`，
  现加入 `licenses/allowed_expressions/npm`。该许可证不在策略的
  `forbidden_patterns`（AGPL/GPL3/SSPL/BUSL/Commons Clause/Elastic）之内；
- 空状态收敛为唯一配方：`result-pane` 历史上存在 4 代互相覆盖的 `.center-state`
  规则（12/24、32px + 紫色径向光晕、回退到 12px、窗口作用域 700 字重），
  最终工作台渲染成 14px/12px 无边框、历史视图却是 18px/14px 虚线卡。删除全部
  4 代与光晕伪元素后，工作台与历史共用同一套排版（18px/600/27 标题、
  14px/21 说明、512px 行宽、16px 间距、40px 内边距、12px 圆角虚线卡），
  真机 WebView2 实测与历史视图逐项一致；
- 折叠指示不再依赖浏览器原生 marker：「更多设置」「更多结果工具」改用 lucide
  `chevron-right` 图标并在展开时旋转 90°（此前用 CSS 边框三角冒充，视觉上仍是
  实心 ▶，与全库线性图标语言不一致）；同时给所有 `summary` 规则补上
  `list-style: none`，避免外壳层规则盖过组件层后原生 marker 重新出现；
- 组件层间距与控件高度对齐 4px 栅格（51 处）：`gap`/`padding`/`margin` 的
  3/5/7/9/11/13/18/22px 等碎片值归位，`min-height` 的 25/29/38/54/70/74/76/90px
  归位；其中 `@media (max-height: 520px)` 下运行按钮的 `height: 35px` 越出
  32/36 控件高度契约，改为 32px；
- 模型选择器去双层描边：`.model-picker` 自身有边框与底色，内部 select 也自带边框，
  形成嵌套双框并把整体顶到 34px；改为无边框容器（真机实测 258×32），并让「模型」
  标签 `flex: 0 0 auto` + `nowrap`，不再被 select 挤成竖排两行；
- 死代码清理改用 AST 方式：postcss 解析后按选择器裁剪，删除 111 条只含退役选择器的
  规则、2 个未引用 `@keyframes` 与 3 个空 at-rule，styles.css 4858 → 4198 行；
  逐条比对确认「消失的规则全部只含退役选择器，活体样式零丢失」；
- 修复前端初始化崩溃导致的空白窗口：修复按钮面板 `providerOptions`/`toast`/
  `activationState`/`cloudConsent`/反馈面板 props 等约 10 处 store 被当作普通值
  使用的遗留缺陷（`svelte-check` 全量模板类型检查归零），并加固
  `feedbackContextFor`、`translationFlow.open` 对空结果的处理；
- 修复窗口显示时序：隐藏创建的窗口在 show 之后补充最小化还原，
  避免以最小化形态显示；
- 修复交互层 store 裸用导致的常驻弹窗：场景/反馈对话框改为订阅后条件渲染，
  反馈时机判断与 BYOK 判断修正，反馈开关不再把 store 对象写入配置；
- 修复弹窗视觉与布局：遮罩加深（16%→46%）、弹窗面板改为 96% 不透明
  （深色主题同步，避免底层文字穿透）、弹窗只在标题栏下方区域居中、
  高度改为自适应上限（消除底部裁切与过高空白）；
- 新增 store 误用守卫测试，自动拦截「store 被当普通值使用」这一缺陷类；
- 设置页布局重排为统一的「标签｜控件」行：默认行为、剪贴板、安全与隐私各分区对齐一致，
  选项胶囊单行等宽不再折行，Provider 表单（下拉/输入/按钮）统一列宽与分隔线；
- 组件层迁移收尾：styles.css 瘦身 5360 → 3914 行（清理 38 条退役规则/48 个
  死选择器项）；补齐 Tailwind 边框基线（关闭 preflight 后 `.border` 只设宽度、
  样式为 none 导致边框不渲染的隐蔽问题），并移除遗留 `button { border: 0 }`
  与其冲突的声明；
- 组件层迁移阶段六：全项目下拉统一到 AppSelect（历史筛选/导出格式/备份恢复、
  批处理、模板分类、场景选择、调整面板、反馈类型），旧 SelectField 组件退役删除，
  架构测试同步改为守护「原生 select 零出现 + 仅经 AppSelect 封装」；
- 组件层迁移阶段五：结果区（重试/打开设置/复制结果/替换剪贴板/对比原文/
  再调整/导出/历史/翻译/预览/反馈/评分）全部替换为 shadcn Button 变体，
  快捷面板（模式与风格分段、优化、复制、关闭）完成替换并验证 token 跨窗口生效，
  迁移后的组件内孤儿样式同步清理；
- 组件层迁移阶段四：设置页输入框/下拉（Input/AppSelect）与工作台主链
  （运行/取消/调整按钮、快捷动作、模型下拉）全部替换为 shadcn 组件，
  组件内遗留元素选择器同步收敛为语义类或全局布局规则；
- 组件层迁移阶段三：设置页表单控件全面替换——7 处分段选择器改用
  ToggleGroup 封装（SegmentedControl，含选中态 token 化）、全部复选框与
  开关改为 shadcn Switch（含插件/隐私/历史/开机自启）；
- 组件层迁移阶段二：主题镜像到 <html>（弹层/portal 在深色下拿到正确 token）、
  补 <button> 最小重置（关闭 preflight 后浏览器默认灰底会透到 ghost 变体上）、
  收敛设置页遗留元素选择器（footer/nav 改为语义类），设置导航迁移为 shadcn Button；
- 前端组件层启动 shadcn-svelte 迁移（阶段一）：接入 Tailwind（关闭 preflight 与既有
  CSS 共存、色板映射既有设计 token、rem 刻度折算为 px）、从官方 registry 直装
  17 个标准原语（button/input/select/dialog/switch/tooltip/dropdown 等），
  设置页底部按钮完成试点替换；项目的 typecheck 升级为 svelte-check；
- 禁用 WebView2 内核自带的浏览器右键菜单（刷新/检查元素等）：非编辑区域右键
  不再弹出网页式菜单，输入框与可编辑区域保留（复制/粘贴可用），新增守卫测试；
- 设计体系统一（参考 CC Switch/shadcn 的 zinc 灰阶 + Apple 蓝配色）：清理历史遗留的
  多套相互覆盖的主题变量块，全应用收敛到单一浅色/深色色板，表面材质改为干净实色、
  边框可见、圆角收敛（16/12/8px），主色由灰蓝改为高辨识度蓝色。

### 变更

- 第二轮 CC Switch 对齐（三子智能体审查后的组件与版面批改）：
  - **设置页开关行改造为 CC 的 toggle-row 卡片**（`toggle-row.tsx` 配方逐字对齐）：
    左侧 32px 图标座（`bg-background` + 1px ring）+ 标题（14/500）+ 说明
    （12/400 muted）、右侧 Switch，整行 `bg-card/50` 卡片、16px 内边距、
    hover 提亮到 `bg-muted/50`；安全与隐私 5 行、插件行、开机自启行全部套用，
    每行配语义色 lucide 图标（自启 Power 橙、改进计划 Sparkles 蓝、反馈
    MessageSquare 琥珀、历史 History 绿等，同 CC 的着色思路）；
  - **分节标题对齐 CC 配方**：图标（`h-4 w-4 text-primary`：Cpu/SlidersHorizontal/
    ClipboardList/ShieldCheck/Puzzle）+ 标题 + `border-b border-border/40` 底边线；
  - 12 个 shadcn 原语逐字改写为 CC Switch 的 registry 配方（Button default/outline/
    ghost、Switch、Textarea、Tooltip 无箭头 + 方向性入场、Checkbox、Badge、
    Select 触发器/Label、Popover、Dropdown checkbox/radio/label），并清出
    26 处 Tailwind v4 死类（`shadow-xs`/`outline-hidden`/`rounded-xs`/
    `field-sizing-content`/裸 `data-highlighted:`——在 v3 下不生成任何 CSS）；
  - **主题跟随 OS 实时切换**：新增 `watchSystemTheme`（`matchMedia` change 监听），
    主窗口与快捷面板在 `theme=system` 档下随系统深浅即时重放（对齐 CC 的
    theme-provider）；hover 底色改用 `color-mix(var(--muted))` 主题自适应；
  - 版面批改：四张窗口级卡片（输入列/结果面板/设置面板/历史工作区）圆角
    12→14px（xl，嵌套内层 12 的同心规则）、历史左栏定宽 320px、历史行语义重排
    （标题主文本 + 时间 meta）、状态栏 5 处硬编码色换令牌、确认弹窗重建为
    CC 形态（图标座 + 标题同行 + footer snippet）、工具栏支持二级视图返回
    （历史/设置页显示「← 标题」）；
  - 新增三条架构契约测试：禁 Tailwind v4 死类、裸 `<button>` 只减不增
    （存量 6 文件进白名单）、主题双轨（显式 dark + system 跟随 OS）必须同时在；
  - 附带清理：`app.css` 重复的焦点规则、`.editor-frame` 圆角字面量改令牌、
    圆角注释把 kbd 标注为本项目自有扩展（CC 无此元素）。

- CI 依赖的 GitHub Actions 升到当前主版本，消除 runner 上的
  「Node.js 20 is deprecated，以下 action 被强制跑在 Node.js 24」告警：
  `actions/checkout` v4→v7、`actions/setup-node` v4→v7、`actions/setup-python` v5→v7、
  `actions/upload-artifact` v4→v7、`actions/cache` v4→v6、`astral-sh/setup-uv` v6→v10.1.0
  （setup-uv 自 v7 起不再发布浮动大版本标签，必须写完整版本号，否则报
  `unable to find version v10`）；升级前逐个核对了 workflow 实际用到的输入
  （`python-version`/`node-version`/`cache`/`cache-dependency-path`/`version`/
  `enable-cache`/`cache-dependency-glob`/`name`/`path`/`if-no-files-found`/
  `retention-days`）在目标版本里仍然存在；
- 按子智能体的对标审查返修一轮（逐条带实测证据，19 项）。修掉的严重项：
  设置页页头/正文/页脚横向错位 20px（`.ui-dialog-content` 的 20px 内边距没在
  page 形态归零，导致页头在 24px、正文在 44px）；历史左右两栏空白态内缩
  0 vs 18px 且都贴顶、下方留 280~330px 死白（两栏统一 16px 内边距、空白态撑满
  所在列并居中、标题提到 18px/600、说明 14px）；主按钮 hover 由品牌蓝变成泥灰
  `#465968`（改为 CC Switch 的 `bg-blue-500 → hover:bg-blue-600`，圆角回到 12px，
  删掉 `!important` 投影）；空状态 64px 图标座被一条 `!important` 白底打成隐形
  并挂着 7s 无限缩放动画（恢复 muted 实心底、去掉动画）；
- 主输入框焦点恢复：`styles.css` 里未分层的裸元素规则 `textarea { outline: none }`
  会击败 `app.css` 中 `@layer base` 的全局焦点规则（CSS 级联层规则：未分层样式
  优先于任何 `@layer`），输入框因此完全没有键盘焦点反馈；现在焦点指示统一落在
  外框上（2px / 20% 柔蓝光晕 + 边框提亮，即 CC Switch 的输入配方）；
- 字重从 12 种非标准值（620/640/650/680/720/740/760/780/800…）收敛到 500/600/700
  三档，与 CC Switch 只用 400/500/600/700 一致；正文级标签色由 `--weak`
  （#a1a1aa，白底对比 2.56:1，不达 WCAG AA）改为 `--muted`（#71717a，4.83:1）；
- 历史行 hover 不再抹掉选中态（`hover:not(.active)`）；分隔线统一到 `var(--line)`；
  设置导航胶囊圆角与顶栏同心（12-4=8px）；可滚动区域移植 CC Switch 的细滚动条，
  不再出现「内容被硬裁切且无任何滚动提示」；
- 焦点体系按 CC Switch 的契约重写（原文：`*:focus-visible { @apply outline-2
  outline-blue-500 outline-offset-2 }`）：全应用恢复成**一条全局规则**
  （2px 蓝色 outline + 2px 偏移），删除 styles.css 里 9 组各写各的
  `:focus-visible` 覆盖（偏移 1px/-2px/加 3px 光晕/改边框色各不相同），
  并把 shadcn 新版 registry 的「3px 环 + 边框变色」配方换成 CC Switch 的配方：
  按钮 `ring-1`、输入框与多行框 `ring-2 + ring-blue-500/20`（柔光、不改边框）、
  下拉触发器只提亮边框、开关/复选/徽章 `ring-2 + ring-offset-2`。
  之前同一个输入框会同时吃到「边框变蓝 + outline + 光晕」三层，出现内外双蓝圈；
- 控件圆角按 CC Switch 分级：默认按钮 `rounded-lg`（12px）、`sm` 按钮与输入框
  保持 `rounded-md`（8px），补上它的 `blue` 色阶（400/500/600）与
  `.border-border-active` 等边框工具类；
- 补上 CC Switch 的动效令牌（fadeIn 0.5s / slideUp 0.5s / slideDown 0.3s /
  slideInRight 0.3s / accordion 0.2s），工作台与历史视图入场走 `animate-fade-in`；
  按钮改 `transition-colors`（原来是 `transition-all`）；
- 场景选择对话框的搜索框由手写原生 `<input type="search">` 改为 shadcn `Input`
  （焦点、尺寸、圆角、图标左内边距统一到同一套契约）；
- 间距与表面契约统一（对齐 CC Switch 的实测值）：页面水平 gutter 24px、
  面板之间 16px、卡片内边距 16px、底部呼吸 24px；顶栏 56→64px、状态条 28→32px
  并统一 24px gutter。工作台原先跑在 `outer-contour` 的「无缝整版」形态下
  （输入区与结果区共用一张白纸、网格间距 0、面板强制透明零边框），现在改为
  「浅灰页底（#fafafa）+ 两张独立白卡片（1px 描边 + 12px 圆角，静止无阴影）」，
  设置页与历史页同样收进卡片，页头页脚的灰色横带去掉；
- 圆角刻度对齐 CC Switch（它把 Tailwind 的 sm/md/lg/xl 重定义为 6/8/12/14px）：
  全仓 `border-radius` 从 **19 个取值**收敛到 5 档——sm 6px（徽章/kbd）、
  md 8px（按钮/输入/下拉）、lg 12px（卡片/浮层/弹窗）、xl 14px（窗口级表面）、
  圆形；控件圆角由 6px 提升到 8px，卡片由 8px 提升到 12px，控件与卡片才真正分层；
- 空状态对齐 CC Switch 的空状态契约：内边距 40px、图标座改为 64px 圆形 muted
  实心底、说明文字由 12px 提到 14px 且行宽上限 512px、块间距 16px；
  说明类文本加 `text-wrap: pretty` 避免「史。」这种单字孤行；
- 交互过渡统一到 150ms 的颜色过渡（按钮/行/chip/胶囊）；
- 全应用刻度统一（真机实测收敛为唯一一套）：高度只有 32px（`sm`/图标）与
  36px（默认控件）两档、字号只有 12/14/18px 三档、行高只有 18/21/23/27px
  四档、圆角只有 6px 一档，五个界面（工作台/历史/设置/调整弹窗/命令面板）
  全部落在这套刻度内；根因是 `:root` 曾把根字号设成 14px，rem 制的 Tailwind
  刻度被整体缩放（`h-8` 变 28px、`text-sm` 变 12.25px、`rounded-md` 变 5px），
  现已恢复 16px 基准并把 Tailwind 的 `fontSize`/`borderRadius` 直接钉成 px，
  使刻度不再随根字号漂移；同时删除遗留 CSS 对高度/圆角的硬编码
  （运行按钮 44/46px、快捷动作 54/62px、命令列表 38px、密钥行 44px、
  设置输入框 10px 圆角等），全部回到 shadcn 控件刻度；
- 行高改为「由字号决定」的 token 体系：新增 `--leading-none/meta/body/prose/title`
  （1/18/21/23/27px），全仓 176 处 `line-height` 全部改为 token，清零原先
  1.35~1.82 的倍数列高 —— 它们会按各自字号重算出 16.2/16.8/17.76/19.8/26.1 这类
  碎片值；同时给 123 处只写了字号、没写行高的规则（按钮内加粗标签、chip、
  kbd、状态条、设置说明等）补上配套行高，避免子元素继承父级绝对行高造成的
  错位（例如 12px 的运行按钮标签继承了 14px 的 21px 行高）；
- 单窗口化（与 CC Switch 同构）：历史记录不再单独开窗，改为主窗口内的视图
  —— 顶部工具栏「历史记录」直接切视图，维护下拉并入筛选行右端，结果区的
  「历史」按钮与托盘菜单入口同样切到该视图；主窗口凭据矩阵相应放开历史读取
  （list/detail/rate/backups/scan）与历史管理（导出/删除/清空/修复/恢复/轮换）
  权限，Rust 侧授权测试改为「仅 main 与 history 两个已知窗口可用，未知标签一律
  拒绝」；旧 `HistoryApp.svelte`/`HistoryHeader.svelte` 退役，逻辑迁入
  `components/history/HistoryView.svelte` 与 `HistoryMaintenanceMenu.svelte`；
- 弹窗与控件比例对齐 CC Switch：`DialogShell` 按 CC Switch 的 dialog 契约重写
  （50% 黑遮罩 + 4px 模糊、居中、`max-h: 90vh`、尺寸档 sm/md/lg = max-w-sm/lg/2xl、
  头部与底部 `16px 20px` 加分隔线与浅灰底、正文滚动区），调整生成方案面板
  整体重建为 `DialogShell` 弹窗（分段控件等宽、搜索框与分类同行对齐、
  预览行限高），连带删除 33 条 `.adjust-*` 遗留样式；
- 命令面板重建为 CC Switch 的 cmdk 结构：标题 + 说明 + 搜索输入框（图标在框内）
  + 命令列表（h-9 行、首项高亮、Enter 执行、输入过滤），替换原无搜索框的裸列表；
- 修复遗留 `.ui-dialog-shell` 规则（`padding: 22px` 等）与组件样式打架：弹窗头部/
  底部灰条被内缩成「白框套灰盒」并吃掉 44px 高度导致内容被切，删除后组件为唯一
  定义处（真机实测 header/footer 满幅、内容溢出 0px）；
- 修复下拉弹层溢出窗口的根因：registry 组件残留 Tailwind v4 简写
  （`max-h-(--bits-…)` / `h-(--…)` / `min-w-(--…)` / `origin-(--…)`）在 v3 下被丢弃，
  长列表（42 个场景）弹层因此没有高度上限并冲出窗口顶部；改为 `[var(--…)]` 写法
  并移除 side 方向 translate 微调后，弹层稳定收敛在窗口内滚动；
- 统一控件高度刻度：删除遗留 CSS 对按钮的 38px 强制（输入区头部动作、
  配置摘要调整按钮、结果区次要动作、主行动按钮共 4 组规则），全部回到
  shadcn Button 刻度（默认 h-9、`sm` h-8）；
- 壳层全面对齐 CC Switch：主窗口改回系统原生标题栏（1200×650、最小 945×600、
  满幅无圆角无边距，`decorations` 与系统阴影启用），自绘标题栏与窗口控制按钮退役
  （`ReflexTitleBar` 及其 `windowControls` 依赖删除）；左侧导航栏替换为顶部工具栏
  （品牌区 + 文字快捷键胶囊 + 右侧 Provider 标签与命令入口；胶囊高 32px、置于
  `bg-muted` 圆角容器内、选中态用 `secondary` 变体加浅阴影）；设置页由模态弹窗
  改为壳内独立页面（进入设置时工作台让位，无遮罩、无弹窗外壳、取消按钮仅在弹窗
  形态出现），`DialogShell` 新增 `page` 形态并由架构测试守护；
- 历史窗口同构化：顶部换成与应用一致的工具栏（品牌 + 工作台/历史记录胶囊 +
  右侧「维护」菜单），历史窗口新增 `allow-show-main-window` 权限以便从工具栏
  回到主窗口；修复筛选行被遗留规则强制涂成主色的缺陷（场景/风格下拉、筛选按钮
  恢复为描边控件），搜索框改用 shadcn Input，工作区改为占满剩余高度
  （修掉顶部约 250px 空白）；
- 全部动作按钮迁到 shadcn Button：13 个组件里 43 处手写 `<button class="outline|
  primary|danger-icon">` 全部替换为 `Button` 变体（含设置页密钥/连接操作、
  诊断包、语义模型、模板管理、批处理、翻译、Markdown 预览、结果对比、历史
  维护与详情、反馈与首启面板），确认弹窗与首启引导也改用 `Button`，
  旧原语 `BaseButton` 与其 `.ui-button` 样式（1124 字符）一并删除；
  新增架构测试守护「手写动作按钮零出现 + BaseButton 不得复活」；
- 快捷面板（Alt+Q）改用设计 token：输入框换成 shadcn Textarea、头部用 ghost
  图标按钮、结果区改用 muted 底与描边，去掉遗留硬编码配色；
- 全局快捷键升级为双键体系：工作台快捷键与快捷面板快捷键独立注册、
  独立替换（同一事务内持久化，任一失败整体回滚），并拒绝两键配置冲突；
- 前端架构重构：App.svelte 从 2851 行拆解至约 1750 行，全部功能流下沉为
  `domain/` 下的可注入、可单测控制器（优化主链、设置、批处理、翻译、模板、
  Markdown 预览、语义模型、剪贴板、反馈、首启激活、云隐私、诊断包、
  窗口控制、滚动同步、toast、视图缩放、下载助手），键盘策略与工作台
  视图模型亦纯函数化，并新增架构测试守护分层与行数预算；
- 抽取 `i18nStore` 统一组件翻译注入，支持运行时切换 UI 语言；
- 统一 `DialogShell` 弹窗外壳（背板层/尺寸档/关闭按钮/Esc/自动聚焦）并抽取 `Spinner` 组件；
- 修复 StatusBar 与窗口底边空隙；生成完成/失败时结果区自动滚入视野。

## [0.7.0-alpha.8] — 2026-09-01

### 新增

- 新增原生协议与 Responses Provider 插件，语义检测对齐场景库；
- 首次成功引导与结果采用完整可用，功能全面合并；
- 前端工作台与反馈链路对齐；Cloud 质量发布与反馈链路完善。

### 修复

- 修复 Runtime 启动握手时序问题，完善发布门禁；
- 修复架构审查发现的质量门禁缺陷；
- 修复首次激活流程中的测试密钥误报。

## [0.7.0-alpha.7] — 2026-07-15

- 统一产品版本与发布门禁。

## [0.7.0-alpha.6] — 2026-07-15

- 完善云端预算限制与发布运维链路。

## [0.7.0-alpha.5] — 2026-07-15

- 提升 Cloud Beta 发布链路的稳定性。

## [0.7.0-alpha.4] — 2026-07-14

- 桌面端接入云端生成与隐私控制。

## [0.7.0-alpha.3] — 2026-07-14

- 打通云端生成与质量分析。

## [0.7.0-alpha.2] — 2026-07-14

- 新增云端免费额度记录；
- 打通反馈与云端管理；
- 兼容 MiniMax 流式结束事件，修复前端历史查询与 Runtime 协议错位。

## [0.6.0-beta.11] — 2026-07-13

- 接入视图缩放与窗口控制；
- 收紧窗口与浮层交互密度。

> 0.6.0-beta.2 至 beta.10 为持续打磨的中间补丁版本，变更从略；
> 0.7.0-alpha.1 的变更并入 alpha.2 发布。

## [0.6.0-beta.7] — 2026-07-13

- 重做模板管理视觉与交互层级；
- 统一主界面与模板编辑视觉体验。

## [0.6.0-beta.4] — 2026-07-13

- 接入语义模型管理界面并补齐后端；
- 提升插件桥接稳定性与错误提示质量。

## [0.6.0-beta.1] — 2026-07-12

- 首个 beta 基线：Core、Provider 插件、模板包、L0 场景识别与 Tauri 桌面宿主。

[Unreleased]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.8...HEAD
[0.7.0-alpha.8]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.7...v0.7.0-alpha.8
[0.7.0-alpha.7]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.6...v0.7.0-alpha.7
[0.7.0-alpha.6]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.5...v0.7.0-alpha.6
[0.7.0-alpha.5]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.4...v0.7.0-alpha.5
[0.7.0-alpha.4]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.3...v0.7.0-alpha.4
[0.7.0-alpha.3]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.7.0-alpha.2...v0.7.0-alpha.3
[0.7.0-alpha.2]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.6.0-beta.11...v0.7.0-alpha.2
[0.6.0-beta.11]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.6.0-beta.7...v0.6.0-beta.11
[0.6.0-beta.7]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.6.0-beta.4...v0.6.0-beta.7
[0.6.0-beta.4]: https://github.com/DOIT-Ben/Reflex-Next/compare/v0.6.0-beta.1...v0.6.0-beta.4
[0.6.0-beta.1]: https://github.com/DOIT-Ben/Reflex-Next/releases/tag/v0.6.0-beta.1
