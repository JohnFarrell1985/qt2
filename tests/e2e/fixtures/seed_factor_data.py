"""合成因子数据工厂

5 个因子从合成价格数据直接计算, 保证与行情一致:
- mom_20:  20 日收益率 (动量)
- vol_20:  20 日收益率标准差 (波动率)
- rsi_14:  14 日 RSI (超买超卖)
- turnover_avg_20: 20 日平均换手率 (流动性)
- amplitude_20: 20 日平均振幅 (波动幅度)
"""
from typing import List, Dict
from collections import defaultdict

import numpy as np

from src.data.models import FactorMeta, FactorValue, StockDaily


FACTOR_DEFS = [
    ("mom_20", "momentum", "20日收益率"),
    ("vol_20", "volatility", "20日收益率标准差"),
    ("rsi_14", "oscillator", "14日RSI"),
    ("turnover_avg_20", "liquidity", "20日平均换手率"),
    ("amplitude_20", "volatility", "20日平均振幅"),
]


def create_factor_meta(session) -> List[FactorMeta]:
    metas = []
    for name, cat, desc in FACTOR_DEFS:
        fm = FactorMeta(
            factor_name=name,
            category=cat,
            description=desc,
            data_source="calculated",
        )
        metas.append(fm)
    session.add_all(metas)
    session.flush()
    return metas


def create_factor_values(
    session,
    stocks: list,
    trading_dates: list,
    daily_data: List[StockDaily],
) -> List[FactorValue]:
    daily_by_code: Dict[str, list] = defaultdict(list)
    for row in daily_data:
        daily_by_code[row.code].append(row)
    for code in daily_by_code:
        daily_by_code[code].sort(key=lambda r: r.trade_date)

    factor_meta_map = {}
    for fm in session.query(FactorMeta).all():
        factor_meta_map[fm.factor_name] = fm.factor_id

    all_fv: List[FactorValue] = []
    dates_list = [td.trade_date for td in trading_dates]

    for code, rows in daily_by_code.items():
        closes = np.array([r.close for r in rows], dtype=float)
        turnovers = np.array([r.turnover_rate or 0.0 for r in rows], dtype=float)
        amplitudes = np.array([r.amplitude or 0.0 for r in rows], dtype=float)

        for j in range(20, len(rows)):
            trade_date = rows[j].trade_date

            mom_20 = float((closes[j] / closes[j - 20] - 1) * 100) if closes[j - 20] > 0 else 0.0
            rets = np.diff(closes[j - 20:j + 1]) / closes[j - 20:j]
            vol_20 = float(np.std(rets) * 100) if len(rets) > 0 else 0.0
            turnover_avg = float(np.mean(turnovers[j - 19:j + 1]))
            amp_avg = float(np.mean(amplitudes[j - 19:j + 1]))
            rsi = float(_calc_rsi(closes[:j + 1], 14))

            for fname, value in [
                ("mom_20", mom_20),
                ("vol_20", vol_20),
                ("rsi_14", rsi),
                ("turnover_avg_20", turnover_avg),
                ("amplitude_20", amp_avg),
            ]:
                fid = factor_meta_map.get(fname)
                if fid is None:
                    continue
                all_fv.append(FactorValue(
                    trade_date=trade_date,
                    code=code,
                    factor_id=fid,
                    value=round(value, 6),
                ))

    session.bulk_save_objects(all_fv)
    session.flush()
    return all_fv


def _calc_rsi(prices: np.ndarray, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))
