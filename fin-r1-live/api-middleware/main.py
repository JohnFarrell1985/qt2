"""
Fin-R1 API Middleware - Main Service
实时数据中间层主服务

功能:
1. 接收Web UI的chat completion请求
2. 智能识别数据需求（实时/历史）
3. 从API获取实时数据
4. 从PostgreSQL读取历史数据
5. 混合数据注入系统Prompt
6. 转发到vLLM后端
"""
import asyncio
import httpx
import json
import re
import logging
from typing import AsyncGenerator, Dict, List, Optional
from contextlib import asynccontextmanager
from datetime import datetime
from dataclasses import asdict
from functools import wraps

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings
from realtime_fetcher import fetcher, StockQuote
from database_client import HistoryDataClient
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
logger = logging.getLogger(__name__)

http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    global http_client
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.VLLM_TIMEOUT),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
    )
    logger.info(f"🚀 Fin-R1 API Middleware 启动，端口: {settings.PORT}")
    logger.info(f"📡 vLLM: {settings.VLLM_BASE_URL}")
    logger.info(f"💾 历史数据: {'启用' if settings.ENABLE_DB_HISTORY else '禁用'}")
    logger.info(f"⚡ 实时数据: {'启用' if settings.ENABLE_REALTIME_API else '禁用'}")
    yield
    if http_client:
        await http_client.aclose()
    logger.info("👋 服务已关闭")


app = FastAPI(
    title="Fin-R1 API Middleware",
    description="实时数据中间层 - 支持PostgreSQL历史数据 + 实时API数据",
    version="1.0.0",
    lifespan=lifespan
)

# 添加GZip压缩中间件
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ 数据模型 ============

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="Fin-R1-Live")
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False
    top_p: Optional[float] = 0.9


# ============ 意图识别 ============

class IntentRecognizer:
    """金融意图识别器 - 增强版（支持技术指标和基本面）"""

    # 匹配6位股票代码（兼容中英文环境）
    # 使用前后非数字字符来界定，避免匹配到更长的数字串中的片段
    STOCK_CODES = re.compile(r'(?:^|[^\d])(\d{6})(?:[^\d]|$)')
    
    # 缓存股票名称映射（从数据库加载）
    _stock_name_map: Optional[Dict[str, str]] = None
    _last_map_update: Optional[datetime] = None
    _map_cache_ttl = 300  # 缓存5分钟

    @classmethod
    def _load_stock_name_map(cls) -> Dict[str, str]:
        """从数据库加载所有股票名称到代码的映射"""
        # 检查缓存是否有效
        if cls._stock_name_map is not None and cls._last_map_update is not None:
            elapsed = (datetime.now() - cls._last_map_update).total_seconds()
            if elapsed < cls._map_cache_ttl:
                return cls._stock_name_map
        
        try:
            from database_client import get_db_session
            from sqlalchemy import text
            
            # 从数据库加载所有股票基础信息
            with get_db_session() as session:
                result = session.execute(text("SELECT code, name FROM stocks WHERE name IS NOT NULL"))
                
                name_map = {}
                for row in result:
                    code = row.code
                    name = row.name
                    if code and name:
                        # 添加完整名称
                        name_map[name] = code
                        # 添加无空格版本
                        name_map[name.replace(" ", "")] = code
                        # 添加无"A"/"B"后缀版本（如"万科A"->"万科"）
                        if name.endswith(("A", "B")) and len(name) > 1:
                            name_map[name[:-1]] = code
                
                cls._stock_name_map = name_map
                cls._last_map_update = datetime.now()
                logger.info(f"✅ 已加载 {len(name_map)} 个股票名称映射")
                return name_map
                
        except Exception as e:
            logger.error(f"加载股票名称映射失败: {e}")
            # 返回空映射，避免阻塞
            return {}

    # 实时和历史数据关键词
    REALTIME_KEYWORDS = ["今天", "今日", "现在", "实时", "当前", "盘中", "最新"]
    HISTORY_KEYWORDS = ["历史", "走势", "K线", "趋势", "前期", "去年", "近"]

    # 技术指标关键词
    TECHNICAL_KEYWORDS = {
        "macd": ["MACD", "异同移动平均线", "金叉", "死叉", "DIFF", "DEA"],
        "boll": ["BOLL", "布林带", "布林", "bollinger", "上轨", "中轨", "下轨"],
        "rsi": ["RSI", "相对强弱", "超买", "超卖"],
        "ma": ["MA", "均线", "移动平均线", "五日线", "十日线", "二十日线", "六十日线", "MA5", "MA10", "MA20", "MA60"],
        "kdj": ["KDJ", "随机指标", "K值", "D值", "J值"],
        "technical": ["技术指标", "技术分析", "技术形态", "支撑", "压力", "突破", "回调"]
    }

    # 基本面关键词
    FUNDAMENTAL_KEYWORDS = {
        "financial_report": ["财报", "财务报表", "资产负债表", "利润表", "现金流量表", "年报", "季报", "半年报"],
        "financial_indicator": ["财务指标", "ROE", "ROA", "毛利率", "净利率", "每股收益", "EPS", "市盈率", "市净率", "PE", "PB"],
        "profitability": ["盈利能力", "盈利", "营收", "净利润", "毛利", "ROE", "ROA"],
        "solvency": ["偿债能力", "负债", "资产负债率", "流动比率", "速动比率"],
        "fundamental": ["基本面", "财务分析", "价值分析", "估值"]
    }

    @classmethod
    def analyze(cls, messages: List[ChatMessage]) -> Dict:
        """分析用户意图（增强版）"""
        content = " ".join([m.content for m in messages if m.role in ["user", "human"]])
        
        logger.info(f"分析用户输入: {content[:100]}...")

        result = {
            "need_realtime": False,
            "need_history": False,
            "need_technical": False,
            "need_fundamental": False,
            "stock_codes": [],
            "history_days": 30,
            "technical_indicators": [],
            "fundamental_types": []
        }

        # 1. 提取6位数字股票代码（优先，不依赖数据库）
        codes = cls.STOCK_CODES.findall(content)
        if codes:
            result["stock_codes"] = list(set(codes))
            logger.info(f"正则提取到股票代码: {result['stock_codes']}")
        
        # 2. 从股票名称识别代码（动态加载，失败不影响主流程）
        try:
            name_map = cls._load_stock_name_map()
            for name, code in name_map.items():
                if name in content:
                    if code not in result["stock_codes"]:
                        result["stock_codes"].append(code)
                        logger.info(f"从名称 '{name}' 识别到股票代码: {code}")
        except Exception as e:
            logger.warning(f"股票名称映射加载失败（不影响代码识别）: {e}")

        # 判断实时/历史数据需求
        if any(kw in content for kw in cls.REALTIME_KEYWORDS):
            result["need_realtime"] = True

        if any(kw in content for kw in cls.HISTORY_KEYWORDS):
            result["need_history"] = True

        # 判断技术指标需求
        for indicator_type, keywords in cls.TECHNICAL_KEYWORDS.items():
            if any(kw.lower() in content.lower() for kw in keywords):
                result["need_technical"] = True
                if indicator_type != "technical":
                    result["technical_indicators"].append(indicator_type)

        # 判断基本面数据需求
        for fundamental_type, keywords in cls.FUNDAMENTAL_KEYWORDS.items():
            if any(kw.lower() in content.lower() for kw in keywords):
                result["need_fundamental"] = True
                if fundamental_type != "fundamental":
                    result["fundamental_types"].append(fundamental_type)

        # 提取天数
        if "一年" in content or "全年" in content:
            result["history_days"] = 365
        elif "半年" in content:
            result["history_days"] = 180
        elif "季度" in content or "三个月" in content:
            result["history_days"] = 90
        elif "两个月" in content:
            result["history_days"] = 60
        elif "一个月" in content:
            result["history_days"] = 30

        # 默认：有股票代码但没有明确指定数据类型时
        if result["stock_codes"]:
            if not result["need_realtime"] and not result["need_history"] and \
               not result["need_technical"] and not result["need_fundamental"]:
                result["need_realtime"] = True
                result["need_history"] = True
                result["need_technical"] = True  # 默认也提供技术指标
                result["history_days"] = 60

        return result


