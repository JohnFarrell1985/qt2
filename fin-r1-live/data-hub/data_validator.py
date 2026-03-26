"""
Fin-R1 Data Hub - Data Validator Module
数据完整性验证模块

功能:
1. 验证下载的历史数据是否完整
2. 检查实时数据字段是否齐全
3. 检测数据异常和缺失
4. 生成数据质量报告
"""
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

from database import get_db_session, Stock, StockDaily, StockRealtime, DataSyncLog

logger = logging.getLogger(__name__)


class DataValidator:
    """数据完整性验证器"""

    # 历史数据必要字段
    REQUIRED_HISTORY_FIELDS = [
        'code', 'trade_date', 'open', 'high', 'low', 'close',
        'volume', 'amount', 'change', 'change_pct', 'turnover_rate', 'amplitude'
    ]

    # 实时数据必要字段
    REQUIRED_REALTIME_FIELDS = [
        'code', 'timestamp', 'price', 'change', 'change_pct',
        'volume', 'amount', 'turnover_rate', 'amplitude'
    ]

    def __init__(self):
        self.issues = []
        self.warnings = []

    def validate_history_data(self, data: List[Dict], stock_code: str) -> Tuple[bool, List[str]]:
        """
        验证历史数据完整性

        Returns:
            (是否有效, 问题列表)
        """
        issues = []

        if not data:
            issues.append(f"股票 {stock_code}: 无历史数据")
            return False, issues

        # 检查必填字段
        for idx, record in enumerate(data):
            missing_fields = [f for f in self.REQUIRED_HISTORY_FIELDS if f not in record]
            if missing_fields:
                issues.append(f"股票 {stock_code} 第{idx+1}条记录缺少字段: {missing_fields}")

            # 检查数值有效性
            if record.get('volume', 0) < 0:
                issues.append(f"股票 {stock_code} 第{idx+1}条记录成交量为负数")

            if record.get('high', 0) < record.get('low', 0):
                issues.append(f"股票 {stock_code} 第{idx+1}条记录最高价低于最低价")

            if record.get('close', 0) < 0:
                issues.append(f"股票 {stock_code} 第{idx+1}条记录收盘价为负数")

        # 检查日期连续性
        if len(data) > 1:
            dates = [r['trade_date'] for r in data if 'trade_date' in r]
            dates.sort()

            # 检查是否有周末交易日的异常数据
            for d in dates:
                if isinstance(d, date):
                    if d.weekday() >= 5:  # 周六或周日
                        issues.append(f"股票 {stock_code} 存在周末交易数据: {d}")

        return len(issues) == 0, issues

    def validate_realtime_data(self, data: Dict, stock_code: str) -> Tuple[bool, List[str]]:
        """
        验证实时数据完整性

        Returns:
            (是否有效, 问题列表)
        """
        issues = []

        if not data:
            issues.append(f"股票 {stock_code}: 无实时数据")
            return False, issues

        # 检查必填字段
        missing_fields = [f for f in self.REQUIRED_REALTIME_FIELDS if f not in data]
        if missing_fields:
            issues.append(f"股票 {stock_code} 实时数据缺少字段: {missing_fields}")

        # 检查数值有效性
        if data.get('price', 0) <= 0:
            issues.append(f"股票 {stock_code} 实时价格异常: {data.get('price')}")

        if data.get('volume', 0) < 0:
            issues.append(f"股票 {stock_code} 实时成交量为负数")

        # 检查数据时效性
        timestamp = data.get('timestamp')
        if timestamp:
            if isinstance(timestamp, datetime):
                age_minutes = (datetime.now() - timestamp).total_seconds() / 60
                if age_minutes > 10:  # 数据超过10分钟
                    issues.append(f"股票 {stock_code} 实时数据已过期 {age_minutes:.1f} 分钟")

        return len(issues) == 0, issues

    def check_database_completeness(self) -> Dict[str, Any]:
        """
        检查数据库数据完整性

        Returns:
            完整性报告
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "stocks": {},
            "history": {},
            "realtime": {},
            "issues": []
        }

        try:
            with get_db_session() as session:
                # 1. 检查股票基础信息
                stock_count = session.query(Stock).count()
                report["stocks"]["count"] = stock_count

                if stock_count == 0:
                    report["issues"].append("股票基础信息表为空")

                # 2. 检查历史数据
                daily_count = session.query(StockDaily).count()
                report["history"]["total_records"] = daily_count

                # 获取日期范围
                min_date = session.query(StockDaily.trade_date).order_by(
                    StockDaily.trade_date.asc()
                ).first()
                max_date = session.query(StockDaily.trade_date).order_by(
                    StockDaily.trade_date.desc()
                ).first()

                if min_date and max_date:
                    report["history"]["date_range"] = {
                        "min": min_date[0].isoformat(),
                        "max": max_date[0].isoformat()
                    }

                    # 检查数据新鲜度
                    days_since_last = (date.today() - max_date[0]).days
                    report["history"]["days_since_last_update"] = days_since_last

                    if days_since_last > 3:
                        report["issues"].append(f"历史数据已落后 {days_since_last} 天")

                # 3. 检查每只股票的历史数据完整性
                stocks = session.query(Stock.code).all()
                incomplete_stocks = []

                for (code,) in stocks[:100]:  # 检查前100只
                    count = session.query(StockDaily).filter_by(code=code).count()
                    if count == 0:
                        incomplete_stocks.append(code)

                if incomplete_stocks:
                    report["history"]["incomplete_stocks"] = incomplete_stocks[:10]
                    report["issues"].append(f"{len(incomplete_stocks)} 只股票缺少历史数据")

                # 4. 检查交易日完整性
                if min_date and max_date:
                    total_days = (max_date[0] - min_date[0]).days
                    trading_days = session.query(StockDaily.trade_date).distinct().count()

                    # 粗略估计：约70%的工作日是交易日
                    expected_trading_days = int(total_days * 0.7)

                    if trading_days < expected_trading_days * 0.8:
                        report["issues"].append(
                            f"交易日数据可能不完整: {trading_days}/{expected_trading_days}"
                        )

        except Exception as e:
            report["issues"].append(f"数据库检查失败: {str(e)}")
            logger.error(f"数据库完整性检查失败: {e}")

        return report

    def check_data_quality(self, sample_size: int = 100) -> Dict[str, Any]:
        """
        检查数据质量

        Args:
            sample_size: 抽样检查的股票数量

        Returns:
            质量报告
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "sample_size": sample_size,
            "checks": {}
        }

        try:
            with get_db_session() as session:
                # 1. 价格异常检查
                price_anomalies = session.query(StockDaily).filter(
                    StockDaily.close > StockDaily.high * 1.1
                ).count()
                report["checks"]["price_anomalies"] = price_anomalies

                # 2. 成交量异常检查
                volume_anomalies = session.query(StockDaily).filter(
                    StockDaily.volume == 0,
                    StockDaily.close > 0
                ).count()
                report["checks"]["zero_volume_with_price"] = volume_anomalies

                # 3. 涨跌幅异常检查
                change_anomalies = session.query(StockDaily).filter(
                    abs(StockDaily.change_pct) > 20  # A股涨跌停限制
                ).count()
                report["checks"]["extreme_changes"] = change_anomalies

                # 4. 换手率异常检查
                turnover_anomalies = session.query(StockDaily).filter(
                    StockDaily.turnover_rate > 50  # 超过50%换手率较少见
                ).count()
                report["checks"]["high_turnover"] = turnover_anomalies

        except Exception as e:
            report["error"] = str(e)
            logger.error(f"数据质量检查失败: {e}")

        return report

    def generate_completeness_report(self) -> str:
        """生成数据完整性报告（文本格式）"""
        report = self.check_database_completeness()
        quality = self.check_data_quality()

        lines = []
        lines.append("=" * 60)
        lines.append("Fin-R1 数据库完整性报告")
        lines.append("=" * 60)
        lines.append(f"生成时间: {report['timestamp']}")
        lines.append("")

        # 股票基础信息
        lines.append("【股票基础信息】")
        lines.append(f"  股票总数: {report['stocks'].get('count', 'N/A')}")
        lines.append("")

        # 历史数据
        lines.append("【历史数据】")
        history = report.get('history', {})
        if 'total_records' in history:
            lines.append(f"  总记录数: {history['total_records']:,}")

        if 'date_range' in history:
            dr = history['date_range']
            lines.append(f"  数据范围: {dr['min']} 至 {dr['max']}")

        if 'days_since_last_update' in history:
            days = history['days_since_last_update']
            status = "✅ 最新" if days <= 1 else f"⚠️ 落后 {days} 天"
            lines.append(f"  数据新鲜度: {status}")
        lines.append("")

        # 数据质量
        lines.append("【数据质量】")
        checks = quality.get('checks', {})
        lines.append(f"  价格异常: {checks.get('price_anomalies', 0)}")
        lines.append(f"  零成交量异常: {checks.get('zero_volume_with_price', 0)}")
        lines.append(f"  极端涨跌幅: {checks.get('extreme_changes', 0)}")
        lines.append(f"  高换手率: {checks.get('high_turnover', 0)}")
        lines.append("")

        # 问题列表
        if report.get('issues'):
            lines.append("【发现的问题】")
            for issue in report['issues']:
                lines.append(f"  ⚠️  {issue}")
        else:
            lines.append("【状态】✅ 数据完整性良好")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


def validate_downloaded_data(data: List[Dict], data_type: str = "history") -> bool:
    """
    快速验证下载数据的入口函数

    Args:
        data: 下载的数据
        data_type: "history" 或 "realtime"

    Returns:
        是否通过验证
    """
    validator = DataValidator()

    if data_type == "history":
        is_valid, issues = validator.validate_history_data(data, data[0].get('code', 'UNKNOWN') if data else 'UNKNOWN')
    elif data_type == "realtime":
        is_valid, issues = validator.validate_realtime_data(data, data.get('code', 'UNKNOWN'))
    else:
        logger.error(f"未知的数据类型: {data_type}")
        return False

    if not is_valid:
        for issue in issues:
            logger.warning(f"数据验证: {issue}")

    return is_valid


if __name__ == "__main__":
    # 运行完整性检查
    validator = DataValidator()
    print(validator.generate_completeness_report())
