"""
Fin-R1 API Middleware - Real-time Data Fetcher
实时数据获取模块（使用akshare）

功能:
- 秒级实时行情获取
- 市场概览数据
- 股票搜索
- 数据缓存
"""
import asyncio
import akshare as ak
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

# API调用超时设置（秒）
AKSHARE_TIMEOUT = 30


@dataclass
class StockQuote:
    """股票实时行情数据结构 - 包含完整实时数据字段"""
    # 基础信息
    code: str
    name: str

    # 价格数据
    price: float
    change: float
    change_percent: float
    high: float
    low: float
    open: float
    pre_close: float

    # 成交数据
    volume: float
    turnover: float
    turnover_rate: Optional[float] = None
    amplitude: Optional[float] = None

    # 市值数据
    market_cap: Optional[float] = None
    float_market_cap: Optional[float] = None

    # 财务指标
    pe: Optional[float] = None
    pb: Optional[float] = None

    # 技术指标（来自akshare实时行情）
    rise_speed: Optional[float] = None  # 涨速
    change_5min: Optional[float] = None   # 5分钟涨跌
    change_60d: Optional[float] = None    # 60日涨跌幅
    change_ytd: Optional[float] = None   # 年初至今涨跌幅


class LRUCache:
    """简单LRU缓存实现"""

    def __init__(self, maxsize: int = 128):
        self.maxsize = maxsize
        self.cache = {}
        self.access_order = []

    def get(self, key):
        if key in self.cache:
            # 移动到末尾（最近使用）
            self.access_order.remove(key)
            self.access_order.append(key)
            return self.cache[key]
        return None

    def set(self, key, value):
        if key in self.cache:
            self.access_order.remove(key)
        elif len(self.cache) >= self.maxsize:
            # 移除最久未使用的
            oldest = self.access_order.pop(0)
            del self.cache[oldest]
        self.cache[key] = value
        self.access_order.append(key)

    def clear(self):
        self.cache.clear()
        self.access_order.clear()