# ============ Prompt构建 ============

SYSTEM_PROMPT = """你是Fin-R1金融分析助手，具备专业的股票分析能力。

【重要：你必须基于以下提供的数据进行分析】

{data_section}

【分析要求】
1. ✅ 必须使用上述提供的真实数据进行分析，禁止假设或模拟数据
2. ✅ 如果上述数据显示"[暂无数据]"，请明确告知用户当前数据库中无该股票数据
3. ✅ 技术指标分析要具体（MACD信号、布林带位置、RSI超买超卖、均线排列等）
4. ✅ 基本面分析要关注盈利能力（ROE、毛利率）、偿债能力（资产负债率）等核心指标
5. ✅ 明确标注数据来源：数据库历史数据、实时API数据、计算的技术指标
6. ✅ 风险提示：仅供参考，不构成投资建议

【禁止事项】
❌ 禁止使用假设数据或模拟数据
❌ 禁止声称"无法访问实时数据"或"无法查询数据库"（数据已在上方提供）
❌ 禁止编造不存在的股价或财务数据

今天是 {current_date}。

请记住：你已经有权限访问上述PostgreSQL数据库中的真实股票数据，请基于这些数据进行专业分析。
"""


async def build_prompt(intent: Dict) -> str:
    """构建系统Prompt（增强版 - 包含技术指标和基本面）"""
    data_parts = []
    now = datetime.now()
    data_query_stats = {"history": 0, "technical": 0, "fundamental": 0, "realtime": 0, "failed": []}

    # 1. 历史数据（从DB）
    if intent["need_history"] and settings.ENABLE_DB_HISTORY:
        data_parts.append("【历史数据统计 (数据库)】")
        has_history_data = False
        
        logger.info(f"开始查询历史数据，股票代码: {intent['stock_codes']}, 天数: {intent['history_days']}")

        for code in intent["stock_codes"][:3]:
            logger.info(f"查询股票 {code} 的历史数据...")
            stats = HistoryDataClient.get_stock_statistics(code, intent["history_days"])
            logger.info(f"查询结果: {stats}")
            
            if stats and stats.get('current_price'):
                has_history_data = True
                data_query_stats["history"] += 1
                data_parts.append(f"\n{code} 近{intent['history_days']}天统计:")
                data_parts.append(f"  当前: ¥{stats['current_price']:.2f}")
                data_parts.append(f"  区间: ¥{stats['period_low']:.2f} - ¥{stats['period_high']:.2f}")
                data_parts.append(f"  涨跌天数: 涨{stats['up_days']}天 / 跌{stats['down_days']}天")
                data_parts.append(f"  平均涨跌: {stats['avg_change_pct']:+.2f}%")
                data_parts.append(f"  波动率: {stats['volatility']:.2f}%")

                # 最近3天K线
                history = HistoryDataClient.get_stock_history(code, 3)
                if history:
                    data_parts.append("  最近3个交易日:")
                    for day in history[:3]:
                        data_parts.append(
                            f"    {day['trade_date']}: 开¥{day['open']:.2f} 高¥{day['high']:.2f} "
                            f"低¥{day['low']:.2f} 收¥{day['close']:.2f} ({day.get('change_pct',0):+.1f}%) "
                            f"量{day.get('volume',0)/1e4:.0f}万"
                        )
            else:
                # 明确告知AI该股票无历史数据
                data_parts.append(f"\n⚠️ {code}: 数据库中暂无该股票的历史日线数据")
                data_query_stats["failed"].append(f"{code}: 无历史数据")
                logger.warning(f"股票 {code} 在历史数据表中无记录")
        
        if not has_history_data:
            data_parts.append("\n⚠️ 注意：当前查询的股票代码在数据库中暂无历史数据。请确认：")
            data_parts.append("   1. 离线数据导入是否已完成")
            data_parts.append("   2. 股票代码是否正确")
            data_parts.append("   3. 数据库连接是否正常")

    # 2. 技术指标分析（新增）
    if intent["need_technical"] and settings.ENABLE_DB_HISTORY:
        data_parts.append(f"\n【技术指标分析 (数据库计算)】")

        for code in intent["stock_codes"][:2]:  # 限制最多2只股票，避免prompt过长
            try:
                from database_client import TechnicalIndicatorClient
                tech_summary = TechnicalIndicatorClient.get_indicator_summary(code)

                if 'error' not in tech_summary:
                    data_parts.append(f"\n{code} 技术指标:")

                    # 移动平均线
                    if tech_summary.get('ma'):
                        ma = tech_summary['ma']
                        data_parts.append(f"  移动平均线:")
                        for ma_name, ma_val in ma.items():
                            if ma_val:
                                data_parts.append(f"    {ma_name.upper()}: ¥{ma_val:.2f}")

                        # 判断均线排列
                        ma5 = ma.get('ma5')
                        ma20 = ma.get('ma20')
                        ma60 = ma.get('ma60')
                        if ma5 and ma20 and ma60:
                            if ma5 > ma20 > ma60:
                                data_parts.append(f"    均线排列: 多头排列（强势）")
                            elif ma5 < ma20 < ma60:
                                data_parts.append(f"    均线排列: 空头排列（弱势）")
                            else:
                                data_parts.append(f"    均线排列: 震荡整理")

                    # MACD
                    if tech_summary.get('macd'):
                        macd = tech_summary['macd']
                        data_parts.append(f"  MACD指标:")
                        data_parts.append(f"    MACD: {macd.get('macd', 'N/A')}")
                        data_parts.append(f"    Signal: {macd.get('signal', 'N/A')}")
                        data_parts.append(f"    Histogram: {macd.get('histogram', 'N/A')}")
                        if macd.get('description'):
                            data_parts.append(f"    信号: {macd['description']}")

                    # 布林带
                    if tech_summary.get('boll'):
                        boll = tech_summary['boll']
                        data_parts.append(f"  布林带:")
                        data_parts.append(f"    上轨: ¥{boll.get('upper', 'N/A')}")
                        data_parts.append(f"    中轨: ¥{boll.get('middle', 'N/A')}")
                        data_parts.append(f"    下轨: ¥{boll.get('lower', 'N/A')}")
                        if boll.get('position'):
                            data_parts.append(f"    位置: {boll['position']}")

                    # RSI
                    if tech_summary.get('rsi'):
                        rsi = tech_summary['rsi']
                        data_parts.append(f"  RSI指标:")
                        data_parts.append(f"    RSI(14): {rsi.get('value', 'N/A')}")
                        if rsi.get('signal'):
                            data_parts.append(f"    信号: {rsi['signal']}")

            except Exception as e:
                logger.warning(f"获取技术指标失败 {code}: {e}")

    # 3. 基本面数据（新增）
    if intent["need_fundamental"] and settings.ENABLE_DB_HISTORY:
        data_parts.append(f"\n【基本面数据 (数据库)】")

        for code in intent["stock_codes"][:2]:
            try:
                from database_client import FundamentalDataClient

                # 获取最新财务摘要
                summary = FundamentalDataClient.get_latest_financial_summary(code)

                if summary and not summary.get("error"):
                    data_parts.append(f"\n{code} 财务概况:")

                    # 财务报表关键指标
                    if summary.get("latest_report"):
                        report = summary["latest_report"]
                        data_parts.append(f"  财务报表:")

                        # 资产负债
                        if report.get("balance_sheet"):
                            bs = report["balance_sheet"]
                            total_assets = bs.get("total_assets")
                            total_liabilities = bs.get("total_liabilities")
                            if total_assets and total_liabilities:
                                debt_ratio = total_liabilities / total_assets * 100
                                data_parts.append(f"    总资产: {total_assets/1e8:.2f}亿")
                                data_parts.append(f"    资产负债率: {debt_ratio:.2f}%")

                        # 利润表
                        if report.get("income_statement"):
                            inc = report["income_statement"]
                            revenue = inc.get("total_revenue")
                            net_profit = inc.get("net_profit")
                            if revenue:
                                data_parts.append(f"    营业收入: {revenue/1e8:.2f}亿")
                            if net_profit:
                                data_parts.append(f"    净利润: {net_profit/1e8:.2f}亿")

                    # 财务指标
                    if summary.get("latest_indicator"):
                        indicator = summary["latest_indicator"]
                        data_parts.append(f"  财务指标:")

                        # 盈利能力
                        per_share = indicator.get("per_share", {})
                        if per_share.get("eps_basic"):
                            data_parts.append(f"    每股收益(EPS): {per_share['eps_basic']:.2f}元")
                        if per_share.get("bps"):
                            data_parts.append(f"    每股净资产(BPS): {per_share['bps']:.2f}元")

                        # 盈利能力比率
                        profitability = indicator.get("profitability", {})
                        if profitability.get("roe_weighted"):
                            data_parts.append(f"    ROE(净资产收益率): {profitability['roe_weighted']:.2f}%")
                        if profitability.get("net_profit_margin"):
                            data_parts.append(f"    净利率: {profitability['net_profit_margin']:.2f}%")
                        if profitability.get("gross_profit_margin"):
                            data_parts.append(f"    毛利率: {profitability['gross_profit_margin']:.2f}%")

                        # 偿债能力
                        solvency = indicator.get("solvency", {})
                        if solvency.get("debt_asset_ratio"):
                            data_parts.append(f"    资产负债率: {solvency['debt_asset_ratio']:.2f}%")
                        if solvency.get("current_ratio"):
                            data_parts.append(f"    流动比率: {solvency['current_ratio']:.2f}")

            except Exception as e:
                logger.warning(f"获取基本面数据失败 {code}: {e}")

    # 4. 实时数据（从API）
    if intent["need_realtime"] and settings.ENABLE_REALTIME_API:
        data_parts.append(f"\n【实时行情 (API) - {now.strftime('%H:%M:%S')}】")

        for code in intent["stock_codes"][:5]:
            quote = await fetcher.get_quote(code)
            if quote:
                data_parts.append(
                    f"\n{quote.name}({code}): ¥{quote.price:.2f} ({quote.change:+.2f}%) "
                    f"成交{quote.volume/1e4:.0f}万手"
                )

        # 市场概览
        if not intent["stock_codes"]:
            overview = await fetcher.get_market_overview()
            if overview and "statistics" in overview:
                s = overview["statistics"]
                data_parts.append(f"\n市场概览: 涨{s['up']}家 / 跌{s['down']}家 / 平{s['flat']}家")

    data_section = "\n".join(data_parts) if data_parts else "[暂无数据]"
    
    # 记录数据查询统计
    logger.info(f"📊 数据查询统计: 历史={data_query_stats['history']}, "
                f"技术={data_query_stats['technical']}, "
                f"基本面={data_query_stats['fundamental']}, "
                f"实时={data_query_stats['realtime']}, "
                f"失败={len(data_query_stats['failed'])}")
    if data_query_stats['failed']:
        logger.warning(f"⚠️ 数据查询失败: {data_query_stats['failed']}")

    return SYSTEM_PROMPT.format(
        data_section=data_section,
        current_date=now.strftime("%Y年%m月%d日 %H:%M")
    )


