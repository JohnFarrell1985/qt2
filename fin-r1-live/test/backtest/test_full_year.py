"""
2025全年回测 — 真实数据库行情 + mock选股

使用 PostgreSQL (123.60.11.74:5432/finr1_data) 中的真实 K线数据回测,
只 mock 选股结果 (固定2只股票)。

注意: test/conftest.py 将 DATABASE_URL 覆盖为 localhost 测试库,
本文件的 fixture 会创建独立的真实数据库连接以绕过这个问题。
"""
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from backtest.strategy_runner import (
    run_strategy, run_continuous, StrategyConfig, StrategyResult,
)
from backtest.stock_picker import MockPicker


# ======== 真实数据库配置 ========

REAL_DB_URL = "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"


def _db_available() -> bool:
    """直接创建引擎检测真实数据库连通性, 不依赖 data_loader 模块"""
    try:
        eng = create_engine(REAL_DB_URL, pool_pre_ping=True,
                            connect_args={"connect_timeout": 5})
        with eng.connect() as conn:
            row = conn.execute(text(
                "SELECT COUNT(DISTINCT trade_date) FROM stock_daily "
                "WHERE trade_date >= '2025-01-01' AND trade_date <= '2025-01-31'"
            )).scalar()
        eng.dispose()
        return row is not None and row > 0
    except Exception as e:
        print(f"[test_full_year] DB check failed: {type(e).__name__}: {e}")
        return False


_DB_OK = _db_available()
db_required = pytest.mark.skipif(not _DB_OK, reason="PostgreSQL 不可达或无 2025 年数据")


# ======== fixture: 用真实数据库引擎替换 data_loader 模块级引擎 ========

@pytest.fixture(autouse=True)
def restore_real_db():
    """
    test/conftest.py 把 DATABASE_URL 设成了 localhost 测试库,
    data_loader 模块级 engine 因此指向了错误的地址。
    这里创建指向真实库的 engine/SessionLocal, 替换进 data_loader 模块,
    然后把 strategy_runner 的数据函数也恢复成真实版本。
    """
    import backtest.data_loader as dl

    real_engine = create_engine(
        REAL_DB_URL, poolclass=QueuePool, pool_size=5, pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    real_session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=real_engine,
    )

    old_engine = dl.engine
    old_session = dl.SessionLocal
    dl.engine = real_engine
    dl.SessionLocal = real_session_factory

    with patch("backtest.strategy_runner.get_open_price_exact", new=dl.get_open_price_exact), \
         patch("backtest.strategy_runner.get_trading_dates", new=dl.get_trading_dates), \
         patch("backtest.strategy_runner.get_next_trading_date", new=dl.get_next_trading_date):
        yield

    dl.engine = old_engine
    dl.SessionLocal = old_session
    real_engine.dispose()


# ======== 常量 ========

STOCK_A = "000001"  # 平安银行
STOCK_B = "000002"  # 万科A


# ======== 测试用例 ========

@db_required
class TestTradingCalendar:
    """用数据库真实交易日验证日历逻辑"""

    def test_no_weekends(self):
        """数据库中的交易日不包含周末"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 12, 31))
        for d in dates:
            assert d.weekday() < 5, f"{d} ({d.strftime('%A')}) 是周末"

    def test_approximately_242_trading_days(self):
        """全年约 242 个交易日 (±10)"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 12, 31))
        count = len(dates)
        assert 230 <= count <= 250, f"交易日数量 {count} 不在合理范围"
        print(f"\n  数据库 2025 年交易日数: {count}")

    def test_first_trading_day(self):
        """2025年第一个交易日是1月2日(周四)"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 1, 10))
        assert dates[0] == date(2025, 1, 2)

    def test_spring_festival_gap(self):
        """春节期间无交易日 (约1/28-2/4)"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 28), date(2025, 2, 4))
        assert len(dates) == 0, f"春节期间不应有交易日, 实际: {dates}"

    def test_national_day_gap(self):
        """国庆期间无交易日 (约10/1-10/7)"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 10, 1), date(2025, 10, 7))
        assert len(dates) == 0, f"国庆期间不应有交易日, 实际: {dates}"

    def test_dates_are_sorted(self):
        """交易日严格递增"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 12, 31))
        for i in range(1, len(dates)):
            assert dates[i] > dates[i - 1]

    def test_stock_a_has_data(self):
        """000001 在 2025 年有行情数据"""
        import backtest.data_loader as dl
        data = dl.get_open_price_exact(STOCK_A, date(2025, 1, 2))
        assert data is not None, f"{STOCK_A} 在 2025-01-02 无数据"
        assert data["open"] is not None and data["open"] > 0
        print(f"\n  {STOCK_A} 2025-01-02 开盘价: {data['open']}")

    def test_stock_b_has_data(self):
        """000002 在 2025 年有行情数据"""
        import backtest.data_loader as dl
        data = dl.get_open_price_exact(STOCK_B, date(2025, 1, 2))
        assert data is not None, f"{STOCK_B} 在 2025-01-02 无数据"
        assert data["open"] is not None and data["open"] > 0
        print(f"\n  {STOCK_B} 2025-01-02 开盘价: {data['open']}")


