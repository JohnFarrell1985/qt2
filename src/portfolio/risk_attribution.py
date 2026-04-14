"""简化 Barra 风险归因

P1-06: 5 个风格因子 + 行业哑变量的横截面回归.
将组合收益分解为: alpha + 风格贡献 + 行业贡献 + 残差.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.common.logger import get_logger

logger = get_logger(__name__)

try:
    import statsmodels.api as sm

    _USE_STATSMODELS = True
except ImportError:
    _USE_STATSMODELS = False

STYLE_FACTORS = ["size", "value", "momentum", "volatility", "liquidity"]

_MOMENTUM_WINDOW = 20
_VOL_WINDOW = 20


def _zscore(s: pd.Series) -> pd.Series:
    """横截面 z-score, 处理零标准差."""
    std = s.std()
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


class RiskAttributor:
    """简化 Barra 风格因子 + 行业归因.

    因子定义
    --------
    - size: ln(market_cap), z-scored
    - value: 1/pb_ratio, z-scored
    - momentum: 20 日收益率, z-scored
    - volatility: 20 日收益率标准差, z-scored
    - liquidity: 20 日平均换手率, z-scored (若无换手数据则置零)
    """

    def compute_factor_exposures(
        self,
        prices: pd.DataFrame,
        market_caps: pd.Series,
        industries: pd.Series,
        pb_ratios: pd.Series,
        turnover: pd.Series | None = None,
    ) -> pd.DataFrame:
        """计算一个截面上各股票的风格因子暴露.

        Parameters
        ----------
        prices : pd.DataFrame
            行 = 日期 (升序), 列 = 股票代码.
        market_caps : pd.Series
            index = 股票代码, value = 总市值.
        industries : pd.Series
            index = 股票代码, value = 行业名称.
        pb_ratios : pd.Series
            index = 股票代码, value = PB (市净率).
        turnover : pd.Series | None
            index = 股票代码, value = 20 日平均换手率.

        Returns
        -------
        pd.DataFrame
            index = 股票代码, columns = STYLE_FACTORS.
        """
        stocks = list(prices.columns)
        exposures = pd.DataFrame(index=stocks, columns=STYLE_FACTORS, dtype=float)

        valid_caps = market_caps.reindex(stocks).fillna(market_caps.median())
        valid_caps = valid_caps.clip(lower=1.0)
        exposures["size"] = _zscore(np.log(valid_caps))

        valid_pb = pb_ratios.reindex(stocks).fillna(pb_ratios.median())
        valid_pb = valid_pb.clip(lower=0.01)
        exposures["value"] = _zscore(1.0 / valid_pb)

        if prices.shape[0] >= _MOMENTUM_WINDOW:
            mom = prices.iloc[-1] / prices.iloc[-_MOMENTUM_WINDOW] - 1.0
        else:
            mom = prices.iloc[-1] / prices.iloc[0] - 1.0
        exposures["momentum"] = _zscore(mom.reindex(stocks).fillna(0.0))

        if prices.shape[0] >= _VOL_WINDOW:
            daily_ret = prices.pct_change().iloc[-_VOL_WINDOW:]
        else:
            daily_ret = prices.pct_change().dropna()
        vol = daily_ret.std()
        exposures["volatility"] = _zscore(vol.reindex(stocks).fillna(vol.median()))

        if turnover is not None:
            liq = turnover.reindex(stocks).fillna(turnover.median())
        else:
            liq = pd.Series(0.0, index=stocks)
        exposures["liquidity"] = _zscore(liq)

        return exposures.astype(float)

    def attribute_returns(
        self,
        portfolio_returns: pd.Series,
        factor_exposures: pd.DataFrame,
        industry_dummies: pd.DataFrame,
    ) -> dict:
        """横截面 OLS 归因: R = α + Σ(β_style × Style) + Σ(β_ind × Ind) + ε.

        Parameters
        ----------
        portfolio_returns : pd.Series
            index = 股票代码, value = 当期收益率.
        factor_exposures : pd.DataFrame
            index = 股票代码, columns = STYLE_FACTORS.
        industry_dummies : pd.DataFrame
            index = 股票代码, columns = 行业名称, value = 0/1.

        Returns
        -------
        dict
            alpha, style, industry, residual_std, r_squared.
        """
        common = portfolio_returns.index.intersection(factor_exposures.index)
        common = common.intersection(industry_dummies.index)
        if len(common) < 3:
            logger.warning("可用截面样本数 < 3, 归因不可靠")
            return {
                "alpha": 0.0,
                "style": {f: 0.0 for f in STYLE_FACTORS},
                "industry": {},
                "residual_std": 0.0,
                "r_squared": 0.0,
            }

        y = portfolio_returns.loc[common].values.astype(float)
        x_style = factor_exposures.loc[common].values.astype(float)
        x_ind = industry_dummies.loc[common].values.astype(float)
        x_full = np.column_stack([x_style, x_ind])

        if _USE_STATSMODELS:
            x_with_const = sm.add_constant(x_full)
            model = sm.OLS(y, x_with_const).fit()
            alpha = float(model.params[0])
            betas = model.params[1:]
            r_squared = float(model.rsquared)
            residual_std = float(np.std(model.resid, ddof=1)) if len(model.resid) > 1 else 0.0
        else:
            from sklearn.linear_model import LinearRegression

            reg = LinearRegression(fit_intercept=True)
            reg.fit(x_full, y)
            alpha = float(reg.intercept_)
            betas = reg.coef_
            r_squared = float(reg.score(x_full, y))
            resid = y - reg.predict(x_full)
            residual_std = float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0

        style_names = list(factor_exposures.columns)
        industry_names = list(industry_dummies.columns)
        n_style = len(style_names)

        style_contrib = {}
        for i, name in enumerate(style_names):
            style_contrib[name] = float(betas[i])

        industry_contrib = {}
        for i, name in enumerate(industry_names):
            industry_contrib[name] = float(betas[n_style + i])

        return {
            "alpha": alpha,
            "style": style_contrib,
            "industry": industry_contrib,
            "residual_std": residual_std,
            "r_squared": max(0.0, min(r_squared, 1.0)),
        }

    def generate_report(self, attribution: dict) -> dict:
        """将归因结果格式化为结构化报告.

        Returns
        -------
        dict
            summary, top_style_factors, top_industries, risk_metrics.
        """
        style = attribution.get("style", {})
        industry = attribution.get("industry", {})

        sorted_style = sorted(style.items(), key=lambda x: abs(x[1]), reverse=True)
        sorted_industry = sorted(industry.items(), key=lambda x: abs(x[1]), reverse=True)

        total_style = sum(abs(v) for v in style.values())
        total_industry = sum(abs(v) for v in industry.values())

        return {
            "summary": {
                "alpha": attribution["alpha"],
                "total_style_contribution": total_style,
                "total_industry_contribution": total_industry,
                "residual_std": attribution["residual_std"],
                "r_squared": attribution["r_squared"],
            },
            "top_style_factors": sorted_style[:5],
            "top_industries": sorted_industry[:5],
            "risk_metrics": {
                "idiosyncratic_risk": attribution["residual_std"],
                "explained_variance_pct": attribution["r_squared"] * 100,
            },
        }