# ============ API端点 ============

@app.get("/v1/models")
async def list_models():
    """模型列表"""
    return {
        "object": "list",
        "data": [{"id": "Fin-R1-Live", "object": "model", "created": 1700000000}]
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    db_status = HistoryDataClient.get_db_status() if settings.ENABLE_DB_HISTORY else {"connected": False}

    return {
        "status": "healthy",
        "service": "fin-r1-middleware",
        "version": "1.0.0",
        "vllm": settings.VLLM_BASE_URL,
        "database": db_status,
        "time": datetime.now().isoformat()
    }


@app.post("/v1/chat/completions")
async def chat_completion(request: ChatCompletionRequest):
    """主chat completion端点"""
    logger.info(f"请求: model={request.model}")

    # 分析意图（增强版）
    intent = IntentRecognizer.analyze(request.messages)
    logger.info(f"意图分析: {intent}")

    # 构建消息
    messages = list(request.messages)

    # 如果有数据需求（实时、历史、技术指标、基本面），则构建系统prompt
    if intent["need_realtime"] or intent["need_history"] or \
       intent["need_technical"] or intent["need_fundamental"]:
        system_prompt = await build_prompt(intent)

        # 插入或合并system消息
        has_system = any(m.role == "system" for m in messages)
        if has_system:
            for i, m in enumerate(messages):
                if m.role == "system":
                    messages[i] = ChatMessage(role="system", content=system_prompt + "\n\n" + m.content)
                    break
        else:
            messages.insert(0, ChatMessage(role="system", content=system_prompt))

    # 转发到vLLM
    payload = {
        "model": settings.VLLM_MODEL,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "temperature": request.temperature,
        "stream": request.stream
    }

    if request.max_tokens:
        payload["max_tokens"] = request.max_tokens

    try:
        url = f"{settings.VLLM_BASE_URL}/v1/chat/completions"

        if request.stream:
            return StreamingResponse(
                stream_response(url, payload),
                media_type="text/event-stream"
            )
        else:
            # 使用带重试的调用
            try:
                response = await _call_vllm_with_retry(url, payload)
            except Exception as e:
                logger.error(f"vLLM调用最终失败: {e}")
                raise HTTPException(status_code=503, detail=f"vLLM服务不可用: {str(e)}")

            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)

            data = response.json()
            data["model"] = request.model
            return JSONResponse(content=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理请求失败: {e}")
        raise HTTPException(status_code=500, detail=f"内部错误: {str(e)}")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException)),
    reraise=True
)
async def _call_vllm_with_retry(url: str, payload: dict) -> httpx.Response:
    """调用 vLLM 带重试机制"""
    return await http_client.post(url, json=payload, timeout=settings.VLLM_TIMEOUT)


