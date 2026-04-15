"""Tests for src/distill/consensus.py — ConsensusArbiter & ConsensusLabel."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.distill.consensus import ConsensusArbiter, ConsensusLabel


# ── ConsensusLabel dataclass ─────────────────────────────────────────


class TestConsensusLabel:
    @pytest.mark.timeout(30)
    def test_create_with_defaults(self):
        label = ConsensusLabel(text="利好消息", label="positive")
        assert label.text == "利好消息"
        assert label.label == "positive"
        assert label.confidence == 1.0
        assert label.is_hard is False
        assert label.teacher_agreement is True
        assert label.teacher_a_label == ""
        assert label.teacher_b_label == ""
        assert label.difficulty_score == 0.0
        assert label.metadata == {}

    @pytest.mark.timeout(30)
    def test_create_with_all_fields(self):
        label = ConsensusLabel(
            text="暴跌",
            label="negative",
            confidence=0.6,
            is_hard=True,
            teacher_agreement=False,
            teacher_a_label="negative",
            teacher_b_label="neutral",
            difficulty_score=0.8,
            metadata={"source": "test"},
        )
        assert label.is_hard is True
        assert label.teacher_agreement is False
        assert label.difficulty_score == 0.8
        assert label.metadata == {"source": "test"}

    @pytest.mark.timeout(30)
    def test_has_expected_fields(self):
        expected = {
            "text", "label", "confidence", "is_hard",
            "teacher_agreement", "teacher_a_label", "teacher_b_label",
            "difficulty_score", "metadata",
        }
        label = ConsensusLabel(text="t", label="l")
        assert set(vars(label).keys()) == expected


# ── ConsensusArbiter._rule_fallback ─────────────────────────────────


class TestRuleFallback:
    @pytest.mark.timeout(30)
    def test_positive_keywords(self):
        result = ConsensusArbiter._rule_fallback("利好消息 上涨突破")
        assert result.label == "positive"
        assert result.confidence == 0.3

    @pytest.mark.timeout(30)
    def test_negative_keywords(self):
        result = ConsensusArbiter._rule_fallback("暴跌 利空 下跌跌停")
        assert result.label == "negative"

    @pytest.mark.timeout(30)
    def test_neutral_no_keywords(self):
        result = ConsensusArbiter._rule_fallback("今日市场成交量平稳")
        assert result.label == "neutral"

    @pytest.mark.timeout(30)
    def test_neutral_equal_keywords(self):
        result = ConsensusArbiter._rule_fallback("利好 利空")
        assert result.label == "neutral"

    @pytest.mark.timeout(30)
    def test_returns_consensus_label(self):
        result = ConsensusArbiter._rule_fallback("test")
        assert isinstance(result, ConsensusLabel)
        assert result.is_hard is False
        assert result.teacher_agreement is True


# ── ConsensusArbiter.label_batch ────────────────────────────────────


class TestLabelBatch:
    @pytest.mark.timeout(30)
    def test_no_llm_falls_back_to_rules(self):
        arbiter = ConsensusArbiter(llm_client=None)
        texts = ["利好消息", "暴跌警告", "今天天气不错"]
        results = asyncio.run(arbiter.label_batch(texts))
        assert len(results) == 3
        assert all(isinstance(r, ConsensusLabel) for r in results)
        assert results[0].label == "positive"
        assert results[1].label == "negative"
        assert results[2].label == "neutral"

    @pytest.mark.timeout(30)
    def test_with_llm_agreement(self):
        mock_llm = MagicMock()
        arbiter = ConsensusArbiter(llm_client=mock_llm)
        arbiter._classify = AsyncMock(return_value="positive")

        results = asyncio.run(arbiter.label_batch(["利好消息"]))
        assert len(results) == 1
        assert results[0].label == "positive"
        assert results[0].teacher_agreement is True
        assert results[0].confidence == 1.0

    @pytest.mark.timeout(30)
    def test_with_llm_disagreement_triggers_judge(self):
        mock_llm = MagicMock()
        arbiter = ConsensusArbiter(llm_client=mock_llm)

        call_count = 0

        async def side_effect(text, model, context=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "positive"
            if call_count == 2:
                return "negative"
            return "positive"

        arbiter._classify = AsyncMock(side_effect=side_effect)

        results = asyncio.run(arbiter.label_batch(["分歧文本"]))
        assert len(results) == 1
        assert results[0].is_hard is True
        assert results[0].teacher_agreement is False
        assert results[0].confidence == 0.6

    @pytest.mark.timeout(30)
    def test_llm_exception_falls_back(self):
        mock_llm = MagicMock()
        arbiter = ConsensusArbiter(llm_client=mock_llm)
        arbiter._classify = AsyncMock(side_effect=RuntimeError("LLM down"))

        results = asyncio.run(arbiter.label_batch(["利好突破"]))
        assert len(results) == 1
        assert results[0].confidence == 0.3


# ── ConsensusArbiter.score_difficulty ───────────────────────────────


class TestScoreDifficulty:
    @pytest.mark.timeout(30)
    def test_without_student_model(self):
        arbiter = ConsensusArbiter()
        labels = [
            ConsensusLabel(text="a", label="positive", is_hard=False),
            ConsensusLabel(text="b", label="negative", is_hard=True),
            ConsensusLabel(text="c", label="neutral", is_hard=False),
        ]
        easy, hard = arbiter.score_difficulty(labels)
        assert len(easy) == 2
        assert len(hard) == 1
        assert hard[0].text == "b"

    @pytest.mark.timeout(30)
    def test_with_student_model(self):
        arbiter = ConsensusArbiter()
        mock_student = MagicMock()
        mock_student.predict.side_effect = lambda t: "positive" if t == "a" else "wrong"

        labels = [
            ConsensusLabel(text="a", label="positive"),
            ConsensusLabel(text="b", label="negative"),
        ]
        easy, hard = arbiter.score_difficulty(labels, base_student=mock_student)
        assert len(easy) == 1
        assert easy[0].text == "a"
        assert len(hard) == 1
        assert hard[0].text == "b"
