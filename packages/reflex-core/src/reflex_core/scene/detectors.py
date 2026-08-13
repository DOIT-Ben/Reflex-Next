"""Built-in zero-dependency scene detectors."""

from __future__ import annotations

import re

from ..models import OptimizeRequest, SceneDetectionResult

_SCENE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("diagnosis", "emergency_plan", ("应急预案", "应急响应", "故障演练", "contingency plan")),
    ("diagnosis", "risk_assessment", ("风险评估", "风险矩阵", "风险清单", "risk assessment")),
    ("diagnosis", "root_cause", ("根因", "五个为什么", "root cause", "5 whys")),
    ("diagnosis", "solution_generation", ("解决方案", "方案设计", "怎么解决", "solution proposal")),
    ("diagnosis", "problem_diagnosis", ("问题诊断", "排查", "故障", "报错", "异常", "exception", "failed")),
    ("translation", "interpreting_notes", ("口译笔记", "同传", "传译", "interpreting notes")),
    ("translation", "term_unification", ("术语统一", "术语表", "terminology", "glossary")),
    ("translation", "literary_translation", ("文学翻译", "小说翻译", "诗歌翻译", "literary translation")),
    ("translation", "localization", ("本地化适配", "软件本地化", "localization", "localize")),
    ("translation", "doc_translation", ("文档翻译", "翻译文档", "译成", "translate this document")),
    ("creative", "world_building", ("世界观", "设定集", "架空世界", "world building")),
    ("creative", "game_plot", ("游戏剧情", "游戏故事", "任务线", "game plot")),
    ("creative", "poetry_creation", ("现代诗", "诗歌创作", "写一首诗", "写诗", "poetry")),
    ("creative", "script_writing", ("短视频剧本", "剧本", "分镜脚本", "script writing")),
    ("creative", "story_writing", ("短篇故事", "故事创作", "写故事", "小说创作", "story writing")),
    ("business", "meeting_summary", ("会议纪要", "会议总结", "会议记录", "meeting minutes")),
    ("business", "process_optimization", ("流程优化", "优化现有 sop", "工作流优化", "process optimization")),
    ("business", "project_planning", ("项目里程碑", "项目计划", "项目规划", "project plan")),
    ("business", "decision_analysis", ("辅助决策", "决策分析", "方案的利弊", "decision analysis")),
    ("business", "report_writing", ("工作报告", "报告撰写", "汇报材料", "季度报告", "report writing")),
    ("education", "homework_help", ("作业题", "作业辅导", "习题辅导", "homework help")),
    ("education", "course_design", ("课程设计", "教学设计", "教案", "lesson plan")),
    ("education", "exam_prep", ("备考", "考试复习", "考纲", "exam prep")),
    ("education", "study_plan", ("学习计划", "学习路线", "study plan", "learning roadmap")),
    ("academic", "knowledge_explain", ("科普", "解释概念", "知识讲解", "explain the concept")),
    ("market_analysis", "trend_prediction", ("趋势预测", "未来趋势", "行业趋势", "trend prediction")),
    ("academic", "literature_review", ("文献综述", "研究现状", "相关工作", "literature review")),
    ("market_analysis", "competitor_analysis", ("竞品分析", "竞争对手分析", "competitive analysis")),
    ("market_analysis", "market_research", ("市场调研", "市场规模", "用户调研", "market research")),
    ("market_analysis", "data_analysis", ("数据分析", "数据集", "统计分析", "data analysis")),
    ("tech_doc", "tech_doc", ("技术文档", "api 文档", "接口文档", "technical documentation")),
    ("code", "code_review", ("代码审查", "代码评审", "code review", "review this code")),
    ("code", "code_refactor", ("重构这段代码", "代码重构", "refactor")),
    ("code", "bug_fix", ("修复这个 bug", "bug 修复", "修复 bug", "fix this bug")),
    ("academic", "paper_writing", ("学术论文", "论文摘要", "论文写作", "academic paper")),
    ("marketing", "product_desc", ("产品描述", "商品详情", "产品卖点", "product description")),
    ("marketing", "ad_creative", ("广告宣传语", "广告创意", "广告文案", "slogan", "ad copy")),
    ("marketing", "social_media", ("小红书", "社交媒体", "微博文案", "朋友圈文案", "social media")),
    ("marketing", "article_writing", ("公众号文章", "文章写作", "博客文章", "article writing")),
    ("business", "resume", ("简历", "履历", "优化简历", "resume", "cv")),
    ("business", "cover_letter", ("求职信", "自荐信", "cover letter", "求职申请")),
    ("business", "interview", ("面试", "面试准备", "面试问题", "面试话术", "interview")),
    ("marketing", "headline", ("标题", "起标题", "标题生成", "headline", "title")),
    ("marketing", "sales_script", ("销售话术", "推销", "销售脚本", "销售开场白", "sales pitch")),
    ("creative", "speech", ("演讲", "致辞", "演讲稿", "开场白", "speech")),
    ("business", "prd", ("产品需求", "prd", "需求文档", "用户故事", "product requirements")),
    ("business", "email", ("商务邮件", "邮件", "收件人：", "发件人：", "email reply")),
)

_CODE_MARKERS = ("```", "def ", "class ", "function ", "import ", "traceback", ".py", ".js", ".ts", ".rs")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


class RuleSceneDetector:
    """Fast L0 detector with deterministic, zero-dependency rules."""

    def detect(self, text: str, request: OptimizeRequest) -> SceneDetectionResult:
        normalized = text.strip()
        lowered = normalized.lower()

        for category, scene_id, markers in _SCENE_RULES:
            if any(marker in lowered for marker in markers):
                return SceneDetectionResult(
                    scene_id, 0.82, "rule", f"{scene_id}_marker", category
                )
        if _EMAIL_RE.search(normalized):
            return SceneDetectionResult("email", 0.88, "rule", "email_address", "business")
        if any(marker in lowered for marker in _CODE_MARKERS):
            return SceneDetectionResult("code_generation", 0.88, "rule", "code_marker", "code")
        return SceneDetectionResult("general", 0.2, "rule", "no_specific_rule", "general")


class GeneralSceneDetector:
    """Safe fallback detector used when no specialized detector is available."""

    def detect(self, text: str, request: OptimizeRequest) -> SceneDetectionResult:
        return SceneDetectionResult(
            scene="general", confidence=0.0, method="fallback", category="general"
        )
