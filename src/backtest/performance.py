"""绩效统计模块

夏普比率、Calmar比率、最大回撤、Sortino比率、年化收益、月度收益表、
Deflated Sharpe Ratio (多重检验修正)。
"""
import math

import numpy as np
import pandas as pd
from typing import Dict, Any, List


def calc_returns(equity_curve: List[Dict]) -> pd.Series:
    """从净值曲线计算日收益率序列"""
    if not equity_curve:
        return pd.Series(dtype=float)
    df = pd.DataFrame(equity_curve)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df["capital"].pct_change().dropna()


def annualized_return(equity_curve: List[Dict]) -> float:
    """年化收益率"""
    if len(equity_curve) < 2:
        return 0.0
    start_cap = equity_curve[0]["capital"]
    end_cap = equity_curve[-1]["capital"]
    days = (pd.Timestamp(equity_curve[-1]["date"]) - pd.Timestamp(equity_curve[0]["date"])).days
    if days <= 0 or start_cap <= 0:
        return 0.0
    return ((end_cap / start_cap) ** (365.0 / days) - 1) * 100


def max_drawdown(equity_curve: List[Dict]) -> Dict[str, Any]:
    """最大回撤"""
    if len(equity_curve) < 2:
        return {"max_drawdown_pct": 0.0, "peak_date": None, "trough_date": None}

    capitals = [p["capital"] for p in equity_curve]
    dates = [p["date"] for p in equity_curve]

    peak = capitals[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_peak_idx = 0
    max_dd_trough_idx = 0

    for i in range(1, len(capitals)):
        if capitals[i] > peak:
            peak = capitals[i]
            peak_idx = i
        dd = (peak - capitals[i]) / peak * 100
        if dd > max_dd:
            max_dd = dd
            max_dd_peak_idx = peak_idx
            max_dd_trough_idx = i

    return {
        "max_drawdown_pct": round(max_dd, 4),
        "peak_date": dates[max_dd_peak_idx],
        "trough_date": dates[max_dd_trough_idx],
    }


def sharpe_ratio(equity_curve: List[Dict], risk_free_rate: float = 0.03) -> float:
    """夏普比率 (年化)

    Sharpe = (年化收益 - 无风险利率) / 年化波动率
    """
    returns = calc_returns(equity_curve)
    if len(returns) < 5:
        return 0.0
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    if ann_vol == 0:
        return 0.0
    return round((ann_ret - risk_free_rate) / ann_vol, 4)


def sortino_ratio(equity_curve: List[Dict], risk_free_rate: float = 0.03) -> float:
    """Sortino比率 (仅考虑下行波动率)"""
    returns = calc_returns(equity_curve)
    if len(returns) < 5:
        return 0.0
    ann_ret = returns.mean() * 252
    downside = returns[returns < 0]
    if len(downside) == 0:
        return 0.0
    downside_vol = downside.std() * np.sqrt(252)
    if downside_vol == 0:
        return 0.0
    return round((ann_ret - risk_free_rate) / downside_vol, 4)


def calmar_ratio(equity_curve: List[Dict]) -> float:
    """Calmar比率 = 年化收益率 / 最大回撤"""
    ann_ret = annualized_return(equity_curve)
    dd = max_drawdown(equity_curve)["max_drawdown_pct"]
    if dd == 0:
        return 0.0
    return round(ann_ret / dd, 4)


def win_rate(trades: List[Dict]) -> float:
    """胜率"""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("profit", 0) > 0)
    return round(wins / len(trades) * 100, 2)


def profit_loss_ratio(trades: List[Dict]) -> float:
    """盈亏比 = 平均盈利 / 平均亏损"""
    wins = [t["profit"] for t in trades if t.get("profit", 0) > 0]
    losses = [abs(t["profit"]) for t in trades if t.get("profit", 0) < 0]
    if not wins or not losses:
        return 0.0
    return round(np.mean(wins) / np.mean(losses), 4)


def monthly_returns(equity_curve: List[Dict]) -> pd.DataFrame:
    """月度收益表"""
    if not equity_curve:
        return pd.DataFrame()
    df = pd.DataFrame(equity_curve)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    monthly = df["capital"].resample("ME").last().pct_change() * 100
    result = pd.DataFrame({"monthly_return_pct": monthly.round(2)})
    return result


def _safe_float(v: float) -> float:
    """Replace inf/nan with 0.0 for JSON serialization safety."""
    if isinstance(v, float) and (np.isinf(v) or np.isnan(v)):
        return 0.0
    return v


def expected_max_sharpe(num_trials: int, var_sharpe: float) -> float:
    """Expected maximum Sharpe ratio under null hypothesis (all trials random).

    E[max(SR)] ≈ sqrt(2·ln(N))·σ_SR − (γ·σ_SR) / sqrt(2·ln(N))
    where σ_SR = sqrt(var_sharpe), N = num_trials, γ = Euler-Mascheroni.

    Reference: Bailey & López de Prado (2014)
    """
    if num_trials <= 1 or var_sharpe <= 0:
        return 0.0
    sigma_sr = math.sqrt(var_sharpe)
    z = math.sqrt(2.0 * math.log(num_trials))
    euler_gamma = 0.5772156649015329
    return z * sigma_sr - (euler_gamma * sigma_sr) / z


def deflated_sharpe_ratio(
    observed_sharpe: float,
    num_trials: int,
    var_sharpe: float,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    T: int = 252,
) -> float:
    """Deflated Sharpe Ratio — p-value adjusted for multiple testing.

    Returns p-value: probability that observed Sharpe is due to luck.
    p < 0.05 → strategy likely has real alpha.

    Reference: Bailey & López de Prado (2014), Journal of Portfolio Management
    """
    from scipy.stats import norm

    if num_trials <= 0 or T <= 1 or var_sharpe <= 0:
        return 1.0

    e_max_sr = expected_max_sharpe(num_trials, var_sharpe)

    sr_std = math.sqrt(
        (1.0 - skewness * observed_sharpe + (kurtosis - 1.0) / 4.0 * observed_sharpe ** 2)
        / (T - 1.0)
    )

    if sr_std <= 0:
        return 1.0

    test_stat = (observed_sharpe - e_max_sr) / sr_std
    return float(norm.cdf(test_stat))


def full_performance_report(
    equity_curve: List[Dict],
    trades: List[Dict] = None,
    num_trials: int = None,
) -> Dict[str, Any]:
    """完整绩效报告"""
    report = {
        "annualized_return_pct": _safe_float(round(annualized_return(equity_curve), 2)),
        "max_drawdown": max_drawdown(equity_curve),
        "sharpe_ratio": _safe_float(sharpe_ratio(equity_curve)),
        "sortino_ratio": _safe_float(sortino_ratio(equity_curve)),
        "calmar_ratio": _safe_float(calmar_ratio(equity_curve)),
    }
    if trades:
        report["win_rate"] = _safe_float(win_rate(trades))
        report["profit_loss_ratio"] = _safe_float(profit_loss_ratio(trades))
        report["total_trades"] = len(trades)

    if num_trials and num_trials > 1:
        sr = report["sharpe_ratio"]
        returns = calc_returns(equity_curve)
        if len(returns) > 5 and sr != 0:
            report["deflated_sharpe_pvalue"] = _safe_float(
                deflated_sharpe_ratio(
                    sr, num_trials, returns.std() ** 2,
                    returns.skew(), returns.kurtosis() + 3,
                    len(returns),
                )
            )

    return report