@db_required
class TestFixedAmountPerStock:
    """固定金额买入 (真实数据)"""

    def test_fixed_amount_config(self):
        c = StrategyConfig(fixed_amount_per_stock=100_000)
        assert c.fixed_amount_per_stock == 100_000

    def test_run_strategy_fixed_amount(self):
        """隔日卖出 + 固定 10万/只"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 1, 31))
        schedule = {d: [STOCK_A] for d in dates[:10]}
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(
            initial_capital=1_000_000,
            fixed_amount_per_stock=100_000,
        )
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            config=config,
        )
        assert result.total_trades > 0
        for t in result.trades:
            assert t.buy_amount <= 110_000

    def test_run_continuous_fixed_amount(self):
        """连续持仓 + 固定 10万/只"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 2, 28))
        schedule = {d: [STOCK_A, STOCK_B] for d in dates[:20]}
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(
            initial_capital=1_000_000,
            fixed_amount_per_stock=100_000,
            max_holdings=2,
        )
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 2, 28),
            config=config,
        )
        assert result.total_trades >= 1
        for t in result.trades:
            assert t.buy_amount <= 110_000


@db_required
class TestAutoExit:
    """资金耗尽自动退出 (真实数据)"""

    def test_run_strategy_exits_when_broke(self):
        """初始 500 元, 每只要 10万 → 直接退出"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 12, 31))
        schedule = {d: [STOCK_A] for d in dates}
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=500, fixed_amount_per_stock=100_000)
        result = run_strategy(
            picker=picker, start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31), config=config,
        )
        assert result.total_trades == 0
        assert len(result.equity_curve) <= 2

    def test_run_continuous_exits_when_broke(self):
        """连续持仓: 资金耗尽且无持仓 → 自动退出"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 12, 31))
        schedule = {d: [STOCK_A] for d in dates}
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=500, fixed_amount_per_stock=100_000)
        result = run_continuous(
            picker=picker, start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31), config=config,
        )
        assert result.total_trades == 0
        assert len(result.equity_curve) <= 2