async def stream_response(url: str, payload: dict) -> AsyncGenerator[str, None]:
    """流式响应 - 带错误处理"""
    try:
        async with http_client.stream("POST", url, json=payload, timeout=settings.VLLM_TIMEOUT) as response:
            async for chunk in response.aiter_text():
                if chunk:
                    yield chunk
    except httpx.RequestError as e:
        logger.error(f"流式响应请求失败: {e}")
        yield f"data: {json.dumps({'error': f'请求失败: {str(e)}'})}\n\n"
    except Exception as e:
        logger.error(f"流式响应异常: {e}")
        yield f"data: {json.dumps({'error': f'服务器错误: {str(e)}'})}\n\n"


# ============ 数据查询API ============

# 股票代码格式验证正则
STOCK_CODE_PATTERN = re.compile(r'^\d{6}$')


def validate_stock_code(code: str) -> str:
    """验证股票代码格式"""
    if not code or not STOCK_CODE_PATTERN.match(code):
        raise HTTPException(status_code=400, detail=f"无效的股票代码: {code}，应为6位数字")
    return code


@app.get("/api/stock/{code}/realtime")
async def get_realtime(code: str):
    """获取实时数据"""
    # 验证股票代码格式
    validate_stock_code(code)

    quote = await fetcher.get_quote(code)
    if not quote:
        raise HTTPException(status_code=404, detail=f"未找到股票: {code}")
    return asdict(quote)


