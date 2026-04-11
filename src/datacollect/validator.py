"""数据质量验证层 — 三级校验: schema / business / statistical

对采集到的 DataFrame 做质量门控, 在入库前拦截脏数据。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)

_CFG = settings.datacollect

STOCK_CODE_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")

_REQUIRED_COLUMNS: dict[str, list[str]] = {
    "stock_daily": ["code", "trade_date", "open", "high", "low", "close", "volume"],
    "stock_list": ["code", "name"],
}

_NUMERIC_COLUMNS: dict[str, list[str]] = {
    "stock_daily": ["open", "high", "low", "close", "volume"],
}


@dataclass
class ValidationError:
    """单条校验错误。"""

    level: str  # "schema", "business", "statistical"
    column: str
    row_idx: int | None
    message: str


@dataclass
class ValidationResult:
    """整体校验结果。"""

    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    rows_checked: int = 0
    rows_invalid: int = 0
    warnings: list[ValidationError] = field(default_factory=list)


class DataValidator:
    """Three-level data quality validator for collected DataFrames.

    Levels:
        1. Schema — 必需列、类型
        2. Business — OHLCV 逻辑关系
        3. Statistical — 涨跌幅阈值、Z-score 异常值 (warning)
    """

    def __init__(
        self,
        pct_change_limit: float | None = None,
        zscore_limit: float | None = None,
    ):
        self._pct_change_limit = pct_change_limit if pct_change_limit is not None else _CFG.validator_pct_change_limit
        self._zscore_limit = zscore_limit if zscore_limit is not None else _CFG.validator_zscore_limit

    def validate(self, df: pd.DataFrame, data_type: str) -> ValidationResult:
        """执行三级校验, 返回 ValidationResult。"""
        if df is None or df.empty:
            return ValidationResult(
                is_valid=False,
                errors=[
                    ValidationError(
                        level="schema",
                        column="",
                        row_idx=None,
                        message="DataFrame is empty or None",
                    )
                ],
            )

        errors: list[ValidationError] = []
        warnings: list[ValidationError] = []

        errors.extend(self._check_schema(df, data_type))
        if not errors:
            errors.extend(self._check_business_rules(df, data_type))
        warnings.extend(self._check_statistical(df, data_type))

        invalid_rows = {e.row_idx for e in errors if e.row_idx is not None}
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            rows_checked=len(df),
            rows_invalid=len(invalid_rows),
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Level 1: Schema
    # ------------------------------------------------------------------

    def _check_schema(self, df: pd.DataFrame, data_type: str) -> list[ValidationError]:
        errors: list[ValidationError] = []

        required = _REQUIRED_COLUMNS.get(data_type, [])
        for col in required:
            if col not in df.columns:
                errors.append(
                    ValidationError(
                        level="schema",
                        column=col,
                        row_idx=None,
                        message=f"Required column '{col}' missing",
                    )
                )
        if errors:
            return errors

        numeric_cols = _NUMERIC_COLUMNS.get(data_type, [])
        for col in numeric_cols:
            if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
                errors.append(
                    ValidationError(
                        level="schema",
                        column=col,
                        row_idx=None,
                        message=f"Column '{col}' must be numeric, got {df[col].dtype}",
                    )
                )

        if data_type == "stock_daily" and "volume" in df.columns:
            neg_mask = pd.to_numeric(df["volume"], errors="coerce").fillna(0) < 0
            for idx in df.index[neg_mask]:
                errors.append(
                    ValidationError(
                        level="schema",
                        column="volume",
                        row_idx=int(idx),
                        message="volume must be non-negative",
                    )
                )

        if data_type == "stock_list" and "code" in df.columns:
            for idx, code in df["code"].items():
                if pd.isna(code) or not STOCK_CODE_PATTERN.match(str(code)):
                    errors.append(
                        ValidationError(
                            level="schema",
                            column="code",
                            row_idx=int(idx),
                            message=f"code '{code}' does not match pattern XXXXXX.SH|SZ|BJ",
                        )
                    )

        return errors

    # ------------------------------------------------------------------
    # Level 2: Business Rules
    # ------------------------------------------------------------------

    def _check_business_rules(self, df: pd.DataFrame, data_type: str) -> list[ValidationError]:
        errors: list[ValidationError] = []

        if data_type != "stock_daily":
            return errors

        for idx in df.index:
            row = df.loc[idx]
            op = row.get("open")
            hi = row.get("high")
            lo = row.get("low")
            cl = row.get("close")
            vol = row.get("volume")

            if pd.isna(op) or pd.isna(hi) or pd.isna(lo) or pd.isna(cl):
                continue

            row_idx = int(idx)

            if op <= 0:
                errors.append(
                    ValidationError("business", "open", row_idx, f"open={op} must be > 0")
                )
            if cl <= 0:
                errors.append(
                    ValidationError("business", "close", row_idx, f"close={cl} must be > 0")
                )
            if hi < lo:
                errors.append(
                    ValidationError("business", "high", row_idx, f"high={hi} < low={lo}")
                )
            if hi < op:
                errors.append(
                    ValidationError("business", "high", row_idx, f"high={hi} < open={op}")
                )
            if hi < cl:
                errors.append(
                    ValidationError("business", "high", row_idx, f"high={hi} < close={cl}")
                )
            if lo > op:
                errors.append(
                    ValidationError("business", "low", row_idx, f"low={lo} > open={op}")
                )
            if lo > cl:
                errors.append(
                    ValidationError("business", "low", row_idx, f"low={lo} > close={cl}")
                )
            if vol is not None and not pd.isna(vol) and vol < 0:
                errors.append(
                    ValidationError("business", "volume", row_idx, f"volume={vol} must be >= 0")
                )

        return errors

    # ------------------------------------------------------------------
    # Level 3: Statistical
    # ------------------------------------------------------------------

    def _check_statistical(self, df: pd.DataFrame, data_type: str) -> list[ValidationError]:
        warnings: list[ValidationError] = []

        if data_type != "stock_daily":
            return warnings

        if "pct_change" in df.columns:
            pct = pd.to_numeric(df["pct_change"], errors="coerce")
            mask = pct.abs() >= self._pct_change_limit
            for idx in df.index[mask]:
                val = pct.loc[idx]
                if pd.notna(val):
                    warnings.append(
                        ValidationError(
                            "statistical",
                            "pct_change",
                            int(idx),
                            f"pct_change={val:.2f}% exceeds ±{self._pct_change_limit}%",
                        )
                    )

        if "close" in df.columns:
            close = pd.to_numeric(df["close"], errors="coerce").dropna()
            if len(close) > 1:
                mean = close.mean()
                std = close.std()
                if std > 0:
                    zscores = (close - mean) / std
                    outlier_mask = zscores.abs() >= self._zscore_limit
                    for idx in close.index[outlier_mask]:
                        warnings.append(
                            ValidationError(
                                "statistical",
                                "close",
                                int(idx),
                                f"close Z-score={zscores.loc[idx]:.2f} exceeds ±{self._zscore_limit}",
                            )
                        )

        return warnings
