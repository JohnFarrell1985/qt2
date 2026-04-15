"""进化式因子挖掘 (P2-23)

QuantaAlpha 风格: LLM 生成因子假设 → 代码 → 沙箱回测 → IC 门控 → 进化

参考: QuantaAlpha (arXiv:2602.07085), FactorEngine (arXiv:2603.16365)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FactorIndividual:
    """进化种群中的个体"""
    hypothesis: str = ""
    code: str = ""
    parent_code: str = ""
    metrics: Dict[str, float] = field(default_factory=dict)
    generation: int = 0


class EvolutionaryFactorMiner:
    """QuantaAlpha 风格进化式因子挖掘

    核心流程:
    1. LLM 生成因子代码 (可降级为规则模板)
    2. 沙箱回测: IC/ICIR 评估
    3. IC 门控 (> 0.03)
    4. 选择 + 变异 + 交叉 → 下一代
    """

    def __init__(
        self,
        llm_client=None,
        sandbox=None,
        ic_threshold: float = 0.03,
    ):
        self.llm = llm_client
        self.sandbox = sandbox
        self.ic_threshold = ic_threshold
        self._rng = np.random.default_rng(42)

    def mine(
        self,
        n_generations: int = 10,
        population_size: int = 20,
    ) -> List[FactorIndividual]:
        """执行进化搜索

        Args:
            n_generations: 进化代数
            population_size: 种群大小

        Returns:
            最终保留的优秀因子列表
        """
        population = self._init_population(population_size)

        for gen in range(n_generations):
            for ind in population:
                if not ind.code:
                    ind.code = self._generate_code(ind.hypothesis, ind.parent_code)

                if self.sandbox:
                    ind.metrics = self.sandbox.evaluate(ind.code)
                else:
                    ind.metrics = self._mock_evaluate()

            population = [
                i for i in population
                if i.metrics.get("ic", 0) > self.ic_threshold
            ]

            if not population:
                logger.warning("第 %d 代: 无因子通过 IC 门控, 重新初始化", gen + 1)
                population = self._init_population(population_size)
                continue

            parents = self._select_top(population, k=max(1, population_size // 2))
            offspring = self._crossover_mutate(parents, gen + 1)
            population = parents + offspring

            best = max(population, key=lambda i: i.metrics.get("ic", 0))
            logger.info(
                "第 %d 代: %d 个体, 最佳 IC=%.4f",
                gen + 1, len(population), best.metrics.get("ic", 0),
            )

        return self._select_top(population, k=5)

    def _init_population(self, size: int) -> List[FactorIndividual]:
        templates = [
            "收盘价 {w}日均线偏离度",
            "成交量 {w}日变化率",
            "换手率 {w}日波动率",
            "量价相关性 {w}日窗口",
            "收益率 {w}日偏度",
        ]
        population = []
        for i in range(size):
            tmpl = templates[i % len(templates)]
            w = int(self._rng.choice([5, 10, 20, 60]))
            population.append(FactorIndividual(
                hypothesis=tmpl.format(w=w),
                generation=0,
            ))
        return population

    def _generate_code(self, hypothesis: str, parent_code: str = "") -> str:
        if self.llm:
            try:
                return self.llm.generate(
                    f"将以下因子假设转为 Python 函数:\n{hypothesis}\n"
                    f"函数签名: def compute_factor(df: pd.DataFrame) -> pd.Series"
                )
            except Exception:
                pass
        return f"# {hypothesis}\ndef compute_factor(df):\n    return df['close'].pct_change(20)"

    def _mock_evaluate(self) -> Dict[str, float]:
        return {
            "ic": float(self._rng.normal(0.03, 0.02)),
            "icir": float(self._rng.normal(0.3, 0.15)),
        }

    @staticmethod
    def _select_top(population: List[FactorIndividual], k: int) -> List[FactorIndividual]:
        return sorted(population, key=lambda i: i.metrics.get("ic", 0), reverse=True)[:k]

    def _crossover_mutate(
        self, parents: List[FactorIndividual], gen: int,
    ) -> List[FactorIndividual]:
        offspring = []
        for p in parents:
            child = FactorIndividual(
                hypothesis=f"变异: {p.hypothesis}",
                parent_code=p.code,
                generation=gen,
            )
            offspring.append(child)
        return offspring
