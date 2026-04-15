"""P2 数据清洗 Schema 单元测试

测试 5 个 P2 阶段的 Pydantic Schema:
- SectorSignalExtraction (行业轮动)
- FundFlowExtraction (资金流向)
- MacroIndicatorExtraction (宏观指标)
- StockEventExtraction (个股事件)
- RiskAlertExtraction (风险预警)
"""
import pytest
from pydantic import ValidationError

from src.dataclean.schemas.sector_signal import SectorRotation, SectorSignalExtraction
from src.dataclean.schemas.fund_flow import FundFlowSignal, FundFlowExtraction
from src.dataclean.schemas.macro_indicator import MacroDataPoint, MacroIndicatorExtraction
from src.dataclean.schemas.stock_event import StockEvent, StockEventExtraction
from src.dataclean.schemas.risk_alert import RiskAlert, RiskAlertExtraction


# ── SectorSignalExtraction ───────────────────────────────────────


class TestSectorRotation:

    @pytest.mark.timeout(30)
    def test_valid_construction(self):
        sr = SectorRotation(
            sector="半导体",
            direction="bullish",
            catalyst="国产替代加速",
            time_horizon="medium",
            confidence=0.8,
        )
        assert sr.sector == "半导体"
        assert sr.direction == "bullish"
        assert sr.confidence == 0.8

    @pytest.mark.timeout(30)
    def test_direction_normalization_chinese(self):
        sr = SectorRotation(
            sector="新能源",
            direction="看多",
            catalyst="政策利好",
            time_horizon="short",
            confidence=0.7,
        )
        assert sr.direction == "bullish"

    @pytest.mark.timeout(30)
    def test_direction_normalization_bearish(self):
        sr = SectorRotation(
            sector="房地产",
            direction="看空",
            catalyst="政策收紧",
            time_horizon="long",
            confidence=0.6,
        )
        assert sr.direction == "bearish"

    @pytest.mark.timeout(30)
    def test_confidence_bounds(self):
        with pytest.raises(ValidationError, match="confidence"):
            SectorRotation(
                sector="金融",
                direction="neutral",
                catalyst="无",
                time_horizon="short",
                confidence=1.5,
            )

    @pytest.mark.timeout(30)
    def test_confidence_negative(self):
        with pytest.raises(ValidationError, match="confidence"):
            SectorRotation(
                sector="金融",
                direction="neutral",
                catalyst="无",
                time_horizon="short",
                confidence=-0.1,
            )

    @pytest.mark.timeout(30)
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            SectorRotation()  # type: ignore[call-arg]


class TestSectorSignalExtraction:

    @pytest.mark.timeout(30)
    def test_defaults(self):
        ext = SectorSignalExtraction()
        assert ext.top_sectors == []
        assert ext.avoid_sectors == []
        assert ext.macro_context == ""
        assert ext.data_source == ""

    @pytest.mark.timeout(30)
    def test_with_sectors(self):
        rotation = SectorRotation(
            sector="芯片",
            direction="bullish",
            catalyst="订单增长",
            time_horizon="short",
            confidence=0.9,
        )
        ext = SectorSignalExtraction(top_sectors=[rotation])
        assert len(ext.top_sectors) == 1
        assert ext.top_sectors[0].sector == "芯片"

    @pytest.mark.timeout(30)
    def test_max_length_top_sectors(self):
        rotations = [
            SectorRotation(
                sector=f"行业_{i}",
                direction="neutral",
                catalyst="test",
                time_horizon="short",
                confidence=0.5,
            )
            for i in range(11)
        ]
        with pytest.raises(ValidationError, match="top_sectors"):
            SectorSignalExtraction(top_sectors=rotations)


# ── FundFlowExtraction ───────────────────────────────────────


class TestFundFlowSignal:

    @pytest.mark.timeout(30)
    def test_valid_construction(self):
        signal = FundFlowSignal(
            flow_type="northbound",
            direction="inflow",
            amount_billion=50.3,
            target="market",
        )
        assert signal.flow_type == "northbound"
        assert signal.direction == "inflow"
        assert signal.amount_billion == 50.3

    @pytest.mark.timeout(30)
    def test_defaults(self):
        signal = FundFlowSignal(
            flow_type="margin",
            direction="outflow",
        )
        assert signal.amount_billion is None
        assert signal.target == "market"
        assert signal.target_name == ""
        assert signal.significance == "normal"

    @pytest.mark.timeout(30)
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            FundFlowSignal()  # type: ignore[call-arg]


class TestFundFlowExtraction:

    @pytest.mark.timeout(30)
    def test_defaults(self):
        ext = FundFlowExtraction()
        assert ext.signals == []
        assert ext.north_net_flow_billion is None
        assert ext.margin_balance_change is None
        assert ext.summary == ""

    @pytest.mark.timeout(30)
    def test_with_signals(self):
        sig = FundFlowSignal(flow_type="block", direction="inflow", amount_billion=10.0)
        ext = FundFlowExtraction(
            signals=[sig],
            north_net_flow_billion=80.5,
            summary="北向资金大幅流入",
        )
        assert len(ext.signals) == 1
        assert ext.north_net_flow_billion == 80.5

    @pytest.mark.timeout(30)
    def test_signals_max_length(self):
        signals = [
            FundFlowSignal(flow_type="northbound", direction="inflow")
            for _ in range(21)
        ]
        with pytest.raises(ValidationError, match="signals"):
            FundFlowExtraction(signals=signals)


