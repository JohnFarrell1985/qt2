"""绩效统计模块

夏普比率、Calmar比率、最大回撤、Sortino比率、年化收益、月度收益表、
Deflated Sharpe Ratio (多重检验修正)。

P2-03 增强: 滚动 Sharpe、Bootstrap 显著性、信息比率 (IR)、Tracking Error
P2-05 增强: 年化换手率、交易成本归因、扣费后 Sharpe
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


def rolling_sharpe(
    equity_curve: List[Dict],
    window: int = 60,
    risk_free_rate: float = 0.03,
) -> pd.Series:
    """滚动 Sharpe 比率 (P2-03)

    Args:
        equity_curve: 净值曲线
        window: 滚动窗口大小 (交易日)
        risk_free_rate: 年化无风险利率

    Returns:
        Series — index=date, values=rolling_sharpe
    """
    returns = calc_returns(equity_curve)
    if len(returns) < window:
        return pd.Series(dtype=float)
    daily_rf = risk_free_rate / 252
    excess = returns - daily_rf
    rolling_mean = excess.rolling(window).mean() * 252
    rolling_vol = returns.rolling(window).std() * np.sqrt(252)
    rs = rolling_mean / rolling_vol.replace(0, np.nan)
    return rs.dropna().round(4)


def rolling_alpha(
    equity_curve: List[Dict],
    benchmark_curve: List[Dict],
    window: int = 60,
) -> pd.Series:
    """滚动 Alpha (P2-03)

    使用单因子模型: r_strategy - rf = α + β(r_bench - rf) + ε
    """
    strat_ret = calc_returns(equity_curve)
    bench_ret = calc_returns(benchmark_curve)
    if len(strat_ret) < window or len(bench_ret) < window:
        return pd.Series(dtype=float)

    aligned = pd.DataFrame({"strat": strat_ret, "bench": bench_ret}).dropna()
    if len(aligned) < window:
        return pd.Series(dtype=float)

    alphas = []
    for i in range(window, len(aligned) + 1):
        chunk = aligned.iloc[i - window: i]
        cov = np.cov(chunk["strat"], chunk["bench"])
        beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 0 else 0
        alpha = (chunk["strat"].mean() - beta * chunk["bench"].mean()) * 252
        alphas.append((aligned.index[i - 1], alpha))

    return pd.Series(
        dict(alphas), dtype=float,
    ).round(4)


def bootstrap_sharpe_pvalue(
    equity_curve: List[Dict],
    n_bootstrap: int = 1000,
    risk_free_rate: float = 0.03,
) -> float:
    """Bootstrap 显著性检验 — Sharpe > 0 的 p-value (P2-03)

    非参数 bootstrap: 重采样日收益率序列, 计算每次的 Sharpe,
    p-value = 比例 of bootstrap Sharpe <= 0
    """
    returns = calc_returns(equity_curve)
    if len(returns) < 20:
        return 1.0

    rng = np.random.default_rng(42)
    n = len(returns)
    ret_arr = returns.values
    daily_rf = risk_free_rate / 252

    count_negative = 0
    for _ in range(n_bootstrap):
        sample = rng.choice(ret_arr, size=n, replace=True)
        excess = sample - daily_rf
        bs_sharpe = excess.mean() / sample.std() * np.sqrt(252) if sample.std() > 0 else 0
        if bs_sharpe <= 0:
            count_negative += 1

    return round(count_negative / n_bootstrap, 4)


def information_ratio(
    equity_curve: List[Dict],
    benchmark_curve: List[Dict],
) -> Dict[str, float]:
    """信息比率 IR 与 Tracking Error (P2-03)

    IR = (年化超额收益) / Tracking Error
    TE = std(日超额收益) × √252
    """
    strat_ret = calc_returns(equity_curve)
    bench_ret = calc_returns(benchmark_curve)
    aligned = pd.DataFrame({"strat": strat_ret, "bench": bench_ret}).dropna()

    if len(aligned) < 20:
        return {"ir": 0.0, "tracking_error": 0.0, "annualized_excess_return": 0.0}

    excess = aligned["strat"] - aligned["bench"]
    ann_excess = excess.mean() * 252
    te = excess.std() * np.sqrt(252)
    ir = ann_excess / te if te > 0 else 0.0

    return {
        "ir": _safe_float(round(ir, 4)),
        "tracking_error": _safe_float(round(te * 100, 2)),
        "annualized_excess_return": _safe_float(round(ann_excess * 100, 2)),
    }


def monthly_returns_heatmap(equity_curve: List[Dict]) -> Dict[str, Dict[str, float]]:
    """月度收益热力图数据 (P2-03)

    Returns:
        嵌套 dict: {year: {month: return_pct}}
    """
    mr = monthly_returns(equity_curve)
    if mr.empty:
        return {}

    result: Dict[str, Dict[str, float]] = {}
    for dt, row in mr.iterrows():
        year = str(dt.year)
        month = str(dt.month)
        if year not in result:
            result[year] = {}
        result[year][month] = float(row.iloc[0]) if not np.isnan(row.iloc[0]) else 0.0
    return result


# ======== P2-05: 交易成本归因 ========

def turnover_analysis(
    trades: List[Dict],
    equity_curve: List[Dict],
) -> Dict[str, Any]:
    """年化换手率、交易成本占比、扣费后 Sharpe (P2-05)

    Args:
        trades: 交易记录, 每笔含 amount/fees/direction
        equity_curve: 净值曲线

    Returns:
        cost_attribution dict
    """
    if not trades or len(equity_curve) < 2:
        return {
            "annualized_turnover_pct": 0.0,
            "total_fees": 0.0,
            "gross_return_pct": 0.0,
            "fee_to_gross_pct": 0.0,
            "net_sharpe": 0.0,
            "per_strategy_turnover": {},
        }

    start_cap = equity_curve[0]["capital"]
    days = (pd.Timestamp(equity_curve[-1]["date"]) - pd.Timestamp(equity_curve[0]["date"])).days
    years = max(days / 365.0, 1.0 / 365)

    total_traded = sum(abs(t.get("amount", 0)) for t in trades)
    avg_capital = np.mean([p["capital"] for p in equity_curve])
    ann_turnover = (total_traded / avg_capital / years) if avg_capital > 0 else 0.0

    total_fees = sum(t.get("fees", 0) for t in trades)
    total_slippage = sum(t.get("slippage", 0) for t in trades)
    total_cost = total_fees + total_slippage

    gross_pnl = equity_curve[-1]["capital"] - start_cap + total_cost
    gross_return_pct = gross_pnl / start_cap * 100 if start_cap > 0 else 0.0
    fee_to_gross = total_cost / gross_pnl * 100 if gross_pnl > 0 else 0.0

    net_sr = sharpe_ratio(equity_curve)

    per_strat: Dict[str, float] = {}
    for t in trades:
        s = t.get("strategy_name", "unknown")
        per_strat[s] = per_strat.get(s, 0) + abs(t.get("amount", 0))
    for s in per_strat:
        per_strat[s] = round(per_strat[s] / avg_capital / years * 100, 2) if avg_capital > 0 else 0.0

    return {
        "annualized_turnover_pct": _safe_float(round(ann_turnover * 100, 2)),
        "total_fees": _safe_float(round(total_fees, 2)),
        "total_slippage": _safe_float(round(total_slippage, 2)),
        "gross_return_pct": _safe_float(round(gross_return_pct, 2)),
        "fee_to_gross_pct": _safe_float(round(fee_to_gross, 2)),
        "net_sharpe": _safe_float(net_sr),
        "per_strategy_turnover": per_strat,
    }


def full_performance_report(
    equity_curve: List[Dict],
    trades: List[Dict] = None,
    num_trials: int = None,
    benchmark_curve: List[Dict] = None,
) -> Dict[str, Any]:
    """完整绩效报告

    P2-03 增强: rolling_sharpe, bootstrap_pvalue, monthly_heatmap, IR
    P2-05 增强: turnover_analysis (交易成本归因)
    """
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
        report["cost_attribution"] = turnover_analysis(trades, equity_curve)

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

    returns = calc_returns(equity_curve)
    if len(returns) > 20:
        report["bootstrap_sharpe_pvalue"] = bootstrap_sharpe_pvalue(equity_curve)

    report["monthly_heatmap"] = monthly_returns_heatmap(equity_curve)

    if benchmark_curve:
        report["information_ratio"] = information_ratio(equity_curve, benchmark_curve)

    return report
