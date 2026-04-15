"""Tests for config.py field validators and validate_required_keys."""

from src.common.config import (
    EtfRotationConfig,
    FactorPipelineConfig,
    PortfolioConfig,
    validate_required_keys,
)


class TestEtfRotationConfigParsing:
    def test_default_pools_are_lists(self):
        cfg = EtfRotationConfig()
        assert isinstance(cfg.risk_pool, list)
        assert isinstance(cfg.defensive_pool, list)
        assert isinstance(cfg.canary_pool, list)
        assert len(cfg.risk_pool) > 0

    def test_json_string_parsed(self):
        cfg = EtfRotationConfig(
            ETF_ROTATION_RISK_POOL='["A","B"]',
            ETF_ROTATION_DEFENSIVE_POOL='["C"]',
            ETF_ROTATION_CANARY_POOL='["D","E"]',
        )
        assert cfg.risk_pool == ["A", "B"]
        assert cfg.defensive_pool == ["C"]
        assert cfg.canary_pool == ["D", "E"]


class TestFactorPipelineConfigParsing:
    def test_default_windows_are_int_list(self):
        cfg = FactorPipelineConfig()
        assert cfg.alpha158_windows == [5, 10, 20, 30, 60]
        assert all(isinstance(w, int) for w in cfg.alpha158_windows)

    def test_csv_string_parsed(self):
        cfg = FactorPipelineConfig(FACTOR_ALPHA158_WINDOWS="3,7,14")
        assert cfg.alpha158_windows == [3, 7, 14]

    def test_categories_parsed_from_csv(self):
        cfg = FactorPipelineConfig(FACTOR_XT_CATEGORIES="a,b,c")
        assert cfg.xt_categories == ["a", "b", "c"]

    def test_default_categories_are_list(self):
        cfg = FactorPipelineConfig()
        assert isinstance(cfg.xt_categories, list)
        assert len(cfg.xt_categories) > 0


class TestPortfolioConfigParsing:
    def test_default_cash_assets_is_list(self):
        cfg = PortfolioConfig()
        assert isinstance(cfg.caa_cash_assets, list)
        assert "511010.SH" in cfg.caa_cash_assets

    def test_json_string_parsed(self):
        cfg = PortfolioConfig(PORTFOLIO_CAA_CASH_ASSETS='["X","Y"]')
        assert cfg.caa_cash_assets == ["X", "Y"]


class TestValidateRequiredKeys:
    def test_returns_missing_keys(self):
        missing = validate_required_keys(
            ("datacollect.tushare_token", "TUSHARE_TOKEN"),
        )
        assert "TUSHARE_TOKEN" in missing

    def test_returns_empty_for_present_keys(self):
        missing = validate_required_keys(
            ("api.host", "API_HOST"),
        )
        assert missing == []
