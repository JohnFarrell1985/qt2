"""repair-qfq CLI 测试."""
from src.data.repair_qfq import ALL_HISTORY_GAP_DAYS, build_parser, summarize_gap_detection


def test_build_parser_defaults():
    args = build_parser().parse_args([])
    assert args.full is False
    assert args.detect_only is False
    assert args.source == "qmt"
    assert args.concurrency == 8


def test_build_parser_full():
    args = build_parser().parse_args(["--full", "--detect-only"])
    assert args.full is True
    assert args.detect_only is True


def test_summarize_gap_detection_shape():
    summary = summarize_gap_detection(30)
    assert "from_gap" in summary
    assert "union" in summary
    assert isinstance(summary["codes"], list)


def test_all_history_gap_days_large():
    assert ALL_HISTORY_GAP_DAYS >= 3650
