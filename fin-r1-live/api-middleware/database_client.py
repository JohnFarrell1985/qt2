"""
Fin-R1 API Middleware - Database Client
数据库客户端（只读访问历史数据）
"""
import os
from datetime import date, timedelta
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"
)

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db_session():
    """获取数据库会话"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class HistoryDataClient:
    """历史数据客户端（只读）"""

    @staticmethod
    def get_stock_history(code: str, days: int = 30) -> List[Dict]:
        """获取股票历史数据"""
        try:
            with get_db_session() as session:
                sql = """
                SELECT code, trade_date, open, high, low, close,
                       volume, amount, change_pct, turnover_rate
                FROM stock_daily
                WHERE code = :code
                ORDER BY trade_date DESC
                LIMIT :limit
                """
                result = session.execute(text(sql), {"code": code, "limit": days})

                return [
                    {
                        "code": row.code,
                        "trade_date": row.trade_date.isoformat(),
                        "open": row.open,
                        "high": row.high,
                        "low": row.low,
                        "close": row.close,
                        "volume": row.volume,
                        "amount": row.amount,
                        "change_pct": row.change_pct,
                        "turnover_rate": row.turnover_rate
                    }
                    for row in result
                ]
        except Exception as e:
            logger.error(f"获取历史数据失败: {e}")
            return []

    @staticmethod
    def get_stock_statistics(code: str, days: int = 30) -> Dict[str, Any]:
        """获取股票统计信息"""
        try:
            with get_db_session() as session:
                # 使用参数化查询防止 SQL 注入
                # 注意: PostgreSQL INTERVAL 需要使用字符串拼接或函数
                from datetime import date, timedelta
                start_date = date.today() - timedelta(days=days)
                
                sql = text("""
                SELECT
                    COUNT(*) as total_days,
                    MAX(high) as period_high,
                    MIN(low) as period_low,
                    (SELECT close FROM stock_daily
                     WHERE code = :code ORDER BY trade_date DESC LIMIT 1) as current_price,
                    SUM(volume) as total_volume,
                    AVG(change_pct) as avg_change,
                    MAX(change_pct) as max_change,
                    MIN(change_pct) as min_change,
                    COUNT(CASE WHEN change_pct > 0 THEN 1 END) as up_days,
                    COUNT(CASE WHEN change_pct < 0 THEN 1 END) as down_days
                FROM stock_daily
                WHERE code = :code
                AND trade_date >= :start_date
                """)

                result = session.execute(sql, {"code": code, "start_date": start_date}).first()

                if not result or not result.current_price:
                    return {}

                return {
                    "code": code,
                    "analysis_days": days,
                    "current_price": float(result.current_price),
                    "period_high": float(result.period_high),
                    "period_low": float(result.period_low),
                    "total_volume": int(result.total_volume) if result.total_volume else 0,
                    "avg_change_pct": float(result.avg_change) if result.avg_change else 0,
                    "max_change_pct": float(result.max_change) if result.max_change else 0,
                    "min_change_pct": float(result.min_change) if result.min_change else 0,
                    "up_days": result.up_days,
                    "down_days": result.down_days,
                    "volatility": float(result.max_change - result.min_change) if result.max_change and result.min_change else 0
                }

        except Exception as e:
            logger.error(f"获取统计数据失败: {e}")
            return {}

    @staticmethod
    def search_stocks(keyword: str, limit: int = 10, order_by: str = "code") -> List[Dict]:
        """搜索股票（从基础信息表）

        Args:
            keyword: 搜索关键词
            limit: 返回数量限制
            order_by: 排序字段 (code 或 name)
        """
        try:
            with get_db_session() as session:
                order_clause = "ORDER BY " + ("code" if order_by == "code" else "name")
                sql = f"""
                SELECT code, name, exchange, industry, pe_ttm, pb
                FROM stocks
                WHERE name ILIKE :keyword
                {order_clause}
                LIMIT :limit
                """
                result = session.execute(
                    text(sql),
                    {"keyword": f"%{keyword}%", "limit": limit}
                )

                return [
                    {
                        "code": row.code,
                        "name": row.name,
                        "exchange": row.exchange,
                        "industry": row.industry,
                        "pe": row.pe_ttm,
                        "pb": row.pb
                    }
                    for row in result
                ]
        except Exception as e:
            logger.error(f"搜索股票失败: {e}")
            return []

    @staticmethod
    def get_db_status() -> Dict[str, Any]:
        """获取数据库状态"""
        try:
            with get_db_session() as session:
                # 统计各表记录数
                tables = ['stocks', 'stock_daily', 'stock_realtime']
                counts = {}

                for table in tables:
                    try:
                        result = session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        counts[table] = result.scalar()
                    except:
                        counts[table] = 0

                # 最新数据日期
                result = session.execute(
                    text("SELECT MAX(trade_date) FROM stock_daily")
                )
                latest_date = result.scalar()

                return {
                    "connected": True,
                    "table_counts": counts,
                    "latest_trade_date": latest_date.isoformat() if latest_date else None
                }

        except Exception as e:
            return {"connected": False, "error": str(e)}


# ============ 基本面数据 DAO ============

class FundamentalDataClient:
    """基本面数据访问客户端"""

    @staticmethod
    def get_financial_reports(
        code: str,
        report_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """获取财务报表数据"""
        try:
            with get_db_session() as session:
                from database import StockFinancialReport

                query = session.query(StockFinancialReport).filter_by(code=code)

                if report_type:
                    query = query.filter_by(report_type=report_type)

                reports = query.order_by(
                    StockFinancialReport.report_date.desc()
                ).limit(limit).all()

                return [r.to_dict() for r in reports]

        except Exception as e:
            logger.error(f"获取财务报表失败: {e}")
            return []

    @staticmethod
    def get_financial_indicators(
        code: str,
        limit: int = 10
    ) -> List[Dict]:
        """获取财务指标数据"""
        try:
            with get_db_session() as session:
                from database import StockFinancialIndicator

                indicators = session.query(StockFinancialIndicator).filter_by(
                    code=code
                ).order_by(
                    StockFinancialIndicator.report_date.desc()
                ).limit(limit).all()

                return [i.to_dict() for i in indicators]

        except Exception as e:
            logger.error(f"获取财务指标失败: {e}")
            return []

    @staticmethod
    def get_latest_financial_summary(code: str) -> Dict[str, Any]:
        """获取最新财务摘要（综合数据）"""
        try:
            with get_db_session() as session:
                from database import StockFinancialReport, StockFinancialIndicator

                # 获取最新的财务报表
                latest_report = session.query(StockFinancialReport).filter_by(
                    code=code
                ).order_by(StockFinancialReport.report_date.desc()).first()

                # 获取最新的财务指标
                latest_indicator = session.query(StockFinancialIndicator).filter_by(
                    code=code
                ).order_by(StockFinancialIndicator.report_date.desc()).first()

                result = {
                    "code": code,
                    "latest_report": None,
                    "latest_indicator": None
                }

                if latest_report:
                    result["latest_report"] = latest_report.to_dict()

                if latest_indicator:
                    result["latest_indicator"] = latest_indicator.to_dict()

                return result

        except Exception as e:
            logger.error(f"获取财务摘要失败: {e}")
            return {"code": code, "error": str(e)}

    @staticmethod
    def get_profitability_analysis(code: str) -> Dict[str, Any]:
        """获取盈利能力分析"""
        try:
            with get_db_session() as session:
                from database import StockFinancialIndicator

                indicators = session.query(StockFinancialIndicator).filter_by(
                    code=code
                ).order_by(
                    StockFinancialIndicator.report_date.desc()
                ).limit(8).all()  # 最近8期

                if not indicators:
                    return {"code": code, "message": "无盈利能力数据"}

                return {
                    "code": code,
                    "analysis": {
                        "roe_trend": [i.roe_weighted for i in indicators if i.roe_weighted],
                        "profit_margin_trend": [i.net_profit_margin for i in indicators if i.net_profit_margin],
                        "gross_margin_trend": [i.gross_profit_margin for i in indicators if i.gross_profit_margin],
                        "latest": {
                            "roe": indicators[0].roe_weighted,
                            "net_profit_margin": indicators[0].net_profit_margin,
                            "gross_profit_margin": indicators[0].gross_profit_margin,
                            "core_profit_margin": indicators[0].core_profit_margin
                        }
                    }
                }

        except Exception as e:
            logger.error(f"获取盈利能力分析失败: {e}")
            return {"code": code, "error": str(e)}

    @staticmethod
    def get_solvency_analysis(code: str) -> Dict[str, Any]:
        """获取偿债能力分析"""
        try:
            with get_db_session() as session:
                from database import StockFinancialIndicator

                indicators = session.query(StockFinancialIndicator).filter_by(
                    code=code
                ).order_by(
                    StockFinancialIndicator.report_date.desc()
                ).limit(4).all()

                if not indicators:
                    return {"code": code, "message": "无偿债能力数据"}

                return {
                    "code": code,
                    "analysis": {
                        "debt_ratio_trend": [i.debt_asset_ratio for i in indicators if i.debt_asset_ratio],
                        "current_ratio_trend": [i.current_ratio for i in indicators if i.current_ratio],
                        "quick_ratio_trend": [i.quick_ratio for i in indicators if i.quick_ratio],
                        "latest": {
                            "debt_ratio": indicators[0].debt_asset_ratio,
                            "current_ratio": indicators[0].current_ratio,
                            "quick_ratio": indicators[0].quick_ratio,
                            "cash_ratio": indicators[0].cash_ratio
                        }
                    }
                }

        except Exception as e:
            logger.error(f"获取偿债能力分析失败: {e}")
            return {"code": code, "error": str(e)}


# ============ 技术指标数据 DAO ============

class TechnicalIndicatorClient:
    """技术指标数据访问客户端"""

    @staticmethod
    def get_stock_indicators(code: str, days: int = 60) -> Dict[str, Any]:
        """获取股票的完整技术指标分析"""
        from technical_indicators import TechnicalIndicators

        try:
            # 获取历史数据
            history = HistoryDataClient.get_stock_history(code, days)
            if not history:
                return {'error': '无历史数据', 'code': code}

            # 数据按日期升序排列（计算指标需要）
            history = sorted(history, key=lambda x: x['trade_date'])

            # 计算所有指标
            indicators = TechnicalIndicators.calculate_all(history)

            # 添加代码信息
            indicators['code'] = code

            return indicators

        except Exception as e:
            logger.error(f"获取技术指标失败: {e}")
            return {'error': str(e), 'code': code}

    @staticmethod
    def get_indicator_summary(code: str) -> Dict[str, Any]:
        """获取技术指标摘要（用于prompt）"""
        from technical_indicators import TechnicalIndicators

        indicators = TechnicalIndicatorClient.get_stock_indicators(code, days=60)

        if 'error' in indicators:
            return indicators

        summary = {
            'code': code,
            'ma': {},
            'macd': {},
            'boll': {},
            'rsi': {}
        }

        # 移动平均线摘要
        if 'ma' in indicators:
            for ma_name, ma_data in indicators['ma'].items():
                valid_values = [m['value'] for m in ma_data if m['value'] is not None]
                if valid_values:
                    summary['ma'][ma_name] = valid_values[-1]

        # MACD摘要
        if 'macd' in indicators and 'latest_macd' in indicators['macd']:
            summary['macd'] = {
                'macd': indicators['macd'].get('latest_macd'),
                'signal': indicators['macd'].get('latest_signal'),
                'histogram': indicators['macd'].get('latest_histogram'),
                'description': indicators['macd'].get('signal_description')
            }

        # BOLL摘要
        if 'boll' in indicators and 'latest_middle' in indicators['boll']:
            summary['boll'] = {
                'middle': indicators['boll'].get('latest_middle'),
                'upper': indicators['boll'].get('latest_upper'),
                'lower': indicators['boll'].get('latest_lower'),
                'position': indicators['boll'].get('current_position')
            }

        # RSI摘要
        if 'rsi' in indicators and 'latest_rsi' in indicators['rsi']:
            summary['rsi'] = {
                'value': indicators['rsi'].get('latest_rsi'),
                'signal': indicators['rsi'].get('signal')
            }

        return summary

    @staticmethod
    def get_multi_indicator_analysis(code: str) -> Dict[str, Any]:
        """获取多指标综合分析（用于AI分析）"""
        summary = TechnicalIndicatorClient.get_indicator_summary(code)

        if 'error' in summary:
            return summary

        # 综合判断
        analysis = {
            'code': code,
            'indicators': summary,
            'trend': '中性',
            'momentum': '中性',
            'volatility': '中性',
            'recommendation': '观望'
        }

        # 趋势判断（基于MA）
        if summary['ma']:
            ma5 = summary['ma'].get('ma5')
            ma20 = summary['ma'].get('ma20')
            ma60 = summary['ma'].get('ma60')

            if ma5 and ma20 and ma60:
                if ma5 > ma20 > ma60:
                    analysis['trend'] = '上升趋势（多头排列）'
                elif ma5 < ma20 < ma60:
                    analysis['trend'] = '下降趋势（空头排列）'
                else:
                    analysis['trend'] = '震荡整理'

        # 动量判断（基于MACD和RSI）
        macd_signal = summary.get('macd', {}).get('description', '')
        rsi_signal = summary.get('rsi', {}).get('signal', '')

        if '金叉' in macd_signal or '超卖' in rsi_signal:
            analysis['momentum'] = '偏多（买入信号）'
        elif '死叉' in macd_signal or '超买' in rsi_signal:
            analysis['momentum'] = '偏空（卖出信号）'

        # 波动率判断（基于BOLL）
        boll_position = summary.get('boll', {}).get('position', '')
        if '上轨之上' in boll_position:
            analysis['volatility'] = '超买区间（关注回调）'
        elif '下轨之下' in boll_position:
            analysis['volatility'] = '超卖区间（关注反弹）'

        # 综合建议
        if analysis['trend'] == '上升趋势（多头排列）' and '偏多' in analysis['momentum']:
            analysis['recommendation'] = '强势上涨，可持有或逢低买入'
        elif analysis['trend'] == '下降趋势（空头排列）' and '偏空' in analysis['momentum']:
            analysis['recommendation'] = '弱势下跌，建议观望或减仓'
        elif '超卖' in analysis['volatility'] and '偏多' in analysis['momentum']:
            analysis['recommendation'] = '超卖反弹机会，可关注'
        elif '超买' in analysis['volatility'] and '偏空' in analysis['momentum']:
            analysis['recommendation'] = '超买回调风险，注意止盈'
        else:
            analysis['recommendation'] = '趋势不明，建议观望'

        return analysis
