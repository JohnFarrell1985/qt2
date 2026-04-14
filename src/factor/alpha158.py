"""Qlib Alpha158 因子计算器

纯 pandas/numpy 实现, 无 Qlib 依赖。6 大类 ~130+ 因子:
KBAR / PRICE / VOLUME / STD / RSRS / CORR-COV

P1-21: 多源因子管线 — Alpha158 计算模块
"""

import numpy as np
import pandas as pd

from src.common.config import settings
from src.common.logger import get_logger
from src.factor.base import BaseFactor, register_factor

logger = get_logger(__name__)

_EPS = 1e-12


class Alpha158Calculator:
    """Qlib Alpha158 因子计算器

    对单只股票的日线 OHLCV DataFrame 批量计算 ~130+ 量价因子。
    """

    def __init__(self, windows: list[int] | None = None):
        if windows is None:
            raw = settings.factor_pipeline.alpha158_windows
            self.windows: list[int] = [int(w) for w in raw.split(",")]
        else:
            self.windows = windows

    def calc(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算 Alpha158 因子

        Args:
            df: 单只标的日线 DataFrame, 至少含 open/high/low/close/volume 列, 按日期升序

        Returns:
            原始 df 附加 ~130 个因子列
        """
        o = df["open"].astype(float)
        h = df["high"].astype(float)
        lo = df["low"].astype(float)
        c = df["close"].astype(float)
        v = df["volume"].astype(float)
        ret = c.pct_change()
        vol_pct = v.pct_change()

        parts: dict[str, pd.Series] = {}
        self._kbar(parts, o, h, lo, c)
        for w in self.windows:
            self._price(parts, c, ret, w)
            self._volume(parts, v, vol_pct, w)
            self._std(parts, c, h, lo, ret, w)
            self._rsrs(parts, c, h, lo, w)
            self._corr_cov(parts, c, h, lo, v, ret, vol_pct, w)

        result = pd.concat([df, pd.DataFrame(parts, index=df.index)], axis=1)
        logger.debug("Alpha158 计算完成: %d 个因子, windows=%s", len(parts), self.windows)
        return result

    @property
    def factor_names(self) -> list[str]:
        """返回所有因子名称列表 (不含原始 OHLCV)"""
        names: list[str] = []
        names.extend(self._kbar_names())
        for w in self.windows:
            names.extend(self._price_names(w))
            names.extend(self._volume_names(w))
            names.extend(self._std_names(w))
            names.extend(self._rsrs_names(w))
            names.extend(self._corr_cov_names(w))
        return names

    # ------------------------------------------------------------------
    # KBAR: K 线形态因子 (8 个, 无窗口)
    # ------------------------------------------------------------------

    @staticmethod
    def _kbar_names() -> list[str]:
        return [
            "KBAR_open", "KBAR_high_low", "KBAR_close_pos",
            "KBAR_upper_shadow", "KBAR_lower_shadow", "KBAR_body_ratio",
            "KBAR_high_open", "KBAR_low_open",
        ]

    @staticmethod
    def _kbar(
        out: dict[str, pd.Series],
        o: pd.Series,
        h: pd.Series,
        lo: pd.Series,
        c: pd.Series,
    ) -> None:
        hl = h - lo + _EPS
        out["KBAR_open"] = (c - o) / (o + _EPS)
        out["KBAR_high_low"] = (h - lo) / (o + _EPS)
        out["KBAR_close_pos"] = (c - o) / hl
        max_oc = pd.concat([o, c], axis=1).max(axis=1)
        min_oc = pd.concat([o, c], axis=1).min(axis=1)
        out["KBAR_upper_shadow"] = (h - max_oc) / hl
        out["KBAR_lower_shadow"] = (min_oc - lo) / hl
        out["KBAR_body_ratio"] = (c - o).abs() / hl
        out["KBAR_high_open"] = (h - o) / (o + _EPS)
        out["KBAR_low_open"] = (o - lo) / (o + _EPS)

    # ------------------------------------------------------------------
    # PRICE: 价格动量/均值回归因子 (7 per window)
    # ------------------------------------------------------------------

    @staticmethod
    def _price_names(w: int) -> list[str]:
        return [
            f"PRICE_mom_{w}", f"PRICE_mean_rev_{w}",
            f"PRICE_close_max_{w}", f"PRICE_close_min_{w}",
            f"PRICE_bias_{w}", f"PRICE_ret_max_{w}", f"PRICE_ret_min_{w}",
        ]

    @staticmethod
    def _price(out: dict[str, pd.Series], c: pd.Series, ret: pd.Series, w: int) -> None:
        c_shift = c.shift(w)
        out[f"PRICE_mom_{w}"] = c / (c_shift + _EPS) - 1
        c_ma = c.rolling(w, min_periods=1).mean()
        out[f"PRICE_mean_rev_{w}"] = c / (c_ma + _EPS) - 1
        out[f"PRICE_close_max_{w}"] = c / (c.rolling(w, min_periods=1).max() + _EPS)
        out[f"PRICE_close_min_{w}"] = c / (c.rolling(w, min_periods=1).min() + _EPS)
        c_std = c.rolling(w, min_periods=2).std()
        out[f"PRICE_bias_{w}"] = (c - c_ma) / (c_std + _EPS)
        out[f"PRICE_ret_max_{w}"] = ret.rolling(w, min_periods=1).max()
        out[f"PRICE_ret_min_{w}"] = ret.rolling(w, min_periods=1).min()

    # ------------------------------------------------------------------
    # VOLUME: 成交量特征因子 (5 per window)
    # ------------------------------------------------------------------

    @staticmethod
    def _volume_names(w: int) -> list[str]:
        return [
            f"VOL_mean_ratio_{w}", f"VOL_cv_{w}", f"VOL_chg_{w}",
            f"VOL_zscore_{w}", f"VOL_max_ratio_{w}",
        ]

    @staticmethod
    def _volume(
        out: dict[str, pd.Series],
        v: pd.Series,
        vol_pct: pd.Series,  # noqa: ARG004
        w: int,
    ) -> None:
        v_ma = v.rolling(w, min_periods=1).mean()
        long_w = min(w * 4, 240)
        v_ma_long = v.rolling(long_w, min_periods=1).mean()
        out[f"VOL_mean_ratio_{w}"] = v_ma / (v_ma_long + _EPS)

        v_std = v.rolling(w, min_periods=2).std()
        out[f"VOL_cv_{w}"] = v_std / (v_ma + _EPS)

        out[f"VOL_chg_{w}"] = v / (v.shift(w) + _EPS)

        out[f"VOL_zscore_{w}"] = (v - v_ma) / (v_std + _EPS)

        out[f"VOL_max_ratio_{w}"] = v / (v.rolling(w, min_periods=1).max() + _EPS)

    # ------------------------------------------------------------------
    # STD: 波动率类因子 (4 per window)
    # ------------------------------------------------------------------

    @staticmethod
    def _std_names(w: int) -> list[str]:
        return [
            f"STD_ret_{w}", f"STD_close_{w}",
            f"STD_high_low_{w}", f"STD_parkinson_{w}",
        ]

    @staticmethod
    def _std(
        out: dict[str, pd.Series],
        c: pd.Series,
        h: pd.Series,
        lo: pd.Series,
        ret: pd.Series,
        w: int,
    ) -> None:
        out[f"STD_ret_{w}"] = ret.rolling(w, min_periods=2).std()

        c_ma = c.rolling(w, min_periods=1).mean()
        out[f"STD_close_{w}"] = c.rolling(w, min_periods=2).std() / (c_ma + _EPS)

        hl_ratio = (h - lo) / (c + _EPS)
        out[f"STD_high_low_{w}"] = hl_ratio.rolling(w, min_periods=2).std()

        ln_hl = np.log((h / (lo + _EPS)).clip(lower=_EPS))
        out[f"STD_parkinson_{w}"] = np.sqrt(
            ln_hl.pow(2).rolling(w, min_periods=2).mean() / (4 * np.log(2))
        )

    # ------------------------------------------------------------------
    # RSRS: 阻力支撑类因子 (4 per window)
    # ------------------------------------------------------------------

    @staticmethod
    def _rsrs_names(w: int) -> list[str]:
        return [
            f"RSRS_high_max_{w}", f"RSRS_low_min_{w}",
            f"RSRS_range_{w}", f"RSRS_close_range_{w}",
        ]

    @staticmethod
    def _rsrs(
        out: dict[str, pd.Series],
        c: pd.Series,
        h: pd.Series,
        lo: pd.Series,
        w: int,
    ) -> None:
        h_max = h.rolling(w, min_periods=1).max()
        lo_min = lo.rolling(w, min_periods=1).min()
        out[f"RSRS_high_max_{w}"] = h_max / (c + _EPS)
        out[f"RSRS_low_min_{w}"] = lo_min / (c + _EPS)
        rng = h_max - lo_min
        out[f"RSRS_range_{w}"] = rng / (c + _EPS)
        out[f"RSRS_close_range_{w}"] = (c - lo_min) / (rng + _EPS)

    # ------------------------------------------------------------------
    # CORR / COV: 量价相关性因子 (5 per window)
    # ------------------------------------------------------------------

    @staticmethod
    def _corr_cov_names(w: int) -> list[str]:
        return [
            f"CORR_close_vol_{w}", f"CORR_high_vol_{w}", f"CORR_low_vol_{w}",
            f"COV_ret_vol_{w}", f"CORR_ret_vol_{w}",
        ]

    @staticmethod
    def _corr_cov(
        out: dict[str, pd.Series],
        c: pd.Series,
        h: pd.Series,
        lo: pd.Series,
        v: pd.Series,
        ret: pd.Series,
        vol_pct: pd.Series,
        w: int,
    ) -> None:
        min_p = max(w // 2, 3)
        out[f"CORR_close_vol_{w}"] = c.rolling(w, min_periods=min_p).corr(v)
        out[f"CORR_high_vol_{w}"] = h.rolling(w, min_periods=min_p).corr(v)
        out[f"CORR_low_vol_{w}"] = lo.rolling(w, min_periods=min_p).corr(v)
        out[f"COV_ret_vol_{w}"] = ret.rolling(w, min_periods=min_p).cov(vol_pct)
        out[f"CORR_ret_vol_{w}"] = ret.rolling(w, min_periods=min_p).corr(vol_pct)


# ======================================================================
# 注册 22 个代表性 BaseFactor 子类 (供 FactorRegistry 统一管理)
# ======================================================================

# --- KBAR ---

@register_factor
class KbarOpen(BaseFactor):
    @property
    def name(self) -> str:
        return "KBAR_open"

    @property
    def category(self) -> str:
        return "kbar"

    @property
    def description(self) -> str:
        return "(close-open)/open"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return (df["close"] - df["open"]) / (df["open"] + _EPS)


@register_factor
class KbarHighLow(BaseFactor):
    @property
    def name(self) -> str:
        return "KBAR_high_low"

    @property
    def category(self) -> str:
        return "kbar"

    @property
    def description(self) -> str:
        return "(high-low)/open"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return (df["high"] - df["low"]) / (df["open"] + _EPS)


@register_factor
class KbarClosePos(BaseFactor):
    @property
    def name(self) -> str:
        return "KBAR_close_pos"

    @property
    def category(self) -> str:
        return "kbar"

    @property
    def description(self) -> str:
        return "(close-open)/(high-low)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        hl = df["high"] - df["low"] + _EPS
        return (df["close"] - df["open"]) / hl


@register_factor
class KbarUpperShadow(BaseFactor):
    @property
    def name(self) -> str:
        return "KBAR_upper_shadow"

    @property
    def category(self) -> str:
        return "kbar"

    @property
    def description(self) -> str:
        return "(high-max(open,close))/(high-low)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        hl = df["high"] - df["low"] + _EPS
        max_oc = pd.concat([df["open"], df["close"]], axis=1).max(axis=1)
        return (df["high"] - max_oc) / hl


@register_factor
class KbarLowerShadow(BaseFactor):
    @property
    def name(self) -> str:
        return "KBAR_lower_shadow"

    @property
    def category(self) -> str:
        return "kbar"

    @property
    def description(self) -> str:
        return "(min(open,close)-low)/(high-low)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        hl = df["high"] - df["low"] + _EPS
        min_oc = pd.concat([df["open"], df["close"]], axis=1).min(axis=1)
        return (min_oc - df["low"]) / hl


# --- PRICE ---

@register_factor
class PriceMom5(BaseFactor):
    @property
    def name(self) -> str:
        return "PRICE_mom_5"

    @property
    def category(self) -> str:
        return "price"

    @property
    def lookback_days(self) -> int:
        return 10

    def compute(self, df: pd.DataFrame) -> pd.Series:
        c = df["close"]
        return c / (c.shift(5) + _EPS) - 1


@register_factor
class PriceMom10(BaseFactor):
    @property
    def name(self) -> str:
        return "PRICE_mom_10"

    @property
    def category(self) -> str:
        return "price"

    @property
    def lookback_days(self) -> int:
        return 15

    def compute(self, df: pd.DataFrame) -> pd.Series:
        c = df["close"]
        return c / (c.shift(10) + _EPS) - 1


@register_factor
class PriceMom20(BaseFactor):
    @property
    def name(self) -> str:
        return "PRICE_mom_20"

    @property
    def category(self) -> str:
        return "price"

    @property
    def lookback_days(self) -> int:
        return 25

    def compute(self, df: pd.DataFrame) -> pd.Series:
        c = df["close"]
        return c / (c.shift(20) + _EPS) - 1


@register_factor
class PriceMeanRev5(BaseFactor):
    @property
    def name(self) -> str:
        return "PRICE_mean_rev_5"

    @property
    def category(self) -> str:
        return "price"

    @property
    def lookback_days(self) -> int:
        return 10

    def compute(self, df: pd.DataFrame) -> pd.Series:
        c = df["close"]
        return c / (c.rolling(5, min_periods=1).mean() + _EPS) - 1


@register_factor
class PriceMeanRev20(BaseFactor):
    @property
    def name(self) -> str:
        return "PRICE_mean_rev_20"

    @property
    def category(self) -> str:
        return "price"

    @property
    def lookback_days(self) -> int:
        return 25

    def compute(self, df: pd.DataFrame) -> pd.Series:
        c = df["close"]
        return c / (c.rolling(20, min_periods=1).mean() + _EPS) - 1


@register_factor
class PriceBias20(BaseFactor):
    @property
    def name(self) -> str:
        return "PRICE_bias_20"

    @property
    def category(self) -> str:
        return "price"

    @property
    def lookback_days(self) -> int:
        return 25

    def compute(self, df: pd.DataFrame) -> pd.Series:
        c = df["close"]
        ma = c.rolling(20, min_periods=1).mean()
        std = c.rolling(20, min_periods=2).std()
        return (c - ma) / (std + _EPS)


# --- VOLUME ---

@register_factor
class VolMeanRatio5(BaseFactor):
    @property
    def name(self) -> str:
        return "VOL_mean_ratio_5"

    @property
    def category(self) -> str:
        return "volume"

    @property
    def lookback_days(self) -> int:
        return 25

    @property
    def description(self) -> str:
        return "vol_ma(5)/vol_ma(20)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        v = df["volume"].astype(float)
        return v.rolling(5, min_periods=1).mean() / (v.rolling(20, min_periods=1).mean() + _EPS)


@register_factor
class VolMeanRatio20(BaseFactor):
    @property
    def name(self) -> str:
        return "VOL_mean_ratio_20"

    @property
    def category(self) -> str:
        return "volume"

    @property
    def lookback_days(self) -> int:
        return 80

    def compute(self, df: pd.DataFrame) -> pd.Series:
        v = df["volume"].astype(float)
        return v.rolling(20, min_periods=1).mean() / (v.rolling(80, min_periods=1).mean() + _EPS)


@register_factor
class VolCv20(BaseFactor):
    @property
    def name(self) -> str:
        return "VOL_cv_20"

    @property
    def category(self) -> str:
        return "volume"

    @property
    def lookback_days(self) -> int:
        return 25

    @property
    def description(self) -> str:
        return "vol_std(20)/vol_mean(20)"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        v = df["volume"].astype(float)
        return v.rolling(20, min_periods=2).std() / (v.rolling(20, min_periods=1).mean() + _EPS)


# --- STD ---

@register_factor
class StdRet5(BaseFactor):
    @property
    def name(self) -> str:
        return "STD_ret_5"

    @property
    def category(self) -> str:
        return "std"

    @property
    def lookback_days(self) -> int:
        return 10

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change().rolling(5, min_periods=2).std()


@register_factor
class StdRet20(BaseFactor):
    @property
    def name(self) -> str:
        return "STD_ret_20"

    @property
    def category(self) -> str:
        return "std"

    @property
    def lookback_days(self) -> int:
        return 25

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change().rolling(20, min_periods=2).std()


# --- RSRS ---

@register_factor
class RsrsHighMax20(BaseFactor):
    @property
    def name(self) -> str:
        return "RSRS_high_max_20"

    @property
    def category(self) -> str:
        return "rsrs"

    @property
    def lookback_days(self) -> int:
        return 25

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["high"].rolling(20, min_periods=1).max() / (df["close"] + _EPS)


@register_factor
class RsrsLowMin20(BaseFactor):
    @property
    def name(self) -> str:
        return "RSRS_low_min_20"

    @property
    def category(self) -> str:
        return "rsrs"

    @property
    def lookback_days(self) -> int:
        return 25

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["low"].rolling(20, min_periods=1).min() / (df["close"] + _EPS)


@register_factor
class RsrsRange20(BaseFactor):
    @property
    def name(self) -> str:
        return "RSRS_range_20"

    @property
    def category(self) -> str:
        return "rsrs"

    @property
    def lookback_days(self) -> int:
        return 25

    def compute(self, df: pd.DataFrame) -> pd.Series:
        h_max = df["high"].rolling(20, min_periods=1).max()
        lo_min = df["low"].rolling(20, min_periods=1).min()
        return (h_max - lo_min) / (df["close"] + _EPS)


# --- CORR ---

@register_factor
class CorrCloseVol20(BaseFactor):
    @property
    def name(self) -> str:
        return "CORR_close_vol_20"

    @property
    def category(self) -> str:
        return "corr"

    @property
    def lookback_days(self) -> int:
        return 25

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].rolling(20, min_periods=10).corr(df["volume"].astype(float))


@register_factor
class CorrRetVol20(BaseFactor):
    @property
    def name(self) -> str:
        return "CORR_ret_vol_20"

    @property
    def category(self) -> str:
        return "corr"

    @property
    def lookback_days(self) -> int:
        return 25

    def compute(self, df: pd.DataFrame) -> pd.Series:
        ret = df["close"].pct_change()
        vol_pct = df["volume"].astype(float).pct_change()
        return ret.rolling(20, min_periods=10).corr(vol_pct)


@register_factor
class CovRetVol20(BaseFactor):
    @property
    def name(self) -> str:
        return "COV_ret_vol_20"

    @property
    def category(self) -> str:
        return "corr"

    @property
    def lookback_days(self) -> int:
        return 25

    def compute(self, df: pd.DataFrame) -> pd.Series:
        ret = df["close"].pct_change()
        vol_pct = df["volume"].astype(float).pct_change()
        return ret.rolling(20, min_periods=10).cov(vol_pct)
