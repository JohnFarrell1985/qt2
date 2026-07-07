"""CachedPicker 回测集成测试."""

import json
import tempfile
from datetime import date
from pathlib import Path

from src.backtest.stock_picker import CachedPicker


def test_cached_picker_loads_candidates():
    data = {
        "trade_date": "2026-07-07",
        "candidates": ["600519.SH", "000001.SZ"],
        "ma_snapshots": {
            "600519.SH": {"composite_score": 90, "tier": "A"},
            "000001.SZ": {"composite_score": 80, "tier": "B"},
        },
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f)
        path = f.name

    picker = CachedPicker(picks_file=path)
    result = picker.pick(date(2026, 7, 7))
    assert result.codes == ["600519.SH", "000001.SZ"]
    assert result.confidence["600519.SH"] == 90.0

    Path(path).unlink(missing_ok=True)


def test_cached_picker_loads_final_picks_legacy():
    data = {
        "trade_date": "2026-07-07",
        "final_picks": [
            {"code": "600519.SH", "score": 90, "reasons": "strong trend"},
            {"code": "000001.SZ", "score": 80, "reasons": "ok"},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f)
        path = f.name

    picker = CachedPicker(picks_file=path)
    result = picker.pick(date(2026, 7, 7))
    assert result.codes == ["600519.SH", "000001.SZ"]
    assert result.confidence["600519.SH"] == 90.0

    Path(path).unlink(missing_ok=True)