@app.get("/api/stock/{code}/history")
async def get_history(
    code: str,
    days: int = Query(30, ge=1, le=365, description="查询天数，范围1-365")
):
    """获取历史数据"""
    validate_stock_code(code)

    history = HistoryDataClient.get_stock_history(code, days)
    return {"code": code, "count": len(history), "data": history}


@app.get("/api/stock/{code}/analysis")
async def get_analysis(
    code: str,
    days: int = Query(30, ge=1, le=365, description="统计天数")
):
    """获取综合分析（实时+历史）"""
    validate_stock_code(code)

    result = {
        "code": code,
        "timestamp": datetime.now().isoformat(),
        "realtime": None,
        "statistics": None
    }

    # 实时数据
    try:
        quote = await fetcher.get_quote(code)
        if quote:
            result["realtime"] = asdict(quote)
    except Exception as e:
        logger.warning(f"获取实时数据失败 {code}: {e}")

    # 历史统计
    try:
        stats = HistoryDataClient.get_stock_statistics(code, days)
        if stats:
            result["statistics"] = stats
    except Exception as e:
        logger.warning(f"获取统计数据失败 {code}: {e}")

    return result


@app.get("/api/market/overview")
async def get_market():
    """市场概览"""
    return await fetcher.get_market_overview()


@app.get("/api/search")
async def search(keyword: str, limit: int = 10):
    """搜索股票"""
    # 优先从DB搜索
    results = HistoryDataClient.search_stocks(keyword, limit)

    # 如果没结果，从API搜索
    if not results:
        results = await fetcher.search_stock(keyword)

    return {"keyword": keyword, "results": results}


@app.get("/api/database/status")
async def db_status():
    """数据库状态"""
    return HistoryDataClient.get_db_status()


# ============ 基本面数据 API ============

@app.get("/api/stock/{code}/financial/reports")
async def get_financial_reports(
    code: str,
    report_type: Optional[str] = Query(None, description="报表类型: balance_sheet/income_statement/cash_flow"),
    limit: int = Query(10, ge=1, le=50, description="返回记录数")
):
    """
    获取财务报表数据

    - 资产负债表: report_type=balance_sheet
    - 利润表: report_type=income_statement
    - 现金流量表: report_type=cash_flow
    """
    validate_stock_code(code)

    from database_client import FundamentalDataClient
    reports = FundamentalDataClient.get_financial_reports(code, report_type, limit)

    if not reports:
        return {"code": code, "reports": [], "message": "无财务报表数据"}

    return {"code": code, "count": len(reports), "reports": reports}