# ── MacroIndicatorExtraction ─────────────────────────────────


class TestMacroDataPoint:

    @pytest.mark.timeout(30)
    def test_valid_construction(self):
        dp = MacroDataPoint(
            indicator="CPI",
            value=2.3,
            unit="%",
            period="2026-03",
            direction="up",
        )
        assert dp.indicator == "CPI"
        assert dp.value == 2.3

    @pytest.mark.timeout(30)
    def test_defaults(self):
        dp = MacroDataPoint(indicator="PMI", value=50.1)
        assert dp.unit == "%"
        assert dp.period == ""
        assert dp.direction == ""
        assert dp.expectation == ""

    @pytest.mark.timeout(30)
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            MacroDataPoint()  # type: ignore[call-arg]

        with pytest.raises(ValidationError):
            MacroDataPoint(indicator="CPI")  # type: ignore[call-arg]


class TestMacroIndicatorExtraction:

    @pytest.mark.timeout(30)
    def test_defaults(self):
        ext = MacroIndicatorExtraction()
        assert ext.indicators == []
        assert ext.policy_signal == "neutral"
        assert ext.economic_outlook == "stable"
        assert ext.summary == ""

    @pytest.mark.timeout(30)
    def test_with_indicators(self):
        dp = MacroDataPoint(indicator="M2", value=10.6, direction="up")
        ext = MacroIndicatorExtraction(
            indicators=[dp],
            policy_signal="easing",
            economic_outlook="improving",
            summary="流动性宽松",
        )
        assert len(ext.indicators) == 1
        assert ext.policy_signal == "easing"


# ── StockEventExtraction ─────────────────────────────────────


class TestStockEvent:

    @pytest.mark.timeout(30)
    def test_valid_construction(self):
        ev = StockEvent(
            code="000001.SZ",
            event_type="earnings",
            description="净利润同比增长20%",
            impact="positive",
            magnitude="high",
        )
        assert ev.code == "000001.SZ"
        assert ev.impact == "positive"
        assert ev.time_horizon == "short"

    @pytest.mark.timeout(30)
    def test_impact_normalization_chinese(self):
        ev = StockEvent(
            code="600519.SH",
            event_type="dividend",
            description="高额分红",
            impact="利好",
            magnitude="medium",
        )
        assert ev.impact == "positive"

    @pytest.mark.timeout(30)
    def test_impact_normalization_negative(self):
        ev = StockEvent(
            code="300750.SZ",
            event_type="lawsuit",
            description="涉嫌财务造假",
            impact="利空",
            magnitude="high",
        )
        assert ev.impact == "negative"

    @pytest.mark.timeout(30)
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            StockEvent()  # type: ignore[call-arg]

        with pytest.raises(ValidationError):
            StockEvent(code="000001.SZ")  # type: ignore[call-arg]


class TestStockEventExtraction:

    @pytest.mark.timeout(30)
    def test_defaults(self):
        ext = StockEventExtraction()
        assert ext.events == []
        assert ext.market_impact_summary == ""

    @pytest.mark.timeout(30)
    def test_with_events(self):
        ev = StockEvent(
            code="000001.SZ",
            event_type="merger",
            description="拟收购目标公司",
            impact="positive",
            magnitude="high",
        )
        ext = StockEventExtraction(events=[ev], market_impact_summary="并购利好")
        assert len(ext.events) == 1


# ── RiskAlertExtraction ──────────────────────────────────────


class TestRiskAlert:

    @pytest.mark.timeout(30)
    def test_valid_construction(self):
        alert = RiskAlert(
            alert_type="regulatory",
            severity="high",
            description="监管问询",
            affected_codes=["000001.SZ"],
        )
        assert alert.alert_type == "regulatory"
        assert alert.severity == "high"
        assert alert.recommended_action == "monitor"

    @pytest.mark.timeout(30)
    def test_defaults(self):
        alert = RiskAlert(
            alert_type="fraud",
            severity="critical",
            description="财务造假嫌疑",
        )
        assert alert.affected_codes == []
        assert alert.affected_sectors == []
        assert alert.recommended_action == "monitor"

    @pytest.mark.timeout(30)
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            RiskAlert()  # type: ignore[call-arg]


class TestRiskAlertExtraction:

    @pytest.mark.timeout(30)
    def test_defaults(self):
        ext = RiskAlertExtraction()
        assert ext.alerts == []
        assert ext.overall_risk_level == "normal"
        assert ext.summary == ""

    @pytest.mark.timeout(30)
    def test_with_alerts(self):
        alert = RiskAlert(
            alert_type="delisting",
            severity="critical",
            description="面临退市风险",
            affected_codes=["000001.SZ"],
            recommended_action="exit",
        )
        ext = RiskAlertExtraction(
            alerts=[alert],
            overall_risk_level="extreme",
            summary="存在退市风险",
        )
        assert len(ext.alerts) == 1
        assert ext.overall_risk_level == "extreme"
        assert ext.alerts[0].recommended_action == "exit"

    @pytest.mark.timeout(30)
    def test_alerts_max_length(self):
        alerts = [
            RiskAlert(
                alert_type="policy",
                severity="low",
                description=f"风险_{i}",
            )
            for i in range(11)
        ]
        with pytest.raises(ValidationError, match="alerts"):
            RiskAlertExtraction(alerts=alerts)
