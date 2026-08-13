# 场景模板外部吸收来源（长期机制）

本文件登记场景库（`template-packs/builtin/`）从开源社区吸收角色定义与提示词资产的
来源、许可、筛选标准与更新流程。**以后扩展场景时，先查本清单再动手。**

## 吸收原则

1. **只吸收方法论，不复制原文**：开源角色多为对话式人格定义，场景模板须提炼其
   "评审维度/工作方法/输出结构"，改写成我们的场景模板格式（描述/重点/优化指导/风格指导）；
2. **许可合规**：只从许可明确且允许衍生的来源吸收；模板文件头部不复制来源原文，
   本文件登记来源与许可，避免版权与授权风险；
3. **可追溯**：每个来源登记仓库、许可、获取方式；扩展场景时在本文件追加记录；
4. **边界**：不吸收涉及医疗诊断、法律意见、金融投资建议等高风险领域角色；
   不吸收娱乐/角色扮演类（与产品定位无关）；不吸收任何违反平台政策的内容。

## 来源清单

### 1. awesome-chatgpt-prompts-zh（PlexPt）

- 仓库：https://github.com/PlexPt/awesome-chatgpt-prompts-zh
- 许可：MIT（prompt 内容与代码）
- 获取：`prompts-zh.json`（结构 `{act, prompt}`，约 124 条中文角色）
- 已吸收（2026-08-14）：
  - 招聘人员 / 职业顾问 → `resume`（简历优化）
  - 求职信 → `cover_letter`（求职信）
  - 面试官 → `interview`（面试准备）
  - 花哨的标题生成器 → `headline`（标题创作）
  - 销售员 / 广告商 → `sales_script`（销售话术）
  - 励志演讲者 → `speech`（演讲致辞）
  - 产品经理 → `prd`（产品需求文档）

### 2. awesome-chatgpt-prompts（f/awesome-chatgpt-prompts）

- 仓库：https://github.com/f/awesome-chatgpt-prompts
- 许可：prompt 内容 CC0，代码 MIT
- 获取：`prompts.csv`（数千条英文角色）
- 状态：**未吸收**（候选来源，扩展英文场景或补充方法论时使用）

### 3. anthropics/skills（Anthropic 官方）

- 仓库：https://github.com/anthropics/skills
- 许可：Apache 2.0（docx/pdf/pptx/xlsx 四个文档技能为 source-available）
- 价值：`SKILL.md` 结构范式（`name`/`description` frontmatter + 指令正文），
  可作为场景模板 schema 未来升级参照（模板结构升级时对照）
- 状态：**未吸收内容**（结构参照）

### 4. agency-swarm（VRSEN）

- 仓库：https://github.com/VRSEN/agency-swarm
- 许可：MIT
- 价值：多智能体编排框架，角色用 Python `Agent` 类定义——与本项目模板体系
  形态不同，仅作框架参照
- 状态：**未吸收**

## 扩展场景流程（以后新增场景时）

1. 查本文件来源清单，确认候选角色/技能归属与许可；
2. 按"吸收原则 1"提炼方法论 → 写 `content/<scene_id>/scene.md`（项目模板格式）；
3. 更新 `manifest.json`（scenes 数组加 `{id, path, category}`，分类从十大一级分类中选）；
4. 更新 `packages/reflex-core/src/reflex_core/scene/detectors.py`（`_SCENE_RULES` 加
   `(category, scene_id, markers)`，注意与既有规则的匹配顺序）；
5. 更新测试（`test_template_pack.py` 的 EXPECTED_SCENES、`test_scene_detector.py` 的 SCENE_CASES）；
6. 本文件追加吸收记录（场景 → 来源角色 → 来源仓库）。