@db_required
class TestFullYear2025:
    """2025全年回测 (真实行情 + mock固定2只股票)"""

    def test_continuous_full_year_fixed_2_stocks(self):
        """
        核心测试: 全年连续持仓
        - 每天固定选 000001 (平安银行) + 000002 (万科A)
        - 初始100万, 每只10万
        - 真实数据库行情
        """
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 12, 31))
        schedule = {d: [STOCK_A, STOCK_B] for d in dates}
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(
            initial_capital=1_000_000,
            fixed_amount_per_stock=100_000,
            max_holdings=2,
        )
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            config=config,
        )

        assert result.start_date == date(2025, 1, 1)
        assert result.end_date == date(2025, 12, 31)
        assert result.initial_capital == 1_000_000
        assert result.total_trades == 2, (
            f"持续选同样2只股票应只有2笔(最终清仓), 实际 {result.total_trades} 笔"
        )
        assert result.final_capital > 0
        assert len(result.equity_curve) > 200

        for t in result.trades:
            assert t.holding_days > 100
            assert t.buy_amount <= 110_000

        print(f"\n{'='*60}")
        print(f"  全年连续持仓 (真实数据) — {STOCK_A} + {STOCK_B}")
        print(f"{'='*60}")
        print(f"  交易日数: {len(result.equity_curve)}")
        print(f"  初始资金: {result.initial_capital:>14,.2f} 元")
        print(f"  最终资金: {result.final_capital:>14,.2f} 元")
        print(f"  总收益:   {result.total_return:>+14,.2f} 元 ({result.total_return_pct:+.2f}%)")
        print(f"  年化收益: {result.annualized_return_pct:>+13.2f}%")
        print(f"  手续费:   {result.total_fees:>14,.2f} 元")
        for t in result.trades:
            print(f"  {t.code}: 持仓{t.holding_days}天  "
                  f"买@{t.buy_price:.2f}  卖@{t.sell_price:.2f}  "
                  f"盈亏 {t.profit:+,.2f} ({t.profit_pct:+.2f}%)")

    def test_t1_full_year_fixed_2_stocks(self):
        """
        全年隔日卖出 (T+1) — 真实行情
        - 每天选 000001 + 000002, 每只10万
        """
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 12, 31))
        schedule = {d: [STOCK_A, STOCK_B] for d in dates}
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(
            initial_capital=1_000_000,
            fixed_amount_per_stock=100_000,
            max_holdings=2,
        )
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            config=config,
        )

        assert result.initial_capital == 1_000_000
        assert result.total_trades > 100
        assert result.final_capital > 0
        assert result.win_trades + result.lose_trades == result.total_trades
        assert result.total_fees > 0
        for t in result.trades:
            assert t.buy_amount <= 110_000

        print(f"\n{'='*60}")
        print(f"  全年隔日卖出 T+1 (真实数据) — {STOCK_A} + {STOCK_B}")
        print(f"{'='*60}")
        print(f"  成交笔数: {result.total_trades}")
        print(f"  初始资金: {result.initial_capital:>14,.2f} 元")
        print(f"  最终资金: {result.final_capital:>14,.2f} 元")
        print(f"  总收益:   {result.total_return:>+14,.2f} 元 ({result.total_return_pct:+.2f}%)")
        print(f"  胜率:     {result.win_rate:.1f}%")
        print(f"  手续费:   {result.total_fees:>14,.2f} 元")
        print(f"  跳过笔数: {result.skipped_trades}")
        print(f"  盈利笔数: {result.win_trades}  亏损笔数: {result.lose_trades}")
        print(f"  单笔最大盈利: {result.max_single_profit:+,.2f}")
        print(f"  单笔最大亏损: {result.max_single_loss:+,.2f}")

    def test_full_year_auto_exit_on_depletion(self):
        """5万初始 vs 10万/只 → 买不起, 直接退出"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 12, 31))
        schedule = {d: [STOCK_A, STOCK_B] for d in dates}
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(
            initial_capital=50_000, fixed_amount_per_stock=100_000, max_holdings=2,
        )
        result = run_strategy(
            picker=picker, start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31), config=config,
        )
        assert result.total_trades == 0
        assert result.final_capital == 50_000

    def test_full_year_gradual_depletion(self):
        """20万初始, 每只10万 → 每天满仓交易, 观察手续费侵蚀"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 12, 31))
        schedule = {d: [STOCK_A, STOCK_B] for d in dates}
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(
            initial_capital=200_000, fixed_amount_per_stock=100_000, max_holdings=2,
        )
        result = run_strategy(
            picker=picker, start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31), config=config,
        )

        assert result.total_trades > 0
        assert result.final_capital >= 0
        assert result.total_fees > 0

        print(f"\n{'='*60}")
        print(f"  资金侵蚀测试 (20万, 每只10万)")
        print(f"{'='*60}")
        print(f"  成交笔数: {result.total_trades}")
        print(f"  最终资金: {result.final_capital:>14,.2f} 元")
        print(f"  总收益:   {result.total_return:>+14,.2f} 元 ({result.total_return_pct:+.2f}%)")
        print(f"  总手续费: {result.total_fees:>14,.2f} 元")

    def test_continuous_with_stock_switching(self):
        """全年连续持仓 + 隔天换股 (奇数日选A, 偶数日选B)"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 12, 31))
        schedule = {}
        for i, d in enumerate(dates):
            schedule[d] = [STOCK_A] if i % 2 == 0 else [STOCK_B]

        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(
            initial_capital=1_000_000, fixed_amount_per_stock=100_000, max_holdings=1,
        )
        result = run_continuous(
            picker=picker, start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31), config=config,
        )

        assert result.total_trades > 100
        codes = set(t.code for t in result.trades)
        assert STOCK_A in codes
        assert STOCK_B in codes
        assert result.total_fees > 0

        print(f"\n{'='*60}")
        print(f"  隔天换股 连续持仓 (真实数据)")
        print(f"{'='*60}")
        print(f"  成交笔数: {result.total_trades}")
        print(f"  最终资金: {result.final_capital:>14,.2f} 元")
        print(f"  总收益:   {result.total_return:>+14,.2f} 元 ({result.total_return_pct:+.2f}%)")
        print(f"  平均持仓: {result.avg_holding_days:.1f} 天")
        print(f"  手续费:   {result.total_fees:>14,.2f} 元")

    def test_equity_curve_dates_are_trading_days(self):
        """净值曲线中的日期都是交易日 (不含周末)"""
        import backtest.data_loader as dl
        dates = dl.get_trading_dates(date(2025, 1, 1), date(2025, 3, 31))
        schedule = {d: [STOCK_A] for d in dates[:50]}
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(
            initial_capital=1_000_000, fixed_amount_per_stock=100_000,
        )
        result = run_continuous(
            picker=picker, start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31), config=config,
        )
        td_set = set(dates)
        for point in result.equity_curve:
            d = date.fromisoformat(point["date"])
            assert d in td_set, f"净值曲线日期 {d} 不是交易日"
            assert d.weekday() < 5, f"净值曲线日期 {d} 是周末"
