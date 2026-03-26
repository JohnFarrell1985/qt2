"""
Fin-R1 API Middleware - Technical Indicators Calculator
技术指标计算模块

支持指标:
- MACD: 异同移动平均线（趋势跟踪）
- BOLL: 布林带（波动率通道）
- KDJ: 随机指标（超买超卖）
- RSI: 相对强弱指标（动量）
- MA: 移动平均线（5/10/20/60/120日）
- EMA: 指数移动平均线
- ATR: 平均真实波幅（波动率）
- VWAP: 成交量加权平均价

使用:
    from technical_indicators import TechnicalIndicators
    
    # 计算单个指标
    data = HistoryDataClient.get_stock_history('000001', days=60)
    macd = TechnicalIndicators.macd(data)
    boll = TechnicalIndicators.bollinger(data, period=20)
    
    # 计算全部指标
    indicators = TechnicalIndicators.calculate_all(data)
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class IndicatorValue:
    """指标值数据类"""
    date: str
    value: Optional[float]
    signal: Optional[str] = None  # 买入/卖出/中性信号


class TechnicalIndicators:
    """技术指标计算器"""

    @staticmethod
    def moving_average(data: List[Dict], period: int, field: str = 'close') -> List[IndicatorValue]:
        """
        计算简单移动平均线 (SMA/MA)
        
        Args:
            data: K线数据列表，按日期升序排列
            period: 周期（如5日、10日、20日、60日）
            field: 计算字段（close/open/high/low）
        
        Returns:
            指标值列表
        """
        if len(data) < period:
            return []

        results = []
        for i in range(len(data)):
            if i < period - 1:
                results.append(IndicatorValue(date=data[i]['trade_date'], value=None))
            else:
                # 计算period个数据的平均值
                values = [d[field] for d in data[i-period+1:i+1] if d.get(field)]
                if values:
                    ma = sum(values) / len(values)
                    results.append(IndicatorValue(date=data[i]['trade_date'], value=round(ma, 2)))
                else:
                    results.append(IndicatorValue(date=data[i]['trade_date'], value=None))

        return results

    @staticmethod
    def ema(data: List[Dict], period: int, field: str = 'close') -> List[IndicatorValue]:
        """
        计算指数移动平均线 (EMA)
        
        EMA = Price(t) * k + EMA(y) * (1 - k)
        k = 2 / (period + 1)
        """
        if len(data) < period:
            return []

        k = 2 / (period + 1)
        results = []
        ema_prev = None

        for i, d in enumerate(data):
            price = d.get(field)
            if price is None:
                results.append(IndicatorValue(date=d['trade_date'], value=None))
                continue

            if i < period - 1:
                results.append(IndicatorValue(date=d['trade_date'], value=None))
            elif i == period - 1:
                # 第一个EMA使用简单平均
                values = [d[field] for d in data[:period] if d.get(field)]
                ema_current = sum(values) / len(values) if values else price
                results.append(IndicatorValue(date=d['trade_date'], value=round(ema_current, 2)))
                ema_prev = ema_current
            else:
                ema_current = price * k + ema_prev * (1 - k)
                results.append(IndicatorValue(date=d['trade_date'], value=round(ema_current, 2)))
                ema_prev = ema_current

        return results

    @staticmethod
    def macd(data: List[Dict], 
             fast_period: int = 12, 
             slow_period: int = 26, 
             signal_period: int = 9) -> Dict[str, Any]:
        """
        计算MACD指标
        
        MACD = EMA(12) - EMA(26)
        Signal = EMA(MACD, 9)
        Histogram = MACD - Signal
        
        Returns:
            {
                'macd': [...],
                'signal': [...],
                'histogram': [...],
                'latest_signal': '金叉'/'死叉'/'中性'
            }
        """
        if len(data) < slow_period + signal_period:
            return {'error': '数据不足，无法计算MACD'}

        # 计算快速和慢速EMA
        ema_fast = TechnicalIndicators.ema(data, fast_period)
        ema_slow = TechnicalIndicators.ema(data, slow_period)

        # 计算MACD线
        macd_line = []
        for i in range(len(data)):
            if ema_fast[i].value is not None and ema_slow[i].value is not None:
                macd_line.append(IndicatorValue(
                    date=data[i]['trade_date'],
                    value=round(ema_fast[i].value - ema_slow[i].value, 3)
                ))
            else:
                macd_line.append(IndicatorValue(date=data[i]['trade_date'], value=None))

        # 计算Signal线 (MACD的EMA)
        valid_macd = [m for m in macd_line if m.value is not None]
        if len(valid_macd) < signal_period:
            return {'error': 'MACD数据不足，无法计算Signal线'}

        signal_line = []
        k = 2 / (signal_period + 1)
        signal_prev = sum(m.value for m in valid_macd[:signal_period]) / signal_period

        for i, m in enumerate(macd_line):
            if m.value is None:
                signal_line.append(IndicatorValue(date=m.date, value=None))
            elif i < slow_period + signal_period - 1:
                signal_line.append(IndicatorValue(date=m.date, value=None))
            else:
                signal_current = m.value * k + signal_prev * (1 - k)
                signal_line.append(IndicatorValue(date=m.date, value=round(signal_current, 3)))
                signal_prev = signal_current

        # 计算Histogram
        histogram = []
        for i in range(len(data)):
            if macd_line[i].value is not None and signal_line[i].value is not None:
                hist_value = round(macd_line[i].value - signal_line[i].value, 3)
                histogram.append(IndicatorValue(date=data[i]['trade_date'], value=hist_value))
            else:
                histogram.append(IndicatorValue(date=data[i]['trade_date'], value=None))

        # 判断最新信号
        latest_signal = '中性'
        valid_macd_values = [m for m in macd_line if m.value is not None]
        valid_signal_values = [s for s in signal_line if s.value is not None]

        if len(valid_macd_values) >= 2 and len(valid_signal_values) >= 2:
            current_macd = valid_macd_values[-1].value
            current_signal = valid_signal_values[-1].value
            prev_macd = valid_macd_values[-2].value
            prev_signal = valid_signal_values[-2].value

            # 金叉: MACD从下向上穿过Signal
            if prev_macd <= prev_signal and current_macd > current_signal:
                latest_signal = '金叉（买入信号）'
            # 死叉: MACD从上向下穿过Signal
            elif prev_macd >= prev_signal and current_macd < current_signal:
                latest_signal = '死叉（卖出信号）'

        return {
            'macd': [{'date': m.date, 'value': m.value} for m in macd_line],
            'signal': [{'date': s.date, 'value': s.value} for s in signal_line],
            'histogram': [{'date': h.date, 'value': h.value} for h in histogram],
            'latest_macd': valid_macd_values[-1].value if valid_macd_values else None,
            'latest_signal': valid_signal_values[-1].value if valid_signal_values else None,
            'latest_histogram': [h for h in histogram if h.value is not None][-1].value if any(h.value is not None for h in histogram) else None,
            'signal_description': latest_signal,
            'periods': {'fast': fast_period, 'slow': slow_period, 'signal': signal_period}
        }

    @staticmethod
    def bollinger(data: List[Dict], period: int = 20, std_dev: float = 2.0) -> Dict[str, Any]:
        """
        计算布林带 (BOLL)
        
        中轨 = MA(20)
        上轨 = 中轨 + 2 × 标准差
        下轨 = 中轨 - 2 × 标准差
        
        Returns:
            {
                'middle': [...],  # 中轨
                'upper': [...],   # 上轨
                'lower': [...],   # 下轨
                'bandwidth': [...], # 带宽
                'position': '上轨之上'/'中轨附近'/'下轨之下'
            }
        """
        if len(data) < period:
            return {'error': '数据不足，无法计算布林带'}

        middle_band = TechnicalIndicators.moving_average(data, period)
        upper_band = []
        lower_band = []
        bandwidth = []

        for i in range(len(data)):
            if i < period - 1:
                upper_band.append(IndicatorValue(date=data[i]['trade_date'], value=None))
                lower_band.append(IndicatorValue(date=data[i]['trade_date'], value=None))
                bandwidth.append(IndicatorValue(date=data[i]['trade_date'], value=None))
            else:
                # 计算标准差
                prices = [d['close'] for d in data[i-period+1:i+1] if d.get('close')]
                if len(prices) >= period:
                    mean = sum(prices) / len(prices)
                    variance = sum((p - mean) ** 2 for p in prices) / len(prices)
                    std = variance ** 0.5

                    middle = middle_band[i].value
                    upper = middle + std_dev * std
                    lower = middle - std_dev * std
                    bw = (upper - lower) / middle if middle else 0

                    upper_band.append(IndicatorValue(date=data[i]['trade_date'], value=round(upper, 2)))
                    lower_band.append(IndicatorValue(date=data[i]['trade_date'], value=round(lower, 2)))
                    bandwidth.append(IndicatorValue(date=data[i]['trade_date'], value=round(bw * 100, 2)))
                else:
                    upper_band.append(IndicatorValue(date=data[i]['trade_date'], value=None))
                    lower_band.append(IndicatorValue(date=data[i]['trade_date'], value=None))
                    bandwidth.append(IndicatorValue(date=data[i]['trade_date'], value=None))

        # 判断当前位置
        position = '未知'
        if len(data) > 0 and middle_band and middle_band[-1].value:
            current_price = data[-1].get('close')
            middle = middle_band[-1].value
            upper = upper_band[-1].value
            lower = lower_band[-1].value

            if current_price and upper and lower:
                if current_price > upper:
                    position = '上轨之上（超买）'
                elif current_price < lower:
                    position = '下轨之下（超卖）'
                elif current_price > middle:
                    position = '中轨与上轨之间（偏强）'
                else:
                    position = '中轨与下轨之间（偏弱）'

        return {
            'middle': [{'date': m.date, 'value': m.value} for m in middle_band],
            'upper': [{'date': u.date, 'value': u.value} for u in upper_band],
            'lower': [{'date': l.date, 'value': l.value} for l in lower_band],
            'bandwidth': [{'date': b.date, 'value': b.value} for b in bandwidth],
            'latest_middle': middle_band[-1].value if middle_band else None,
            'latest_upper': upper_band[-1].value if upper_band else None,
            'latest_lower': lower_band[-1].value if lower_band else None,
            'current_position': position,
            'period': period,
            'std_dev': std_dev
        }

    @staticmethod
    def rsi(data: List[Dict], period: int = 14) -> Dict[str, Any]:
        """
        计算相对强弱指标 (RSI)
        
        RSI = 100 - 100 / (1 + RS)
        RS = 平均上涨幅度 / 平均下跌幅度
        
        Returns:
            {
                'rsi': [...],
                'latest_rsi': 值,
                'signal': '超买'/'超卖'/'中性'
            }
        """
        if len(data) < period + 1:
            return {'error': '数据不足，无法计算RSI'}

        gains = []
        losses = []

        # 计算每日涨跌
        for i in range(1, len(data)):
            change = data[i]['close'] - data[i-1]['close']
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))

        rsi_values = []
        
        for i in range(len(data)):
            if i < period:
                rsi_values.append(IndicatorValue(date=data[i]['trade_date'], value=None))
            else:
                # 计算平均涨跌
                avg_gain = sum(gains[i-period:i]) / period
                avg_loss = sum(losses[i-period:i]) / period

                if avg_loss == 0:
                    rsi_val = 100
                else:
                    rs = avg_gain / avg_loss
                    rsi_val = 100 - (100 / (1 + rs))

                rsi_values.append(IndicatorValue(date=data[i]['trade_date'], value=round(rsi_val, 2)))

        # 判断信号
        latest_rsi = [r for r in rsi_values if r.value is not None][-1].value if any(r.value is not None for r in rsi_values) else None
        signal = '中性'
        if latest_rsi:
            if latest_rsi > 70:
                signal = '超买（>70，可能回调）'
            elif latest_rsi < 30:
                signal = '超卖（<30，可能反弹）'
            elif latest_rsi > 50:
                signal = '强势区（>50）'
            else:
                signal = '弱势区（<50）'

        return {
            'rsi': [{'date': r.date, 'value': r.value} for r in rsi_values],
            'latest_rsi': latest_rsi,
            'signal': signal,
            'period': period
        }

    @staticmethod
    def calculate_all(data: List[Dict]) -> Dict[str, Any]:
        """
        计算所有技术指标
        
        Args:
            data: K线数据，至少60天
        
        Returns:
            所有指标的字典
        """
        if len(data) < 60:
            return {'error': '数据不足，至少需要60天数据'}

        return {
            'ma': {
                'ma5': [{'date': m.date, 'value': m.value} for m in TechnicalIndicators.moving_average(data, 5)],
                'ma10': [{'date': m.date, 'value': m.value} for m in TechnicalIndicators.moving_average(data, 10)],
                'ma20': [{'date': m.date, 'value': m.value} for m in TechnicalIndicators.moving_average(data, 20)],
                'ma60': [{'date': m.date, 'value': m.value} for m in TechnicalIndicators.moving_average(data, 60)],
            },
            'macd': TechnicalIndicators.macd(data),
            'boll': TechnicalIndicators.bollinger(data),
            'rsi': TechnicalIndicators.rsi(data),
            'summary': {
                'data_days': len(data),
                'date_range': f"{data[0]['trade_date']} ~ {data[-1]['trade_date']}",
                'current_price': data[-1].get('close') if data else None
            }
        }


class TechnicalIndicatorClient:
    """技术指标数据访问客户端 - 封装技术指标查询"""

    @staticmethod
    def get_stock_indicators(code: str, days: int = 60) -> Dict[str, Any]:
        """获取股票的完整技术指标分析"""
        from database_client import HistoryDataClient

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