@app.get("/api/stock/{code}/financial/indicators")
async def get_financial_indicators(
    code: str,
    limit: int = Query(10, ge=1, le=50, description="返回记录数")
):
    """
    获取财务分析指标

    包含: 盈利能力、偿债能力、运营效率、成长能力等30+指标
    """
    validate_stock_code(code)

    from database_client import FundamentalDataClient
    indicators = FundamentalDataClient.get_financial_indicators(code, limit)

    if not indicators:
        return {"code": code, "indicators": [], "message": "无财务指标数据"}

    return {"code": code, "count": len(indicators), "indicators": indicators}


@app.get("/api/stock/{code}/financial/summary")
async def get_financial_summary(code: str):
    """
    获取最新财务摘要（综合数据）
    """
    validate_stock_code(code)

    from database_client import FundamentalDataClient
    summary = FundamentalDataClient.get_latest_financial_summary(code)

    if summary.get("error"):
        raise HTTPException(status_code=500, detail=summary["error"])

    return summary


@app.get("/api/stock/{code}/financial/profitability")
async def get_profitability_analysis(code: str):
    """
    获取盈利能力分析

    包含: ROE趋势、毛利率趋势、净利率趋势
    """
    validate_stock_code(code)

    from database_client import FundamentalDataClient
    analysis = FundamentalDataClient.get_profitability_analysis(code)

    if analysis.get("error"):
        raise HTTPException(status_code=500, detail=analysis["error"])

    return analysis


@app.get("/api/stock/{code}/financial/solvency")
async def get_solvency_analysis(code: str):
    """
    获取偿债能力分析

    包含: 资产负债率、流动比率、速动比率趋势
    """
    validate_stock_code(code)

    from database_client import FundamentalDataClient
    analysis = FundamentalDataClient.get_solvency_analysis(code)

    if analysis.get("error"):
        raise HTTPException(status_code=500, detail=analysis["error"])

    return analysis


@app.get("/api/stock/{code}/financial/full-analysis")
async def get_full_financial_analysis(code: str):
    """
    获取完整财务分析

    综合: 实时行情、财务报表、财务指标、盈利能力、偿债能力
    """
    validate_stock_code(code)

    result = {
        "code": code,
        "timestamp": datetime.now().isoformat()
    }

    # 1. 实时行情
    try:
        quote = await fetcher.get_quote(code)
        if quote:
            result["realtime"] = asdict(quote)
    except Exception as e:
        logger.warning(f"获取实时数据失败 {code}: {e}")

    # 2. 最新财务报表
    from database_client import FundamentalDataClient
    try:
        summary = FundamentalDataClient.get_latest_financial_summary(code)
        result["financial"] = summary
    except Exception as e:
        logger.warning(f"获取财务数据失败 {code}: {e}")

    # 3. 盈利能力分析
    try:
        profitability = FundamentalDataClient.get_profitability_analysis(code)
        result["profitability"] = profitability.get("analysis", {})
    except Exception as e:
        logger.warning(f"获取盈利能力分析失败 {code}: {e}")

    # 4. 偿债能力分析
    try:
        solvency = FundamentalDataClient.get_solvency_analysis(code)
        result["solvency"] = solvency.get("analysis", {})
    except Exception as e:
        logger.warning(f"获取偿债能力分析失败 {code}: {e}")

    return result


# ============ 技术指标数据 API ============

@app.get("/api/stock/{code}/indicators")
async def get_technical_indicators(
    code: str,
    days: int = Query(60, ge=30, le=365, description="历史数据天数，用于计算指标"),
    include_history: bool = Query(False, description="是否包含完整历史K线数据")
):
    """
    获取股票完整技术指标分析

    包含: MA(5/10/20/60)、MACD、BOLL(20,2)、RSI(14)

    - MA: 移动平均线（趋势判断）
    - MACD: 异同移动平均线（趋势跟踪、金叉死叉）
    - BOLL: 布林带（波动率通道、超买超卖）
    - RSI: 相对强弱指标（动量、超买超卖）
    """
    validate_stock_code(code)

    from database_client import TechnicalIndicatorClient

    try:
        if include_history:
            # 返回完整指标数据（包含历史序列）
            indicators = TechnicalIndicatorClient.get_stock_indicators(code, days)
            return indicators
        else:
            # 只返回最新指标摘要（默认）
            summary = TechnicalIndicatorClient.get_indicator_summary(code)
            return summary

    except Exception as e:
        logger.error(f"获取技术指标失败 {code}: {e}")
        raise HTTPException(status_code=500, detail=f"计算技术指标失败: {str(e)}")


