"""E2E: 数据质量检查器 — 用真实 stock_daily 数据验证 schema + 连续性 + 异常检测"""
import pytest

from src.data.quality import DataQualityChecker


class TestSchemaValidationWithRealData:
    """用真实 stock_daily 数据做 Pandera schema 校验"""

    def test_stock_daily_schema_passes(self, real_stock_daily_df):
        df = real_stock_daily_df.copy()
        df["code"] = df["code"].astype(str)
        df["volume"] = df["volume"].astype(float)

        checker = DataQualityChecker()
        result = checker.validate_schema(df, "stock_daily")
        assert result["valid"], f"Real stock_daily should pass schema: {result['errors'][:3]}"

    def test_high_ge_low_invariant(self, real_stock_daily_df):
        df = real_stock_daily_df
        violations = df[df["high"] < df["low"]]
        assert len(violations) == 0, (
            f"Found {len(violations)} rows with high < low, dates: "
            f"{violations['trade_date'].tolist()[:5]}"
        )

    def test_high_ge_open_and_close(self, real_stock_daily_df):
        df = real_stock_daily_df
        assert (df["high"] >= df["open"]).all(), "high should >= open"
        assert (df["high"] >= df["close"]).all(), "high should >= close"

    def test_low_le_open_and_close(self, real_stock_daily_df):
        df = real_stock_daily_df
        assert (df["low"] <= df["open"]).all(), "low should <= open"
        assert (df["low"] <= df["close"]).all(), "low should <= close"

    def test_positive_ohlc(self, real_stock_daily_df):
        df = real_stock_daily_df
        for col in ["open", "high", "low", "close"]:
            assert (df[col] > 0).all(), f"{col} should be > 0"

    def test_nonneg_volume(self, real_stock_daily_df):
        df = real_stock_daily_df
        assert (df["volume"] >= 0).all(), "volume should be >= 0"

    def test_etf_daily_schema_passes(self, real_etf_daily_df):
        if real_etf_daily_df.empty:
            pytest.skip("No ETF daily data available")
        df = real_etf_daily_df.copy()
        df["code"] = df["code"].astype(str)
        df["volume"] = df["volume"].astype(float)

        checker = DataQualityChecker()
        result = checker.validate_schema(df, "etf_daily")
        assert result["valid"], f"Real ETF daily should pass schema: {result['errors'][:3]}"


class TestContinuityWithRealData:
    """检查真实日线数据的交易日连续性"""

    def test_no_extreme_gaps_in_stock_daily(self, real_stock_daily_df):
        checker = DataQualityChecker()
        gaps = checker.check_continuity(real_stock_daily_df)
        extreme_gaps = [g for g in gaps if g["gap_days"] > 15]
        assert len(extreme_gaps) == 0, (
            f"Found {len(extreme_gaps)} extreme gaps (>15 days): {extreme_gaps[:3]}"
        )

    def test_weekend_gaps_acceptable(self, real_stock_daily_df):
        """普通周末 gap (3 天) 不应被标记, 只有长假 > 5 天才标记"""
        checker = DataQualityChecker()
        gaps = checker.check_continuity(real_stock_daily_df)
        for g in gaps:
            assert g["gap_days"] > 5, "Only gaps > 5 days should be flagged"

    def test_spring_festival_gap_detected(self, real_stock_daily_df):
        """春节/国庆假期应产生 gap (通常 7~10 天)"""
        checker = DataQualityChecker()
        gaps = checker.check_continuity(real_stock_daily_df)
        long_gaps = [g for g in gaps if g["gap_days"] >= 7]
        assert len(long_gaps) >= 1, "Should detect at least one long holiday gap"


class TestAnomalyDetectionWithRealData:
    """用真实收益率数据做 Z-score 异常检测"""

    def test_detect_extreme_returns(self, real_stock_daily_df):
        checker = DataQualityChecker(z_threshold=3.0)
        idx = checker.detect_anomalies(real_stock_daily_df, "change_pct", z_threshold=3.0)
        assert len(idx) >= 0
        if len(idx) > 0:
            extreme_vals = real_stock_daily_df.loc[idx, "change_pct"]
            assert extreme_vals.abs().min() > 3.0, "Anomaly returns should be significant"

    def test_volume_anomalies(self, real_stock_daily_df):
        checker = DataQualityChecker(z_threshold=3.0)
        idx = checker.detect_anomalies(real_stock_daily_df, "volume", z_threshold=3.0)
        if len(idx) > 0:
            normal_vol = real_stock_daily_df["volume"].mean()
            anomaly_vols = real_stock_daily_df.loc[idx, "volume"]
            assert anomaly_vols.mean() > normal_vol, "Anomaly volumes should exceed mean"


class TestFullCheckIntegration:
    """full_check 端到端"""

    def test_full_check_returns_all_sections(self, real_stock_daily_df):
        df = real_stock_daily_df.copy()
        df["code"] = df["code"].astype(str)
        df["volume"] = df["volume"].astype(float)

        checker = DataQualityChecker()
        result = checker.full_check(df, "stock_daily")

        assert "schema" in result
        assert "gaps" in result
        assert "anomalies" in result
        assert result["schema"]["valid"]

    def test_full_check_anomalies_are_dict(self, real_stock_daily_df):
        df = real_stock_daily_df.copy()
        df["code"] = df["code"].astype(str)
        df["volume"] = df["volume"].astype(float)

        checker = DataQualityChecker()
        result = checker.full_check(df, "stock_daily")
        assert isinstance(result["anomalies"], dict)
