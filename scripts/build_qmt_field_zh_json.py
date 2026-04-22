"""从讯投文档抓页文本解析字段中文说明, 生成 ``src/data/qmt_field_labels.zh.json``.

将 ``dict.thinktrader`` 中「财务数据字段列表」段落保存为
``doc/qmt_thinktrader_field_snippet.txt`` 后, 无缓存路径也可解析.

用法: uv run python scripts/build_qmt_field_zh_json.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CAND = [
    Path(
        r"C:\Users\dongg\.cursor\projects\c-Users-dongg-git-game-agents"
        r"\agent-tools\0210e070-60e7-4394-9b89-b523265bba7e.txt",
    ),
    _ROOT / "doc" / "qmt_thinktrader_field_snippet.txt",
]
_HEADS: dict[str, str] = {
    "#### Balance -": "Balance",
    "#### Income -": "Income",
    "#### CashFlow -": "CashFlow",
    "#### PershareIndex -": "Pershareindex",
    "#### Capital -": "Capital",
    "#### Top10holder": "Top10holder",
    "#### Holdernum -": "Holdernum",
}
_LINE_RE = re.compile(r"^\s*'(?P<field>[^']+)'\s*#+(?P<zh>.*?)\s*$")


def main() -> None:
    raw = None
    for p in _CAND:
        if p.is_file():
            raw = p.read_text(encoding="utf-8", errors="ignore")
            break
    if not raw:
        raise SystemExit("缺少 doc: 请放 doc/qmt_thinktrader_field_snippet.txt")

    out: dict[str, dict[str, str]] = {t: {} for t in set(_HEADS.values())}
    out["Top10flowholder"] = {}
    current: str | None = None
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("```"):
            continue
        if s.startswith("### "):
            current = None
            continue
        if s.startswith("####"):
            for prefix, t in _HEADS.items():
                if s.startswith(prefix):
                    current = t
                    break
            else:
                current = None
            continue
        if not current:
            continue
        m = _LINE_RE.match(line.rstrip())
        if not m:
            continue
        field, zh = m.group("field"), m.group("zh").strip()
        if field == "Net":
            continue
        out[current][field] = zh

    if out.get("Top10holder"):
        out["Top10flowholder"] = dict(out["Top10holder"])

    out_path = _ROOT / "src" / "data" / "qmt_field_labels.zh.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written:", out_path)
    print("counts:", {k: len(v) for k, v in out.items()})


if __name__ == "__main__":
    main()
