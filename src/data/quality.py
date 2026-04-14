"""数据质量检查器

功能:
  - DataFrame schema 校验 (via Pandera)
  - 日期连续性检查
  - 异常值检测 (Z-score)

Reference: Great Expectations / Pandera best practices
"""
import numpy as np
import pandas as pd
import pandera.pandas as pa

from src.common.config import settings
from src.common.logger import get_logger
from src.data.schemas import SCHEMA_REGISTRY

logger = get_logger(__name__)


class DataQualityChecker:
    def __init__(self, z_threshold: float = None, max_pct_change: float = None):
        cfg = settings.data_quality
        self.z_threshold = z_threshold or cfg.z_threshold
        self.max_pct_change = max_pct_change or cfg.max_pct_change

    def validate_schema(self, df: pd.DataFrame, schema_name: str = "stock_daily") -> dict:
        """Returns: {"valid": bool, "errors": [...]}"""
        schema = SCHEMA_REGISTRY.get(schema_name)
        if schema is None:
            return {"valid": False, "errors": [f"Unknown schema: {schema_name}"]}

        try:
            schema.validate(df, lazy=True)
            return {"valid": True, "errors": []}
        except pa.errors.SchemaErrors as exc:
            errors = []
            for _, row in exc.failure_cases.iterrows():
                errors.append(str(row.to_dict()))
            return {"valid": False, "errors": errors}

    def check_continuity(
        self, df: pd.DataFrame, date_col: str = "trade_date",
    ) -> list[dict]:
        """Check for gaps in trading dates. Returns list of {gap_start, gap_end, gap_days}"""
        if df.empty or date_col not in df.columns:
            return []

        dates = pd.to_datetime(df[date_col]).sort_values().reset_index(drop=True)
        if len(dates) < 2:
            return []

        gaps = []
        diffs = dates.diff().dropna()
        for i, delta in diffs.items():
            if delta.days > 5:
                gaps.append({
                    "gap_start": str(dates.iloc[i - 1].date()),
                    "gap_end": str(dates.iloc[i].date()),
                    "gap_days": delta.days,
                })
        return gaps

    def detect_anomalies(
        self, df: pd.DataFrame, column: str, z_threshold: float = None,
    ) -> pd.Index:
        """Return indices of rows with Z-score > threshold"""
        threshold = z_threshold or self.z_threshold
        if column not in df.columns or df[column].dropna().empty:
            return pd.Index([])

        series = df[column].astype(float)
        mean = series.mean()
        std = series.std()
        if std == 0:
            return pd.Index([])

        z_scores = ((series - mean) / std).abs()
        return df.index[z_scores > threshold]

    def full_check(
        self, df: pd.DataFrame, schema_name: str = "stock_daily",
    ) -> dict:
        """Run all checks. Returns: {"schema": {...}, "gaps": [...], "anomalies": {...}}"""
        result: dict = {"schema": self.validate_schema(df, schema_name)}

        result["gaps"] = self.check_continuity(df)

        numeric_cols = df.select_dtypes(include=[np.number]).columns
        anomalies = {}
        for col in numeric_cols:
            idx = self.detect_anomalies(df, col)
            if len(idx) > 0:
                anomalies[col] = idx.tolist()
        result["anomalies"] = anomalies

        return result
