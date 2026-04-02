"""Tests for src/ml/strategy_builder.py - StrategyBuilder"""
import numpy as np
import pandas as pd
import pytest
from datetime import date
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_model():
    model = MagicMock()
    model.predict.return_value = pd.Series(
        [0.05, 0.03, -0.01, 0.08, 0.02, -0.02, 0.01, 0.06, 0.04, 0.07],
        index=[f"{i:06d}" for i in range(1, 11)],
        name="predicted_return",
    )
    return model


@pytest.fixture
def factor_data():
    codes = [f"{i:06d}" for i in range(1, 11)]
    rng = np.random.RandomState(0)
    return pd.DataFrame(
        {f"f{i}": rng.randn(10) for i in range(3)},
        index=codes,
    )


@pytest.fixture
def builder(mock_model):
    from src.ml.strategy_builder import StrategyBuilder
    return StrategyBuilder(model=mock_model, top_n=5, long_threshold=0.0)


class TestGenerateSignals:
    def test_returns_list_of_dicts(self, builder, factor_data):
        signals = builder.generate_signals(factor_data, date(2024, 6, 1))
        assert isinstance(signals, list)
        for s in signals:
            assert "code" in s
            assert "signal" in s
            assert "predicted_return" in s
            assert "rank" in s

    def test_respects_top_n(self, builder, factor_data):
        signals = builder.generate_signals(factor_data, date(2024, 6, 1))
        assert len(signals) <= 5

    def test_all_signals_are_buy(self, builder, factor_data):
        signals = builder.generate_signals(factor_data, date(2024, 6, 1))
        for s in signals:
            assert s["signal"] == "buy"

    def test_signals_sorted_by_score_descending(self, builder, factor_data):
        signals = builder.generate_signals(factor_data, date(2024, 6, 1))
        scores = [s["predicted_return"] for s in signals]
        assert scores == sorted(scores, reverse=True)

    def test_rank_starts_at_one(self, builder, factor_data):
        signals = builder.generate_signals(factor_data, date(2024, 6, 1))
        assert signals[0]["rank"] == 1

    def test_long_threshold_filters(self, mock_model, factor_data):
        from src.ml.strategy_builder import StrategyBuilder
        mock_model.predict.return_value = pd.Series(
            [0.05, -0.01, -0.03, 0.02, -0.05, -0.04, -0.02, 0.01, -0.01, 0.03],
            index=[f"{i:06d}" for i in range(1, 11)],
            name="predicted_return",
        )
        builder = StrategyBuilder(model=mock_model, top_n=10, long_threshold=0.01)
        signals = builder.generate_signals(factor_data, date(2024, 6, 1))
        for s in signals:
            assert s["predicted_return"] >= 0.01

    def test_calls_model_predict(self, builder, factor_data):
        builder.generate_signals(factor_data, date(2024, 6, 1))
        builder.model.predict.assert_called_once()


class TestSavePredictions:
    @patch("src.ml.strategy_builder.get_session")
    def test_saves_all_predictions(self, mock_get_session, builder):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        predictions = pd.Series(
            [0.05, 0.03, -0.01], index=["000001", "000002", "000003"],
            name="predicted_return",
        )
        count = builder.save_predictions(predictions, date(2024, 6, 1), model_id=1)
        assert count == 3
        assert mock_session.add.call_count == 3

    @patch("src.ml.strategy_builder.get_session")
    def test_signal_labeling(self, mock_get_session, builder):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        predictions = pd.Series(
            [0.05, -0.01], index=["000001", "000002"], name="predicted_return",
        )
        builder.save_predictions(predictions, date(2024, 6, 1))

        added = [call.args[0] for call in mock_session.add.call_args_list]
        signals = {r.code: r.signal for r in added}
        assert signals["000001"] == "buy"
        assert signals["000002"] == "hold"

    @patch("src.ml.strategy_builder.get_session")
    def test_rank_assigned(self, mock_get_session, builder):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        predictions = pd.Series(
            [0.05, 0.03, 0.01], index=["A", "B", "C"], name="pred",
        )
        builder.save_predictions(predictions, date(2024, 6, 1), model_id=2)

        added = [call.args[0] for call in mock_session.add.call_args_list]
        ranks = {r.code: r.rank_score for r in added}
        assert ranks["A"] < ranks["B"] < ranks["C"]

    @patch("src.ml.strategy_builder.get_session")
    def test_model_id_passed(self, mock_get_session, builder):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        predictions = pd.Series([0.01], index=["000001"])
        builder.save_predictions(predictions, date(2024, 6, 1), model_id=42)
        record = mock_session.add.call_args_list[0].args[0]
        assert record.model_id == 42
