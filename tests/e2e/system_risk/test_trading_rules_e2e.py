"""E2E: 交易规则引擎 — 使用数据库中真实股票代码验证分类与规则"""
from src.strategy.trading_rules import (
    AssetType, TradingRule, TRADING_RULES,
    infer_asset_type, get_trading_rule,
)


class TestInferAssetTypeWithRealCodes:
    """用 DB 真实 stocks 表的代码验证 infer_asset_type"""

    def test_main_board_codes(self, all_stock_codes_sample):
        main_board = [c for c in all_stock_codes_sample if c.startswith("6") and not c.startswith("688")]
        for code in main_board:
            assert infer_asset_type(code) == AssetType.A_STOCK_MAIN, f"{code} should be main board"

    def test_sz_main_board(self, all_stock_codes_sample):
        sz_main = [c for c in all_stock_codes_sample if c.startswith("000")]
        for code in sz_main:
            assert infer_asset_type(code) == AssetType.A_STOCK_MAIN, f"{code} should be main board"

    def test_star_market_codes(self, all_stock_codes_sample):
        star = [c for c in all_stock_codes_sample if c.startswith("688")]
        assert len(star) > 0, "Should have STAR market codes in DB"
        for code in star:
            assert infer_asset_type(code) == AssetType.A_STOCK_STAR, f"{code} should be STAR"

    def test_gem_codes(self, all_stock_codes_sample):
        gem = [c for c in all_stock_codes_sample if c.startswith("300") or c.startswith("301")]
        assert len(gem) > 0, "Should have GEM codes in DB"
        for code in gem:
            assert infer_asset_type(code) == AssetType.A_STOCK_GEM, f"{code} should be GEM"

    def test_bse_codes(self, all_stock_codes_sample):
        bse = [c for c in all_stock_codes_sample if c.startswith("8") and len(c) == 6]
        for code in bse:
            at = infer_asset_type(code)
            assert at == AssetType.A_STOCK_BSE, f"{code} should be BSE, got {at}"


class TestTradingRulesConsistency:
    """用真实代码验证交易规则一致性"""

    def test_all_asset_types_have_rules(self):
        for at in AssetType:
            assert at in TRADING_RULES, f"Missing rule for {at}"

    def test_t_plus_n_for_real_stocks(self, real_stock_codes):
        for code in real_stock_codes:
            rule = get_trading_rule(code)
            assert isinstance(rule, TradingRule)
            at = infer_asset_type(code)
            if at in (AssetType.A_STOCK_MAIN, AssetType.A_STOCK_STAR, AssetType.A_STOCK_GEM):
                assert rule.t_plus_n == 1, f"{code} ({at}) T+N should be 1"
            elif at == AssetType.CONVERTIBLE_BOND:
                assert rule.t_plus_n == 0

    def test_price_limits_reasonable(self, real_stock_codes):
        for code in real_stock_codes:
            rule = get_trading_rule(code)
            if rule.price_limit_pct is not None:
                assert 0.05 <= rule.price_limit_pct <= 0.30, (
                    f"{code} price_limit {rule.price_limit_pct} out of reasonable range"
                )

    def test_min_lot_size_positive(self):
        for at, rule in TRADING_RULES.items():
            assert rule.min_lot_size > 0, f"{at} min_lot_size must be > 0"
            assert rule.min_lot_size in (1, 10, 100, 200), (
                f"{at} min_lot_size {rule.min_lot_size} not standard"
            )

    def test_stamp_tax_nonnegative(self):
        for at, rule in TRADING_RULES.items():
            assert rule.stamp_tax_rate >= 0

    def test_star_has_200_lot(self):
        rule = TRADING_RULES[AssetType.A_STOCK_STAR]
        assert rule.min_lot_size == 200
        assert rule.price_limit_pct == 0.20

    def test_cross_border_etf_is_t0(self):
        rule = TRADING_RULES[AssetType.ETF_CROSS_BORDER]
        assert rule.t_plus_n == 0

    def test_etf_classification_with_real_codes(self, pg_engine):
        """使用 etf_info 表中真实的 ETF 代码验证分类"""
        from sqlalchemy import text
        sql = "SELECT code FROM etf_info LIMIT 50"
        with pg_engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
        codes = [r[0] for r in rows]
        assert len(codes) > 0

        for code in codes:
            bare = code.split(".")[0]
            at = infer_asset_type(bare)
            assert at in (AssetType.ETF_DOMESTIC, AssetType.ETF_CROSS_BORDER), (
                f"ETF code {code} classified as {at}, expected ETF type"
            )