@app.get("/api/stock/{code}/indicators/analysis")
async def get_indicator_analysis(code: str):
    """
    获取多指标综合分析结果

    综合判断: 趋势、动量、波动率、综合建议
    """
    validate_stock_code(code)

    from database_client import TechnicalIndicatorClient

    try:
        analysis = TechnicalIndicatorClient.get_multi_indicator_analysis(code)

        if 'error' in analysis:
            raise HTTPException(status_code=404, detail=analysis['error'])

        return analysis

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取指标分析失败 {code}: {e}")
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@app.get("/api/stock/{code}/full-analysis")
async def get_complete_analysis(code: str):
    """
    获取股票完整分析（技术面+基本面+实时行情）

    综合: 实时行情、技术指标、财务报表、财务指标
    """
    validate_stock_code(code)

    result = {
        "code": code,
        "timestamp": datetime.now().isoformat(),
        "realtime": None,
        "technical": None,
        "fundamental": None,
        "comprehensive": None
    }

    # 1. 实时行情
    try:
        quote = await fetcher.get_quote(code)
        if quote:
            result["realtime"] = asdict(quote)
    except Exception as e:
        logger.warning(f"获取实时数据失败 {code}: {e}")

    # 2. 技术指标
    try:
        from database_client import TechnicalIndicatorClient
        result["technical"] = TechnicalIndicatorClient.get_multi_indicator_analysis(code)
    except Exception as e:
        logger.warning(f"获取技术指标失败 {code}: {e}")

    # 3. 基本面数据
    try:
        from database_client import FundamentalDataClient
        result["fundamental"] = FundamentalDataClient.get_latest_financial_summary(code)
    except Exception as e:
        logger.warning(f"获取基本面数据失败 {code}: {e}")

    # 4. 综合建议
    technical = result.get("technical", {})
    fundamental = result.get("fundamental", {})
    realtime = result.get("realtime", {})

    if technical and fundamental and realtime:
        # 整合技术面和基本面给出建议
        tech_rec = technical.get("recommendation", "")
        trend = technical.get("trend", "")

        # 基本面判断
        fin_rec = "观望"
        if fundamental.get("latest_indicator"):
            indicator = fundamental["latest_indicator"]
            profitability = indicator.get("profitability", {})
            roe = profitability.get("roe_weighted", 0)
            net_margin = profitability.get("net_profit_margin", 0)

            if roe > 15 and net_margin > 20:
                fin_rec = "基本面优秀"
            elif roe > 10 and net_margin > 10:
                fin_rec = "基本面良好"
            elif roe < 5:
                fin_rec = "基本面较弱"

        result["comprehensive"] = {
            "technical_recommendation": tech_rec,
            "fundamental_evaluation": fin_rec,
            "combined_suggestion": f"技术面: {tech_rec} | 基本面: {fin_rec}",
            "risk_level": "中等" if "观望" in tech_rec else "偏高" if "下跌" in tech_rec else "偏低"
        }

    return result


# ============ 量化选股API (V1提示词完整支持) ============

@app.get("/api/stock/{code}/v1-analysis")
async def get_v1_stock_analysis(code: str):
    """
    获取V1版量化选股完整分析报告

    基于V1提示词的5维度评分系统：
    - 技术面分析 (50分): 均线/MACD/BOLL/RSI
    - 量能配合 (25分): 换手率/成交量趋势/成交额
    - 基本面安全 (10分): PE/PB/ROE/盈利增长
    - 板块流动性 (15分): 行业排名/成交额排名

    总分≥75分且基本面≥6分视为合格
    """
    validate_stock_code(code)

    try:
        from stock_analyzer import StockAnalyzer

        analysis = StockAnalyzer.analyze_stock(code)

        if not analysis:
            raise HTTPException(status_code=404, detail=f"无法分析股票: {code}")

        # 格式化报告
        report = StockAnalyzer.format_analysis_report(analysis)

        return {
            "code": code,
            "name": analysis.name,
            "total_score": analysis.total_score,
            "recommendation": analysis.recommendation,
            "risk_level": analysis.risk_level,
            "scores": [
                {
                    "module": s.module,
                    "score": s.score,
                    "max_score": s.max_score,
                    "passed": s.passed,
                    "pass_rate": f"{(s.score/s.max_score*100):.1f}%"
                }
                for s in analysis.scores
            ],
            "technical_data": analysis.technical_data,
            "volume_data": analysis.volume_data,
            "fundamental_data": analysis.fundamental_data,
            "sector_data": analysis.sector_data,
            "report": report
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"V1分析失败 {code}: {e}")
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@app.get("/api/screening/v1")
async def v1_stock_screening(
    min_score: float = Query(75, ge=0, le=100, description="最低综合评分"),
    max_results: int = Query(10, ge=1, le=50, description="最大返回数量")
):
    """
    V1版量化选股筛选

    根据V1提示词标准筛选符合条件的股票：
    1. 技术面强势（均线多头排列、MACD金叉等）
    2. 量能配合良好（换手合理、放量上涨）
    3. 基本面安全（PE合理、盈利增长）
    4. 板块效应（行业强势、成交活跃）

    返回按综合评分排序的股票列表
    """
    try:
        from stock_analyzer import StockAnalyzer

        candidates = StockAnalyzer.screen_stocks(
            min_score=min_score,
            max_results=max_results
        )

        # 格式化输出
        results = []
        for analysis in candidates:
            results.append({
                "rank": len(results) + 1,
                "code": analysis.code,
                "name": analysis.name,
                "total_score": analysis.total_score,
                "recommendation": analysis.recommendation,
                "risk_level": analysis.risk_level,
                "module_scores": {
                    s.module: {
                        "score": s.score,
                        "max": s.max_score,
                        "passed": s.passed
                    }
                    for s in analysis.scores
                }
            })

        return {
            "screening_criteria": {
                "min_total_score": min_score,
                "module_pass_requirements": {
                    "技术面分析": "≥80% (40/50分)",
                    "量能配合": "≥75% (18.75/25分)",
                    "基本面安全": "≥60% (6/10分，硬性条件)",
                    "板块流动性": "≥65% (9.75/15分)"
                }
            },
            "total_candidates": len(results),
            "candidates": results
        }

    except Exception as e:
        logger.error(f"V1选股失败: {e}")
        raise HTTPException(status_code=500, detail=f"选股失败: {str(e)}")


