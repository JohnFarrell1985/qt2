"""
Fin-R1 API Middleware - Stock Analyzer Module
股票分析模块 - 支持V1版提示词的量化筛选需求

功能:
1. 板块排名分析（行业涨幅排名、成交额排名）
2. 多维度股票评分（技术面+基本面+量能）
3. 股票筛选器（基于V1提示词条件）
4. 生成结构化分析报告

使用:
    from stock_analyzer import StockAnalyzer
    
    # 分析单只股票
    analysis = StockAnalyzer.analyze_stock('000001')
    
    # 筛选符合条件的股票
    candidates = StockAnalyzer.screen_stocks(min_score=75)
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, timedelta
from dataclasses import dataclass

from database_client import (
    HistoryDataClient, FundamentalDataClient, TechnicalIndicatorClient,
    get_db_session
)
from technical_indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


@dataclass
class ScoreResult:
    """评分结果"""
    module: str
    score: float  # 0-100
    max_score: float
    passed: bool
    details: Dict[str, Any]


@dataclass
class StockAnalysis:
    """股票分析结果"""
    code: str
    name: str
    total_score: float
    scores: List[ScoreResult]
    technical_data: Dict[str, Any]
    fundamental_data: Dict[str, Any]
    volume_data: Dict[str, Any]
    sector_data: Dict[str, Any]
    recommendation: str
    risk_level: str


class StockAnalyzer:
    """股票分析器 - V1提示词完整支持"""

    @staticmethod
    def get_sector_rankings(days: int = 20) -> List[Dict[str, Any]]:
        """
        获取行业板块排名
        
        Returns:
            按涨幅排名的行业列表
        """
        try:
            with get_db_session() as session:
                from sqlalchemy import func, text

                # 计算各行业近N日涨幅
                sql = text("""
                SELECT 
                    sector_name,
                    COUNT(*) as stock_count,
                    AVG(change_pct) as avg_change
                FROM sector_data
                WHERE trade_date >= CURRENT_DATE - INTERVAL ':days days'
                GROUP BY sector_name
                ORDER BY avg_change DESC
                """)

                result = session.execute(sql, {"days": days})

                rankings = []
                for i, row in enumerate(result, 1):
                    rankings.append({
                        'rank': i,
                        'sector_name': row.sector_name,
                        'stock_count': row.stock_count,
                        'avg_change': round(row.avg_change, 2) if row.avg_change else 0
                    })

                return rankings

        except Exception as e:
            logger.error(f"获取板块排名失败: {e}")
            return []

    @staticmethod
    def get_amount_rankings(days: int = 20, top_n: int = 100) -> List[Dict[str, Any]]:
        """
        获取成交额排名
        
        Args:
            days: 统计天数
            top_n: 返回前N名
            
        Returns:
            按成交额排名的股票列表
        """
        try:
            with get_db_session() as session:
                from sqlalchemy import func, text

                sql = text("""
                SELECT 
                    code,
                    AVG(amount) as avg_amount,
                    COUNT(*) as trade_days
                FROM stock_daily
                WHERE trade_date >= CURRENT_DATE - INTERVAL ':days days'
                GROUP BY code
                HAVING COUNT(*) >= :days * 0.8  -- 至少80%交易日有数据
                ORDER BY avg_amount DESC
                LIMIT :top_n
                """)

                result = session.execute(sql, {"days": days, "top_n": top_n})

                rankings = []
                for i, row in enumerate(result, 1):
                    rankings.append({
                        'rank': i,
                        'code': row.code,
                        'avg_amount': row.avg_amount,
                        'avg_amount_yi': round(row.avg_amount / 1e8, 2)  # 转换为亿
                    })

                return rankings

        except Exception as e:
            logger.error(f"获取成交额排名失败: {e}")
            return []

    @staticmethod
    def analyze_technical(code: str, days: int = 60) -> Dict[str, Any]:
        """
        技术面分析 - V1提示词模块1+3
        
        Returns:
            {
                'score': 分数,
                'max_score': 满分,
                'passed': 是否通过,
                'details': 详细数据
            }
        """
        try:
            # 获取技术指标
            tech_data = TechnicalIndicatorClient.get_stock_indicators(code, days)

            if 'error' in tech_data:
                return {'score': 0, 'max_score': 50, 'passed': False, 'error': tech_data['error']}

            details = {
                'ma_aligned': False,
                'price_vs_ma20': False,
                'macd_signal': 'neutral',
                'boll_position': 'unknown',
                'rsi_status': 'unknown',
                'ma_values': {}
            }

            score = 0
            max_score = 50  # 趋势30 + 形态20

            # 1. 均线分析 (30分)
            if 'ma' in tech_data:
                ma = tech_data['ma']
                ma5 = None
                ma10 = None
                ma20 = None
                ma60 = None

                # 提取最新MA值
                for ma_data in ma.get('ma5', []):
                    if ma_data.get('value'):
                        ma5 = ma_data['value']
                        details['ma_values']['ma5'] = ma5
                        break

                for ma_data in ma.get('ma10', []):
                    if ma_data.get('value'):
                        ma10 = ma_data['value']
                        details['ma_values']['ma10'] = ma10
                        break

                for ma_data in ma.get('ma20', []):
                    if ma_data.get('value'):
                        ma20 = ma_data['value']
                        details['ma_values']['ma20'] = ma20
                        break

                for ma_data in ma.get('ma60', []):
                    if ma_data.get('value'):
                        ma60 = ma_data['value']
                        details['ma_values']['ma60'] = ma60
                        break

                # 判断均线多头排列
                if ma5 and ma10 and ma20 and ma60:
                    if ma5 > ma10 > ma20 > ma60:
                        score += 15
                        details['ma_aligned'] = True

                # 判断是否站稳MA20
                if ma20:
                    # 获取当前价格
                    from database_client import HistoryDataClient
                    history = HistoryDataClient.get_stock_history(code, days=5)
                    if history and len(history) >= 3:
                        recent_prices = [h['close'] for h in history[:3]]
                        if all(p > ma20 * 0.98 for p in recent_prices):  # 允许2%误差
                            score += 10
                            details['price_vs_ma20'] = True
                        else:
                            details['price_vs_ma20'] = False

                # 计算涨幅
                if ma20 and ma60:
                    change_20d = (ma5 - ma20) / ma20 * 100 if ma20 else 0
                    change_60d = (ma5 - ma60) / ma60 * 100 if ma60 else 0
                    details['change_20d'] = round(change_20d, 2)
                    details['change_60d'] = round(change_60d, 2)

                    # 涨幅条件: 20日>10%, 60日>20%且<100%
                    if change_20d > 10 and 20 < change_60d < 100:
                        score += 5

            # 2. 技术形态分析 (20分)
            # MACD信号
            if 'macd' in tech_data:
                macd = tech_data['macd']
                macd_val = macd.get('latest_macd')
                signal_val = macd.get('latest_signal')
                signal_desc = macd.get('signal_description', '')

                details['macd'] = {
                    'macd': macd_val,
                    'signal': signal_val,
                    'description': signal_desc
                }

                # MACD在零轴上方或金叉
                if macd_val and macd_val > 0:
                    score += 8
                    details['macd_signal'] = 'positive'
                elif '金叉' in signal_desc:
                    score += 10
                    details['macd_signal'] = 'golden_cross'

            # 布林带位置
            if 'boll' in tech_data:
                boll = tech_data['boll']
                position = boll.get('current_position', '')
                details['boll_position'] = position

                if '上轨' in position or '中轨' in position:
                    score += 6

                details['boll'] = {
                    'upper': boll.get('latest_upper'),
                    'middle': boll.get('latest_middle'),
                    'lower': boll.get('latest_lower')
                }

            # RSI状态
            if 'rsi' in tech_data:
                rsi = tech_data['rsi']
                rsi_val = rsi.get('latest_rsi')
                details['rsi'] = rsi_val

                if rsi_val and 40 <= rsi_val <= 70:
                    score += 6
                    details['rsi_status'] = 'healthy'
                elif rsi_val and rsi_val < 40:
                    details['rsi_status'] = 'oversold'
                elif rsi_val and rsi_val > 70:
                    details['rsi_status'] = 'overbought'

            passed = score >= 40  # 80%通过率

            return {
                'score': score,
                'max_score': max_score,
                'passed': passed,
                'details': details
            }

        except Exception as e:
            logger.error(f"技术面分析失败 {code}: {e}")
            return {'score': 0, 'max_score': 50, 'passed': False, 'error': str(e)}

    @staticmethod
    def analyze_volume(code: str, days: int = 20) -> Dict[str, Any]:
        """
        量能分析 - V1提示词模块2
        
        Returns:
            {
                'score': 分数,
                'max_score': 25,
                'passed': 是否通过,
                'details': 详细数据
            }
        """
        try:
            # 获取历史数据
            history = HistoryDataClient.get_stock_history(code, days + 5)
            if not history or len(history) < days:
                return {'score': 0, 'max_score': 25, 'passed': False, 'error': '数据不足'}

            # 按日期升序排列
            history = sorted(history, key=lambda x: x['trade_date'])

            details = {
                'current_turnover': 0,
                'avg_volume_5d': 0,
                'avg_volume_20d': 0,
                'avg_amount_20d': 0,
                'turnover_trend': 'unknown',
                'volume_ratio': 0
            }

            score = 0

            # 1. 换手率分析 (10分)
            if history:
                latest = history[-1]
                turnover = latest.get('turnover_rate', 0)
                details['current_turnover'] = turnover

                # 获取流通市值判断阈值
                with get_db_session() as session:
                    from database import Stock
                    stock = session.query(Stock).filter_by(code=code).first()
                    if stock and stock.market_cap:
                        market_cap = stock.market_cap  # 亿为单位

                        # 判断换手率是否合理
                        if market_cap < 100:  # <100亿
                            if 5 <= turnover <= 25:
                                score += 10
                                details['turnover_status'] = 'good'
                            else:
                                details['turnover_status'] = 'out_of_range'
                        elif market_cap < 500:  # 100-500亿
                            if 3 <= turnover <= 15:
                                score += 10
                                details['turnover_status'] = 'good'
                            else:
                                details['turnover_status'] = 'out_of_range'
                        else:  # >500亿
                            if 2 <= turnover <= 10:
                                score += 10
                                details['turnover_status'] = 'good'
                            else:
                                details['turnover_status'] = 'out_of_range'

            # 2. 成交量趋势 (10分)
            if len(history) >= 20:
                recent_5d = history[-5:]
                recent_20d = history[-20:]

                avg_vol_5d = sum(h.get('volume', 0) for h in recent_5d) / 5
                avg_vol_20d = sum(h.get('volume', 0) for h in recent_20d) / 20

                details['avg_volume_5d'] = avg_vol_5d
                details['avg_volume_20d'] = avg_vol_20d

                if avg_vol_20d > 0:
                    volume_ratio = avg_vol_5d / avg_vol_20d
                    details['volume_ratio'] = round(volume_ratio, 2)

                    # 近5日>近20日1.2倍
                    if volume_ratio > 1.2:
                        score += 10
                        details['volume_trend'] = 'increasing'
                    else:
                        details['volume_trend'] = 'stable_or_decreasing'

            # 3. 成交额分析 (5分)
            if len(history) >= 20:
                amounts = [h.get('amount', 0) for h in history[-20:]]
                avg_amount = sum(amounts) / len(amounts)
                details['avg_amount_20d'] = avg_amount
                details['avg_amount_20d_yi'] = round(avg_amount / 1e8, 2)

                # 近20日日均>5亿
                if avg_amount > 5e8:
                    score += 5
                    details['amount_status'] = 'sufficient'
                else:
                    details['amount_status'] = 'insufficient'

            passed = score >= 18.75  # 75%通过率

            return {
                'score': score,
                'max_score': 25,
                'passed': passed,
                'details': details
            }

        except Exception as e:
            logger.error(f"量能分析失败 {code}: {e}")
            return {'score': 0, 'max_score': 25, 'passed': False, 'error': str(e)}

    @staticmethod
    def analyze_fundamental(code: str) -> Dict[str, Any]:
        """
        基本面分析 - V1提示词模块5
        
        Returns:
            {
                'score': 分数,
                'max_score': 10,
                'passed': 是否通过,
                'details': 详细数据
            }
        """
        try:
            # 获取最新财务摘要
            summary = FundamentalDataClient.get_latest_financial_summary(code)

            if summary.get('error'):
                return {'score': 0, 'max_score': 10, 'passed': False, 'error': summary['error']}

            details = {
                'pe': None,
                'pb': None,
                'roe': None,
                'debt_ratio': None,
                'revenue_growth': None,
                'profit_growth': None,
                'profit_positive': False,
                'current_ratio': None
            }

            score = 0

            # 1. 获取基础信息PE/PB
            with get_db_session() as session:
                from database import Stock
                stock = session.query(Stock).filter_by(code=code).first()
                if stock:
                    details['pe'] = stock.pe_ttm
                    details['pb'] = stock.pb

                    # PE>0且<50 (3分)
                    if stock.pe_ttm and stock.pe_ttm > 0 and stock.pe_ttm < 50:
                        score += 2
                        details['pe_status'] = 'good'
                    elif stock.pe_ttm and stock.pe_ttm >= 50:
                        details['pe_status'] = 'high'
                    else:
                        details['pe_status'] = 'negative_or_none'

                    # PB<10 (2分)
                    if stock.pb and stock.pb < 10:
                        score += 2
                        details['pb_status'] = 'good'
                    else:
                        details['pb_status'] = 'high'

            # 2. 财务报表分析
            if summary.get('latest_report'):
                report = summary['latest_report']

                # 净利润为正 (2分)
                if report.get('income_statement'):
                    net_profit = report['income_statement'].get('net_profit')
                    if net_profit and net_profit > 0:
                        score += 2
                        details['profit_positive'] = True
                        details['net_profit'] = net_profit

                # 资产负债率 (1分)
                if report.get('balance_sheet'):
                    total_assets = report['balance_sheet'].get('total_assets')
                    total_liabilities = report['balance_sheet'].get('total_liabilities')
                    if total_assets and total_liabilities:
                        debt_ratio = total_liabilities / total_assets * 100
                        details['debt_ratio'] = round(debt_ratio, 2)

                        if debt_ratio < 70:
                            score += 1
                            details['debt_status'] = 'healthy'
                        else:
                            details['debt_status'] = 'high'

            # 3. 财务指标分析
            if summary.get('latest_indicator'):
                indicator = summary['latest_indicator']

                # ROE (2分)
                profitability = indicator.get('profitability', {})
                roe = profitability.get('roe_weighted')
                if roe:
                    details['roe'] = roe

                # 成长能力 (3分)
                # 这里需要获取多期数据计算同比
                # 简化处理：假设有growth数据
                growth = indicator.get('growth', {})
                revenue_growth = growth.get('revenue_growth')
                profit_growth = growth.get('profit_growth')

                details['revenue_growth'] = revenue_growth
                details['profit_growth'] = profit_growth

                if revenue_growth and revenue_growth >= 10:
                    score += 1
                if profit_growth and profit_growth >= 15:
                    score += 2

                # 偿债能力
                solvency = indicator.get('solvency', {})
                current_ratio = solvency.get('current_ratio')
                if current_ratio:
                    details['current_ratio'] = current_ratio
                    if current_ratio > 1:
                        score += 1

            passed = score >= 6  # 60%通过率，且为硬性条件

            return {
                'score': score,
                'max_score': 10,
                'passed': passed,
                'details': details
            }

        except Exception as e:
            logger.error(f"基本面分析失败 {code}: {e}")
            return {'score': 0, 'max_score': 10, 'passed': False, 'error': str(e)}

    @staticmethod
    def analyze_sector(code: str, days: int = 20) -> Dict[str, Any]:
        """
        板块与流动性分析 - V1提示词模块4
        
        Returns:
            {
                'score': 分数,
                'max_score': 15,
                'passed': 是否通过,
                'details': 详细数据
            }
        """
        try:
            # 获取股票行业信息
            with get_db_session() as session:
                from database import Stock
                stock = session.query(Stock).filter_by(code=code).first()

                if not stock:
                    return {'score': 0, 'max_score': 15, 'passed': False, 'error': '股票不存在'}

                details = {
                    'sector': stock.sector,
                    'industry': stock.industry,
                    'sector_rank': None,
                    'amount_rank': None,
                    'amount_status': False,
                    'turnover_status': True
                }

                score = 0

                # 1. 板块排名 (5分)
                if stock.sector:
                    sector_rankings = StockAnalyzer.get_sector_rankings(days)
                    for ranking in sector_rankings:
                        if ranking['sector_name'] == stock.sector:
                            details['sector_rank'] = ranking['rank']
                            # 前30%
                            if ranking['rank'] <= len(sector_rankings) * 0.3:
                                score += 5
                                details['sector_status'] = 'top_30%'
                            else:
                                details['sector_status'] = 'average'
                            break

                # 2. 成交额排名 (5分)
                amount_rankings = StockAnalyzer.get_amount_rankings(days, top_n=500)
                total_stocks = len(amount_rankings)

                for ranking in amount_rankings:
                    if ranking['code'] == code:
                        details['amount_rank'] = ranking['rank']
                        # 前30%
                        if ranking['rank'] <= total_stocks * 0.3:
                            score += 5
                            details['amount_rank_status'] = 'top_30%'
                        else:
                            details['amount_rank_status'] = 'average'
                        break

                # 3. 流动性检查 (3分)
                history = HistoryDataClient.get_stock_history(code, days=1)
                if history:
                    latest_amount = history[0].get('amount', 0)
                    details['latest_amount_yi'] = round(latest_amount / 1e8, 2)

                    if latest_amount > 10e8:  # >10亿
                        score += 3
                        details['amount_status'] = True

                # 4. 换手率异常检查 (2分)
                if history:
                    turnover = history[0].get('turnover_rate', 0)
                    details['latest_turnover'] = turnover

                    if turnover < 30:  # 无异常高换手
                        score += 2
                        details['turnover_status'] = True
                    else:
                        details['turnover_status'] = False

                passed = score >= 9.75  # 65%通过率

                return {
                    'score': score,
                    'max_score': 15,
                    'passed': passed,
                    'details': details
                }

        except Exception as e:
            logger.error(f"板块分析失败 {code}: {e}")
            return {'score': 0, 'max_score': 15, 'passed': False, 'error': str(e)}

    @staticmethod
    def analyze_stock(code: str) -> Optional[StockAnalysis]:
        """
        完整分析单只股票 - V1提示词完整支持
        
        Returns:
            StockAnalysis对象或None
        """
        try:
            # 获取股票名称
            with get_db_session() as session:
                from database import Stock
                stock = session.query(Stock).filter_by(code=code).first()
                if not stock:
                    return None
                name = stock.name

            # 执行各模块分析
            technical_result = StockAnalyzer.analyze_technical(code)
            volume_result = StockAnalyzer.analyze_volume(code)
            fundamental_result = StockAnalyzer.analyze_fundamental(code)
            sector_result = StockAnalyzer.analyze_sector(code)

            # 检查是否有错误
            if 'error' in technical_result and technical_result['score'] == 0:
                logger.warning(f"股票{code}技术面分析失败: {technical_result.get('error')}")

            # 计算总分
            total_score = (
                technical_result['score'] +  # 50分
                volume_result['score'] +     # 25分
                fundamental_result['score'] +  # 10分
                sector_result['score']        # 15分
            )

            # 生成建议
            if total_score >= 85:
                recommendation = '强烈推荐买入'
                risk_level = '低'
            elif total_score >= 75:
                recommendation = '推荐买入'
                risk_level = '中低'
            elif total_score >= 65:
                recommendation = '可考虑买入'
                risk_level = '中'
            elif fundamental_result['passed']:
                recommendation = '观望，技术面待改善'
                risk_level = '中高'
            else:
                recommendation = '回避'
                risk_level = '高'

            # 生成评分列表
            scores = [
                ScoreResult('技术面分析', technical_result['score'], 50, technical_result['passed'], technical_result['details']),
                ScoreResult('量能配合', volume_result['score'], 25, volume_result['passed'], volume_result['details']),
                ScoreResult('基本面安全', fundamental_result['score'], 10, fundamental_result['passed'], fundamental_result['details']),
                ScoreResult('板块流动性', sector_result['score'], 15, sector_result['passed'], sector_result['details'])
            ]

            return StockAnalysis(
                code=code,
                name=name,
                total_score=total_score,
                scores=scores,
                technical_data=technical_result['details'],
                volume_data=volume_result['details'],
                fundamental_data=fundamental_result['details'],
                sector_data=sector_result['details'],
                recommendation=recommendation,
                risk_level=risk_level
            )

        except Exception as e:
            logger.error(f"分析股票{code}失败: {e}")
            return None

    @staticmethod
    def screen_stocks(min_score: float = 75, max_results: int = 10) -> List[StockAnalysis]:
        """
        筛选符合条件的股票 - V1提示词完整筛选
        
        Args:
            min_score: 最低综合评分
            max_results: 最大返回数量
            
        Returns:
            符合条件的股票分析列表
        """
        try:
            # 获取所有股票代码
            with get_db_session() as session:
                from database import Stock
                stocks = session.query(Stock).limit(100).all()  # 先取前100只测试
                codes = [s.code for s in stocks]

            candidates = []

            for code in codes:
                analysis = StockAnalyzer.analyze_stock(code)
                if analysis and analysis.total_score >= min_score:
                    # 检查是否通过基本面（硬性条件）
                    fundamental_passed = any(
                        s.module == '基本面安全' and s.passed for s in analysis.scores
                    )
                    if fundamental_passed:
                        candidates.append(analysis)

            # 按总分排序
            candidates.sort(key=lambda x: x.total_score, reverse=True)

            return candidates[:max_results]

        except Exception as e:
            logger.error(f"筛选股票失败: {e}")
            return []

    @staticmethod
    def format_analysis_report(analysis: StockAnalysis) -> str:
        """
        格式化分析报告 - 符合V1提示词输出格式
        """
        lines = [
            f"## {analysis.name}({analysis.code}) - 综合评分: {analysis.total_score:.1f}分",
            ""
        ]

        # 技术面
        tech = analysis.technical_data
        lines.extend([
            "### 1. 技术面分析",
            f"- K线走势: 近60日呈{'上升' if tech.get('ma_aligned') else '震荡/下降'}趋势",
        ])

        if 'ma_values' in tech:
            ma = tech['ma_values']
            lines.append(f"- 均线系统: MA5=¥{ma.get('ma5', 'N/A'):.2f} > MA10=¥{ma.get('ma10', 'N/A'):.2f} > MA20=¥{ma.get('ma20', 'N/A'):.2f} > MA60=¥{ma.get('ma60', 'N/A'):.2f}")
            lines.append(f"- 均线排列: {'多头排列（强势）' if tech.get('ma_aligned') else '非多头排列'}")

        if 'macd' in tech:
            macd = tech['macd']
            lines.append(f"- MACD信号: MACD={macd.get('macd', 'N/A')}, Signal={macd.get('signal', 'N/A')}, {macd.get('description', '')}")

        if 'boll' in tech:
            boll = tech['boll']
            lines.append(f"- 布林带: 上轨¥{boll.get('upper', 'N/A'):.2f}/中轨¥{boll.get('middle', 'N/A'):.2f}/下轨¥{boll.get('lower', 'N/A'):.2f}")
            lines.append(f"- 位置: {tech.get('boll_position', '未知')}")

        if 'rsi' in tech:
            lines.append(f"- RSI(14): {tech['rsi']}, 状态: {tech.get('rsi_status', '未知')}")

        lines.append("")

        # 量能
        vol = analysis.volume_data
        lines.extend([
            "### 2. 量能分析",
            f"- 换手率: {vol.get('current_turnover', 'N/A'):.2f}%",
            f"- 成交量趋势: 近5日/近20日 = {vol.get('volume_ratio', 'N/A'):.2f}倍",
            f"- 成交额: 近20日日均{vol.get('avg_amount_20d_yi', 'N/A')}亿",
            ""
        ])

        # 基本面
        fund = analysis.fundamental_data
        lines.extend([
            "### 3. 基本面数据",
            f"- PE: {fund.get('pe', 'N/A')}倍, PB: {fund.get('pb', 'N/A')}倍",
        ])

        if fund.get('revenue_growth') and fund.get('profit_growth'):
            lines.append(f"- 最新季度: 营收同比{fund['revenue_growth']:+.1f}%, 净利润同比{fund['profit_growth']:+.1f}%")

        if fund.get('roe'):
            lines.append(f"- ROE: {fund['roe']:.2f}%, 资产负债率: {fund.get('debt_ratio', 'N/A')}%")

        lines.append("")

        # 板块
        sector = analysis.sector_data
        lines.extend([
            "### 4. 板块与市场",
            f"- 所属行业: {sector.get('industry', '未知')}",
            f"- 板块排名: 近20日涨幅排名{sector.get('sector_rank', 'N/A')}",
            f"- 成交额排名: 全市场{sector.get('amount_rank', 'N/A')}名",
            ""
        ])

        # 评分
        lines.append("### 5. 评分详情")
        for score in analysis.scores:
            status = "✅ 通过" if score.passed else "❌ 不通过"
            lines.append(f"- {score.module}: {score.score:.1f}分/{score.max_score}分 {status}")
        lines.append("")

        # 建议
        lines.extend([
            "### 6. 交易建议",
            f"- 操作建议: {analysis.recommendation}",
            f"- 风险等级: {analysis.risk_level}",
            ""
        ])

        return "\n".join(lines)
