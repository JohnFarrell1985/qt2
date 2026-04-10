"""合成策略/标的池/宏观种子数据

Tables: strategy, instrument_pool, strategy_allocation, macro_state_log
"""
import json
from datetime import date, datetime

from src.data.models import (
    Strategy, InstrumentPool, StrategyAllocation, MacroStateLog,
)


def create_strategies(session) -> list[Strategy]:
    strategies = [
        Strategy(
            strategy_name="momentum_v1",
            strategy_tier="rule",
            strategy_class="momentum",
            config_json=json.dumps({"lookback": 20, "top_n": 10}),
            description="20日动量选股",
            factor_names_json=json.dumps(["mom_20"]),
            status="active",
            applicable_macro="bull,recovery",
            backtest_sharpe=1.35,
            backtest_annual_return=28.5,
            backtest_max_drawdown=-12.3,
            ic_mean=0.045,
            icir=0.62,
        ),
        Strategy(
            strategy_name="low_vol_dividend_v1",
            strategy_tier="rule",
            strategy_class="low_vol_dividend",
            config_json=json.dumps({"vol_window": 60, "div_yield_min": 0.03}),
            description="低波红利",
            factor_names_json=json.dumps(["vol_20"]),
            status="active",
            applicable_macro="bear,shock",
            backtest_sharpe=0.95,
            backtest_annual_return=15.2,
            backtest_max_drawdown=-8.5,
            ic_mean=0.032,
            icir=0.48,
        ),
        Strategy(
            strategy_name="lgb_multi_factor",
            strategy_tier="ml",
            strategy_class="",
            config_json=json.dumps({"n_estimators": 500, "learning_rate": 0.05}),
            description="LightGBM 多因子",
            factor_names_json=json.dumps(["mom_20", "vol_20", "rsi_14",
                                          "turnover_avg_20", "amplitude_20"]),
            model_params_json=json.dumps({"num_leaves": 31, "max_depth": 6}),
            status="active",
            applicable_macro="",
            backtest_sharpe=1.72,
            backtest_annual_return=35.6,
            backtest_max_drawdown=-15.1,
            ic_mean=0.058,
            icir=0.81,
        ),
        Strategy(
            strategy_name="reversal_v1",
            strategy_tier="rule",
            strategy_class="reversal",
            config_json=json.dumps({"lookback": 5, "threshold": -5.0}),
            description="短期反转策略",
            factor_names_json=json.dumps(["mom_20", "rsi_14"]),
            status="paused",
            applicable_macro="shock",
            backtest_sharpe=0.78,
            backtest_annual_return=12.0,
            backtest_max_drawdown=-18.7,
        ),
    ]
    session.add_all(strategies)
    session.flush()
    return strategies


def create_instrument_pools(session, stocks: list) -> list[InstrumentPool]:
    all_codes = [s.code for s in stocks]
    uptrend_codes = [s.code for s in stocks if int(s.code[:6]) <= 10]
    low_vol_codes = [s.code for s in stocks if int(s.code[:6]) >= 41]

    pools = [
        InstrumentPool(
            pool_name="全市场",
            description="全部50只合成股票",
            codes_json=json.dumps(all_codes),
            n_stocks=len(all_codes),
            status="active",
        ),
        InstrumentPool(
            pool_name="上涨池",
            description="稳定上涨股 (000001~000010)",
            codes_json=json.dumps(uptrend_codes),
            n_stocks=len(uptrend_codes),
            status="active",
        ),
        InstrumentPool(
            pool_name="低波红利池",
            description="低波稳定股 (000041~000050)",
            codes_json=json.dumps(low_vol_codes),
            n_stocks=len(low_vol_codes),
            status="active",
        ),
    ]
    session.add_all(pools)
    session.flush()
    return pools


def create_strategy_allocations(
    session, strategies: list[Strategy], pools: list[InstrumentPool],
) -> list[StrategyAllocation]:
    strat_map = {s.strategy_name: s.id for s in strategies}
    pool_map = {p.pool_name: p.id for p in pools}

    allocations = [
        StrategyAllocation(
            strategy_id=strat_map["momentum_v1"],
            pool_id=pool_map["上涨池"],
            macro_state="bull",
            weight=0.4,
            is_active="true",
        ),
        StrategyAllocation(
            strategy_id=strat_map["low_vol_dividend_v1"],
            pool_id=pool_map["低波红利池"],
            macro_state="bear",
            weight=0.6,
            is_active="true",
        ),
        StrategyAllocation(
            strategy_id=strat_map["lgb_multi_factor"],
            pool_id=pool_map["全市场"],
            macro_state="",
            weight=1.0,
            is_active="true",
        ),
    ]
    session.add_all(allocations)
    session.flush()
    return allocations


def create_macro_state_log(session) -> list[MacroStateLog]:
    logs = [
        MacroStateLog(
            state_key="recovery",
            state_detail_json=json.dumps({
                "gdp_growth": 5.2, "pmi": 51.3, "cpi": 1.8,
                "m2_growth": 9.5, "reason": "PMI连续3月>50",
            }),
            determined_by="rule_based",
            effective_date=date(2024, 1, 2),
        ),
        MacroStateLog(
            state_key="bull",
            state_detail_json=json.dumps({
                "gdp_growth": 5.5, "pmi": 52.1, "cpi": 2.0,
                "m2_growth": 10.2, "reason": "经济指标持续向好",
            }),
            determined_by="rule_based",
            effective_date=date(2024, 4, 1),
        ),
        MacroStateLog(
            state_key="shock",
            state_detail_json=json.dumps({
                "gdp_growth": 4.8, "pmi": 49.8, "cpi": 2.5,
                "m2_growth": 8.9, "reason": "PMI跌破荣枯线",
            }),
            determined_by="rule_based",
            effective_date=date(2024, 7, 1),
        ),
    ]
    session.add_all(logs)
    session.flush()
    return logs
