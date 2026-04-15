"""论文阅读 → 策略/因子进化 Agent (P2-30)

arXiv 定期扫描 → LLM 解读 → 假设抽取 → 因子代码生成 → 回测

参考: RD-Agent, FactorMiner, QuantEvolve
"""
from __future__ import annotations

from typing import Dict, List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


class PaperReader:
    """arXiv 论文自动阅读与知识抽取"""

    DEFAULT_KEYWORDS = [
        "alpha factor", "quantitative trading", "momentum",
        "sentiment", "A-share", "factor investing",
    ]

    def __init__(self, llm_client=None):
        self.llm = llm_client

    def scan_arxiv(
        self,
        keywords: Optional[List[str]] = None,
        max_results: int = 20,
    ) -> List[Dict]:
        """扫描最新论文"""
        kw = keywords or self.DEFAULT_KEYWORDS
        try:
            import arxiv
            search = arxiv.Search(
                query=" OR ".join(kw),
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
            )
            return [
                {"title": r.title, "abstract": r.summary, "pdf": r.pdf_url}
                for r in search.results()
            ]
        except ImportError:
            logger.warning("arxiv 库未安装, 无法扫描论文。请运行: uv pip install arxiv")
            return []
        except Exception as e:
            logger.error("arXiv 扫描失败: %s", e)
            return []

    def extract_hypotheses(self, paper_text: str) -> List[Dict]:
        """从论文中提取可执行的因子/策略假设"""
        if self.llm is None:
            return []
        try:
            return self.llm.extract(
                prompt=f"""从以下量化金融论文中提取可执行的交易假设:
                {paper_text[:8000]}

                对每个假设输出 JSON:
                - hypothesis: 一句话描述
                - formula: 数学公式 (如有)
                - data_required: 需要的数据字段
                - expected_ic: 论文报告的 IC 值 (如有)
                - market: 适用市场
                """,
            )
        except Exception as e:
            logger.error("假设抽取失败: %s", e)
            return []


class CodeEvolver:
    """论文假设 → 因子代码 → 回测 → 进化"""

    def __init__(self, llm_client=None, sandbox=None, memory=None):
        self.llm = llm_client
        self.sandbox = sandbox
        self.memory = memory

    def evolve_from_paper(self, hypothesis: Dict) -> Optional[Dict]:
        """将论文假设转化为可执行因子"""
        if self.llm is None:
            return None

        try:
            code = self.llm.generate(
                f"将以下金融假设转为 Python 因子函数:\n{hypothesis}\n"
                f"签名: def compute_factor(df: pd.DataFrame) -> pd.Series"
            )

            metrics = {}
            if self.sandbox:
                metrics = self.sandbox.evaluate(code)

            if self.memory:
                self.memory.record(
                    hypothesis.get("hypothesis", "unknown"),
                    code,
                    "accepted" if metrics.get("ic", 0) > 0.03 else "rejected",
                    metrics,
                )

            if metrics.get("ic", 0) > 0.03 and metrics.get("icir", 0) > 0.3:
                return {"code": code, "metrics": metrics, "source": "paper"}
        except Exception as e:
            logger.error("论文→因子转化失败: %s", e)

        return None
