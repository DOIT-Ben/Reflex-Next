import pytest

from reflex_core import OptimizeRequest
from reflex_core.scene import GeneralSceneDetector, RuleSceneDetector


SCENE_CASES = (
    ("article_writing", "写一篇公众号文章"),
    ("social_media", "生成一篇小红书文案"),
    ("email", "写一封商务邮件"),
    ("ad_creative", "想一个广告宣传语"),
    ("product_desc", "优化商品详情页的产品描述"),
    ("paper_writing", "润色学术论文摘要"),
    ("code_generation", "def greet(): return 'hello'"),
    ("code_review", "请做一次代码审查"),
    ("bug_fix", "修复这个 bug"),
    ("code_refactor", "重构这段代码"),
    ("tech_doc", "编写 API 技术文档"),
    ("data_analysis", "分析这份数据集的指标"),
    ("market_research", "整理市场调研结果"),
    ("competitor_analysis", "完成竞品分析"),
    ("literature_review", "写一份文献综述"),
    ("trend_prediction", "预测未来行业趋势"),
    ("knowledge_explain", "科普什么是量子纠缠"),
    ("study_plan", "制定 Python 学习计划"),
    ("exam_prep", "制定研究生考试备考方案"),
    ("course_design", "设计一份数学教案"),
    ("homework_help", "辅导这道作业题"),
    ("report_writing", "撰写季度工作报告"),
    ("decision_analysis", "分析两个方案的利弊并辅助决策"),
    ("project_planning", "制定项目里程碑计划"),
    ("process_optimization", "优化现有 SOP 流程"),
    ("meeting_summary", "整理会议纪要"),
    ("story_writing", "创作一个短篇故事"),
    ("script_writing", "编写三分钟短视频剧本"),
    ("poetry_creation", "写一首现代诗"),
    ("game_plot", "设计游戏剧情任务线"),
    ("world_building", "构建一个架空世界观"),
    ("doc_translation", "把这份文档翻译成英文"),
    ("localization", "进行软件本地化适配"),
    ("literary_translation", "完成小说的文学翻译"),
    ("term_unification", "统一全文术语并生成术语表"),
    ("interpreting_notes", "整理同传口译笔记"),
    ("problem_diagnosis", "排查系统故障"),
    ("solution_generation", "为这个问题生成解决方案"),
    ("root_cause", "使用五个为什么分析根因"),
    ("risk_assessment", "制作项目风险矩阵"),
    ("emergency_plan", "编写服务中断应急预案"),
)


def test_rule_scene_detector_recognizes_code_without_optional_dependencies():
    result = RuleSceneDetector().detect("def greet():\n    return 'hello'", OptimizeRequest("input"))
    assert result.scene == "code_generation"
    assert result.method == "rule"


@pytest.mark.parametrize(("expected", "text"), SCENE_CASES)
def test_rule_scene_detector_covers_every_non_general_builtin_scene(expected, text):
    result = RuleSceneDetector().detect(text, OptimizeRequest("input"))

    assert result.scene == expected
    assert result.confidence >= 0.7


def test_rule_scene_detector_falls_back_to_general():
    result = RuleSceneDetector().detect("帮我优化这句话", OptimizeRequest("input"))
    assert result.scene == "general"
    assert result.confidence < 0.5


def test_rule_scene_detector_reports_category_for_every_rule():
    detector = RuleSceneDetector()
    for _, text in SCENE_CASES:
        result = detector.detect(text, OptimizeRequest("input"))
        assert result.scene == _
        assert result.category in {
            "business", "marketing", "market_analysis", "tech_doc", "code",
            "diagnosis", "academic", "education", "creative", "translation",
        }


def test_rule_scene_detector_general_has_general_category():
    result = RuleSceneDetector().detect("帮我优化这句话", OptimizeRequest("input"))
    assert result.scene == "general"
    assert result.category == "general"


def test_general_scene_detector_reports_general_category():
    result = GeneralSceneDetector().detect("anything", OptimizeRequest("input"))
    assert result.scene == "general"
    assert result.category == "general"