class RealtimeDataFetcher:
    """实时数据获取器 - 优化缓存策略"""

    def __init__(self, cache_ttl: int = 60, max_cache_size: int = 256):
        # 使用LRU缓存替代普通字典，防止无限增长
        self._cache = LRUCache(maxsize=max_cache_size)
        self._cache_time: Dict[str, datetime] = {}
        self.cache_ttl = cache_ttl
        # 全市场数据缓存（减少API调用）
        self._market_cache: Optional[Any] = None
        self._market_cache_time: Optional[datetime] = None
        self._market_cache_ttl = 30  # 30秒缓存

    async def _get_market_data(self, max_retries: int = 3) -> Any:
        """
        获取全市场数据（带缓存和数据完整性检查）

        注意: akshare stock_zh_a_spot_em 有时只返回200条数据（已知问题）
        此函数会检查数据完整性并重试
        """
        now = datetime.now()
        if (self._market_cache is not None and
            self._market_cache_time and
            (now - self._market_cache_time).seconds < self._market_cache_ttl):
            return self._market_cache

        # 尝试获取完整数据
        for attempt in range(max_retries):
            try:
                df = await self._run_sync(ak.stock_zh_a_spot_em)

                # 检查数据完整性 - A股约有5000+只股票
                if len(df) < 4000:  # 如果少于4000条，可能数据不完整
                    logger.warning(f"市场数据可能不完整: 仅返回 {len(df)} 条记录 (期望4000+)")

                    if attempt < max_retries - 1:
                        logger.info(f"第 {attempt + 1} 次重试获取市场数据...")
                        import asyncio
                        await asyncio.sleep(1)  # 等待1秒后重试
                        continue
                    else:
                        logger.error(f"无法获取完整市场数据，使用 {len(df)} 条记录")

                # 检查必要字段是否存在
                required_fields = ['代码', '名称', '最新价', '涨跌幅']
                missing_fields = [f for f in required_fields if f not in df.columns]

                if missing_fields:
                    logger.error(f"市场数据缺少必要字段: {missing_fields}")
                    if attempt < max_retries - 1:
                        continue

                # 数据验证通过
                self._market_cache = df
                self._market_cache_time = now
                logger.info(f"成功获取市场数据: {len(df)} 只股票")
                return df

            except Exception as e:
                logger.error(f"获取市场数据失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(1)
                else:
                    raise

        return self._market_cache  # 返回缓存数据（如果有）

    def _get_cache(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        value = self._cache.get(key)
        if value is not None:
            cache_time = self._cache_time.get(key)
            if cache_time and (datetime.now() - cache_time).seconds < self.cache_ttl:
                return value
            # 过期清理
            self._cache_time.pop(key, None)
        return None

    def _set_cache(self, key: str, value: Any):
        """设置缓存"""
        self._cache.set(key, value)
        self._cache_time[key] = datetime.now()

    async def _run_sync(self, func, *args, timeout: int = AKSHARE_TIMEOUT, **kwargs):
        """在线程池执行同步函数，带超时控制"""
        loop = asyncio.get_event_loop()
        # 使用 asyncio.wait_for 包装，实现超时控制
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: func(*args, **kwargs)),
            timeout=timeout
        )

    async def get_quote(self, stock_code: str) -> Optional[StockQuote]:
        """获取单只股票实时行情 - 使用市场数据缓存优化"""
        cache_key = f"quote_{stock_code}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        try:
            # 使用缓存的市场数据，而不是每次都拉取全市场
            df = await self._get_market_data()
            row = df[df['代码'] == stock_code]

            if row.empty:
                return None

            r = row.iloc[0]
            quote = StockQuote(
                code=stock_code,
                name=str(r.get('名称', '')),
                price=float(r.get('最新价', 0) or 0),
                change=float(r.get('涨跌额', 0) or 0),
                change_percent=float(r.get('涨跌幅', 0) or 0),
                volume=float(r.get('成交量', 0) or 0),
                turnover=float(r.get('成交额', 0) or 0),
                high=float(r.get('最高', 0) or 0),
                low=float(r.get('最低', 0) or 0),
                open=float(r.get('今开', 0) or 0),
                pre_close=float(r.get('昨收', 0) or 0),
                turnover_rate=float(r.get('换手率', 0) or 0) if pd.notna(r.get('换手率')) else None,
                amplitude=float(r.get('振幅', 0) or 0) if pd.notna(r.get('振幅')) else None,
                market_cap=float(r.get('总市值', 0) or 0) if pd.notna(r.get('总市值')) else None,
                float_market_cap=float(r.get('流通市值', 0) or 0) if pd.notna(r.get('流通市值')) else None,
                pe=float(r.get('市盈率-动态', 0) or 0) if pd.notna(r.get('市盈率-动态')) else None,
                pb=float(r.get('市净率', 0) or 0) if pd.notna(r.get('市净率')) else None,
                rise_speed=float(r.get('涨速', 0) or 0) if pd.notna(r.get('涨速')) else None,
                change_5min=float(r.get('5分钟涨跌', 0) or 0) if pd.notna(r.get('5分钟涨跌')) else None,
                change_60d=float(r.get('60日涨跌幅', 0) or 0) if pd.notna(r.get('60日涨跌幅')) else None,
                change_ytd=float(r.get('年初至今涨跌幅', 0) or 0) if pd.notna(r.get('年初至今涨跌幅')) else None
            )

            self._set_cache(cache_key, quote)
            return quote

        except Exception as e:
            logger.error(f"获取{stock_code}实时行情失败: {e}")
            return None

    async def get_batch_quotes(self, codes: List[str]) -> List[StockQuote]:
        """批量获取股票行情"""
        tasks = [self.get_quote(c) for c in codes]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r]

    async def get_market_overview(self) -> Dict[str, Any]:
        """获取市场概览 - 使用缓存的全市场数据"""
        cache_key = "market_overview"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        try:
            # 使用缓存的市场数据
            df = await self._get_market_data()

            stats = {
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "statistics": {
                    "up": len(df[df['涨跌幅'] > 0]),
                    "down": len(df[df['涨跌幅'] < 0]),
                    "flat": len(df[df['涨跌幅'] == 0])
                },
                "top_gainers": [],
                "top_losers": []
            }

            # 涨跌幅榜
            gainers = df.nlargest(10, '涨跌幅')[['名称', '涨跌幅']].to_dict('records')
            losers = df.nsmallest(10, '涨跌幅')[['名称', '涨跌幅']].to_dict('records')

            stats['top_gainers'] = [
                {"name": r['名称'], "change": round(r['涨跌幅'], 2)} for r in gainers
            ]
            stats['top_losers'] = [
                {"name": r['名称'], "change": round(r['涨跌幅'], 2)} for r in losers
            ]

            self._set_cache(cache_key, stats)
            return stats

        except Exception as e:
            logger.error(f"获取市场概览失败: {e}")
            return {"error": str(e)}

    async def search_stock(self, keyword: str) -> List[Dict]:
        """搜索股票 - 使用缓存的市场数据"""
        try:
            # 使用缓存的市场数据
            df = await self._get_market_data()
            matches = df[df['名称'].str.contains(keyword, case=False, na=False)]

            return [
                {
                    "code": str(row['代码']),
                    "name": str(row['名称']),
                    "price": float(row.get('最新价', 0) or 0),
                    "change": float(row.get('涨跌幅', 0) or 0)
                }
                for _, row in matches.head(10).iterrows()
            ]

        except Exception as e:
            logger.error(f"搜索股票失败: {e}")
            return []

    def format_for_llm(self, data: Any, query_type: str) -> str:
        """格式化为LLM可读的文本"""
        lines = [f"=== 实时数据 [{datetime.now().strftime('%H:%M')}] ==="]

        if query_type == "quote" and isinstance(data, list):
            for q in data:
                lines.append(f"\n【{q.name} ({q.code})】")
                lines.append(f"  价格: ¥{q.price:.2f} ({q.change:+.2f}%)")
                lines.append(f"  成交: {q.volume/1e4:.0f}万手  额: {q.turnover/1e8:.2f}亿")
                if q.pe:
                    lines.append(f"  PE: {q.pe:.1f}  PB: {q.pb:.1f}" if q.pb else f"  PE: {q.pe:.1f}")

        elif query_type == "market":
            stats = data.get("statistics", {})
            lines.append(f"\n【市场概览】上涨{stats.get('up',0)} / 下跌{stats.get('down',0)}")
            if data.get("top_gainers"):
                lines.append("\n涨幅TOP5:")
                for s in data["top_gainers"][:5]:
                    lines.append(f"  {s['name']}: +{s['change']}%")

        return "\n".join(lines)


# 全局实例
fetcher = RealtimeDataFetcher()