@app.get("/api/market/sector-rankings")
async def get_sector_rankings(days: int = Query(20, ge=5, le=60, description="统计天数")):
    """
    获取行业板块涨幅排名

    用于判断板块强势程度
    """
    try:
        from stock_analyzer import StockAnalyzer

        rankings = StockAnalyzer.get_sector_rankings(days)

        return {
            "days": days,
            "total_sectors": len(rankings),
            "top_sectors": rankings[:20],  # 前20名
            "bottom_sectors": rankings[-10:] if len(rankings) >= 10 else rankings  # 后10名
        }

    except Exception as e:
        logger.error(f"获取板块排名失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取板块排名失败: {str(e)}")


@app.get("/api/market/amount-rankings")
async def get_amount_rankings(
    days: int = Query(20, ge=5, le=60, description="统计天数"),
    top_n: int = Query(100, ge=10, le=500, description="返回前N名")
):
    """
    获取股票成交额排名

    用于判断市场流动性分布
    """
    try:
        from stock_analyzer import StockAnalyzer

        rankings = StockAnalyzer.get_amount_rankings(days, top_n)

        return {
            "days": days,
            "total_stocks": len(rankings),
            "rankings": rankings
        }

    except Exception as e:
        logger.error(f"获取成交额排名失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取成交额排名失败: {str(e)}")


# ============ SQL Agent API (AI生成SQL查询) ============

class SQLQueryRequest(BaseModel):
    question: str = Field(..., description="用户问题，如：查询000001最近5天的收盘价")


@app.post("/api/sql-query")
async def sql_query_endpoint(request: SQLQueryRequest):
    """
    SQL Agent 端点 - AI生成SQL并执行

    流程:
    1. AI根据用户问题生成SQL
    2. 后端执行SQL查询PostgreSQL
    3. AI基于查询结果生成分析结论

    示例请求:
    {
        "question": "查询000001最近5天的收盘价"
    }
    """
    try:
        from sql_agent import SQLAgent
        import openai

        # 创建vLLM客户端
        client = openai.OpenAI(
            base_url=settings.VLLM_BASE_URL,
            api_key="dummy"
        )

        # 执行SQL Agent流程
        result = SQLAgent.process_query(request.question, client)

        return {
            "success": True,
            "question": request.question,
            "sql": result["sql"],
            "query_result": result["result"],
            "analysis": result["analysis"],
            "full_response": result["full_response"]
        }

    except Exception as e:
        logger.error(f"SQL查询失败: {e}")
        raise HTTPException(status_code=500, detail=f"SQL查询失败: {str(e)}")


@app.post("/v1/chat/completions-sql")
async def chat_completion_sql(request: ChatCompletionRequest):
    """
    带SQL Agent的Chat Completion

    当检测到用户询问股票数据时，使用SQL Agent生成查询并回答
    否则使用普通流程
    """
    # 获取用户问题
    user_content = " ".join([m.content for m in request.messages if m.role == "user"])

    # 判断是否涉及股票数据查询
    stock_keywords = ["股票", "股价", "收盘", "开盘", "成交量", "查询", "多少", "最近", "历史"]
    has_code = bool(re.search(r'\b\d{6}\b', user_content))
    is_stock_query = has_code and any(kw in user_content for kw in stock_keywords)

    if is_stock_query:
        logger.info(f"使用SQL Agent处理查询: {user_content[:50]}...")

        try:
            from sql_agent import SQLAgent
            import openai

            # 创建异步vLLM客户端
            client = openai.AsyncOpenAI(
                base_url=settings.VLLM_BASE_URL,
                api_key="dummy"
            )

            # 直接调用异步SQL Agent流程
            result = await SQLAgent.process_query(user_content, client)

            # 构造响应
            return JSONResponse(content={
                "model": request.model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": result["full_response"]
                    },
                    "finish_reason": "stop"
                }]
            })

        except Exception as e:
            logger.error(f"SQL Agent处理失败: {e}")
            import traceback
            logger.error(f"SQL Agent详细错误: {traceback.format_exc()}")
            # 降级到普通流程
            logger.info("降级到普通chat completion流程")

    # 使用普通流程
    return await chat_completion(request)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT)
