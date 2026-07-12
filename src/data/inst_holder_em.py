"""东财机构持有家数 API (RPT_F10_MAIN_ORGHOLD) — 供同步与 Web UI 降级。"""
from __future__ import annotations

import time
from datetime import date
from typing import Any, Dict, List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)

_EM_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EM_REPORT = "RPT_F10_MAIN_ORGHOLD"
_PAGE_SIZE = 500
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def bare_code(code: str) -> str:
    s = str(code or "").strip().upper()
    if "." in s:
        s = s.split(".", 1)[0]
    for pre in ("SH", "SZ", "BJ", "HK"):
        if s.startswith(pre) and s[len(pre):].isdigit():
            s = s[len(pre):]
            break
    return s.zfill(6) if s.isdigit() and len(s) <= 6 else s


def current_year_report_dates(today: Optional[date] = None) -> List[str]:
    today = today or date.today()
    y = today.year
    candidates = [f"{y}-12-31", f"{y}-09-30", f"{y}-06-30", f"{y}-03-31"]
    return [d for d in candidates if date.fromisoformat(d) <= today]


def standard_report_dates(start_year: int, end_year: int) -> List[date]:
    """生成区间内标准季报/年报截止日 (新→旧)。"""
    out: List[date] = []
    for y in range(end_year, start_year - 1, -1):
        for md in ("12-31", "09-30", "06-30", "03-31"):
            out.append(date.fromisoformat(f"{y}-{md}"))
    return out


def is_complete(row: dict) -> bool:
    return str(row.get("IS_COMPLETE", "")).strip() in ("1", "1.0")


def em_request(params: dict) -> dict:
    import requests

    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = requests.get(_EM_URL, params=params, headers=_HEADERS, timeout=25)
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("success"):
                raise RuntimeError(payload.get("message") or "eastmoney api failed")
            return payload.get("result") or {}
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.4 * (attempt + 1))
    raise last_err  # type: ignore[misc]


def em_total_for_date(report_date: str) -> int:
    result = em_request({
        "reportName": _EM_REPORT,
        "columns": "SECURITY_CODE",
        "pageSize": 1,
        "pageNumber": 1,
        "source": "WEB",
        "client": "WEB",
        "filter": f"(REPORT_DATE='{report_date}')",
    })
    return int(result.get("count") or 0)


def fetch_report_page(report_date: str, page: int) -> tuple[list[dict], int]:
    result = em_request({
        "reportName": _EM_REPORT,
        "columns": "SECURITY_CODE,TOTAL_ORG_NUM,IS_COMPLETE,REPORT_DATE",
        "pageSize": _PAGE_SIZE,
        "pageNumber": page,
        "source": "WEB",
        "client": "WEB",
        "filter": f"(REPORT_DATE='{report_date}')",
    })
    rows = result.get("data") or []
    total = int(result.get("count") or 0)
    return rows, total


def fetch_all_for_report_date(report_date: str) -> List[Dict[str, Any]]:
    """拉取某报告期全市场机构家数 (含未完整披露)。"""
    out: List[Dict[str, Any]] = []
    page = 1
    rd = date.fromisoformat(report_date[:10])
    while True:
        rows, total = fetch_report_page(report_date, page)
        if not rows:
            break
        for row in rows:
            code = str(row.get("SECURITY_CODE", "")).strip().zfill(6)
            if not code or code == "000000":
                continue
            try:
                cnt = int(row.get("TOTAL_ORG_NUM"))
            except (TypeError, ValueError):
                continue
            out.append({
                "code": code,
                "report_date": rd,
                "holder_count": cnt,
                "is_complete": is_complete(row),
                "source": "eastmoney",
            })
        if page * _PAGE_SIZE >= total:
            break
        page += 1
    return out


def fetch_one(code: str, report_dates: List[str]) -> Optional[Dict[str, Any]]:
    bare = bare_code(code)
    for rd in report_dates:
        result = em_request({
            "reportName": _EM_REPORT,
            "columns": "SECURITY_CODE,TOTAL_ORG_NUM,REPORT_DATE,IS_COMPLETE",
            "pageSize": 5,
            "pageNumber": 1,
            "source": "WEB",
            "client": "WEB",
            "filter": f'(SECURITY_CODE="{bare}")(REPORT_DATE=\'{rd}\')',
        })
        rows = result.get("data") or []
        if not rows or not is_complete(rows[0]):
            continue
        try:
            cnt = int(rows[0].get("TOTAL_ORG_NUM"))
        except (TypeError, ValueError):
            continue
        return {
            "inst_holder_count": cnt,
            "inst_holder_report_date": rd,
            "inst_holder_source": "eastmoney",
        }
    return None
