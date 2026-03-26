"""
Fin-R1 Data Hub - Fundamental Data Fetcher
公司基本面数据获取模块

功能:
1. 获取财务报表数据（资产负债表、利润表、现金流量表）
2. 获取财务分析指标
3. 计算关键财务比率
4. 数据下载和增量更新

数据源: akshare (东方财富/新浪财经)
"""
import asyncio
import akshare as ak
import pandas as pd
from datetime import datetime, date
from typing import List, Dict, Any, Optional
import logging

from database import (
    get_db_session,
    StockFinancialReport,
    StockFinancialIndicator,
    StockDAO
)

logger = logging.getLogger(__name__)


class FundamentalDataFetcher:
    """公司基本面数据获取器"""

    def __init__(self):
        self.downloaded_count = 0
        self.failed_stocks = []

    async def _run_sync(self, func, *args, timeout: int = 60, **kwargs):
        """在线程池中运行同步函数"""
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: func(*args, **kwargs)),
            timeout=timeout
        )

    async def fetch_balance_sheet(self, stock_code: str) -> pd.DataFrame:
        """
        获取资产负债表数据

        接口: ak.stock_balance_sheet_by_report_em
        数据源: 东方财富
        """
        try:
            df = await self._run_sync(
                ak.stock_balance_sheet_by_report_em,
                symbol=stock_code
            )
            return df
        except Exception as e:
            logger.error(f"获取{stock_code}资产负债表失败: {e}")
            return pd.DataFrame()

    async def fetch_income_statement(self, stock_code: str) -> pd.DataFrame:
        """
        获取利润表数据

        接口: ak.stock_profit_sheet_by_report_em
        数据源: 东方财富
        """
        try:
            df = await self._run_sync(
                ak.stock_profit_sheet_by_report_em,
                symbol=stock_code
            )
            return df
        except Exception as e:
            logger.error(f"获取{stock_code}利润表失败: {e}")
            return pd.DataFrame()

    async def fetch_cash_flow(self, stock_code: str) -> pd.DataFrame:
        """
        获取现金流量表数据

        接口: ak.stock_cash_flow_sheet_by_report_em
        数据源: 东方财富
        """
        try:
            df = await self._run_sync(
                ak.stock_cash_flow_sheet_by_report_em,
                symbol=stock_code
            )
            return df
        except Exception as e:
            logger.error(f"获取{stock_code}现金流量表失败: {e}")
            return pd.DataFrame()

    async def fetch_financial_indicators(self, stock_code: str) -> pd.DataFrame:
        """
        获取财务分析指标

        接口: ak.stock_financial_analysis_indicator
        数据源: 新浪财经
        包含: 盈利能力、偿债能力、运营效率、成长能力等30+指标
        """
        try:
            df = await self._run_sync(
                ak.stock_financial_analysis_indicator,
                symbol=stock_code
            )
            return df
        except Exception as e:
            logger.error(f"获取{stock_code}财务指标失败: {e}")
            return pd.DataFrame()

    async def fetch_stock_financial_abstract(self, stock_code: str) -> Dict[str, Any]:
        """
        获取财务摘要数据（快速获取关键指标）

        接口: ak.stock_financial_abstract
        数据源: 新浪财经
        """
        try:
            df = await self._run_sync(
                ak.stock_financial_abstract,
                symbol=stock_code
            )
            if not df.empty:
                return df.iloc[0].to_dict()
            return {}
        except Exception as e:
            logger.error(f"获取{stock_code}财务摘要失败: {e}")
            return {}

    def parse_balance_sheet(self, df: pd.DataFrame, stock_code: str) -> List[Dict]:
        """解析资产负债表数据"""
        if df.empty:
            return []

        records = []
        for _, row in df.iterrows():
            try:
                # 提取报告期
                report_date_str = str(row.get('报告期', ''))
                if not report_date_str:
                    continue
                report_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()

                record = {
                    'code': stock_code,
                    'report_type': 'balance_sheet',
                    'report_period': self._get_report_period(report_date),
                    'report_date': report_date,

                    # 资产负债表核心指标
                    'total_assets': self._parse_float(row.get('资产总计')),
                    'total_liabilities': self._parse_float(row.get('负债合计')),
                    'total_equity': self._parse_float(row.get('所有者权益合计')),
                    'current_assets': self._parse_float(row.get('流动资产合计')),
                    'current_liabilities': self._parse_float(row.get('流动负债合计')),
                    'inventory': self._parse_float(row.get('存货')),
                    'accounts_receivable': self._parse_float(row.get('应收账款')),
                    'cash_and_equivalents': self._parse_float(row.get('货币资金')),
                    'fixed_assets': self._parse_float(row.get('固定资产')),
                }

                # 计算财务比率
                record = self._calculate_balance_ratios(record)
                records.append(record)

            except Exception as e:
                logger.warning(f"解析{stock_code}资产负债表行数据失败: {e}")
                continue

        return records

    def parse_income_statement(self, df: pd.DataFrame, stock_code: str) -> List[Dict]:
        """解析利润表数据"""
        if df.empty:
            return []

        records = []
        for _, row in df.iterrows():
            try:
                report_date_str = str(row.get('报告期', ''))
                if not report_date_str:
                    continue
                report_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()

                record = {
                    'code': stock_code,
                    'report_type': 'income_statement',
                    'report_period': self._get_report_period(report_date),
                    'report_date': report_date,

                    # 利润表核心指标
                    'total_revenue': self._parse_float(row.get('营业收入')),
                    'operating_profit': self._parse_float(row.get('营业利润')),
                    'net_profit': self._parse_float(row.get('净利润')),
                    'gross_profit': self._parse_float(row.get('营业总收入')) - self._parse_float(row.get('营业成本')),
                    'operating_cost': self._parse_float(row.get('营业成本')),
                    'selling_expenses': self._parse_float(row.get('销售费用')),
                    'admin_expenses': self._parse_float(row.get('管理费用')),
                    'financial_expenses': self._parse_float(row.get('财务费用')),
                    'rd_expenses': self._parse_float(row.get('研发费用')),
                }

                # 计算盈利能力比率
                record = self._calculate_income_ratios(record)
                records.append(record)

            except Exception as e:
                logger.warning(f"解析{stock_code}利润表行数据失败: {e}")
                continue

        return records

    def parse_cash_flow(self, df: pd.DataFrame, stock_code: str) -> List[Dict]:
        """解析现金流量表数据"""
        if df.empty:
            return []

        records = []
        for _, row in df.iterrows():
            try:
                report_date_str = str(row.get('报告期', ''))
                if not report_date_str:
                    continue
                report_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()

                record = {
                    'code': stock_code,
                    'report_type': 'cash_flow',
                    'report_period': self._get_report_period(report_date),
                    'report_date': report_date,

                    # 现金流量表核心指标
                    'net_cash_flow': self._parse_float(row.get('现金及现金等价物净增加额')),
                    'operating_cash_flow': self._parse_float(row.get('经营活动产生的现金流量净额')),
                    'investing_cash_flow': self._parse_float(row.get('投资活动产生的现金流量净额')),
                    'financing_cash_flow': self._parse_float(row.get('筹资活动产生的现金流量净额')),
                }

                records.append(record)

            except Exception as e:
                logger.warning(f"解析{stock_code}现金流量表行数据失败: {e}")
                continue

        return records

    def parse_financial_indicators(self, df: pd.DataFrame, stock_code: str) -> List[Dict]:
        """解析财务分析指标数据"""
        if df.empty:
            return []

        records = []
        for _, row in df.iterrows():
            try:
                # 提取日期
                date_str = str(row.get('日期', ''))
                if not date_str:
                    continue
                report_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                record = {
                    'code': stock_code,
                    'report_date': report_date,

                    # 每股指标
                    'eps_basic': self._parse_float(row.get('摊薄每股收益')),
                    'eps_diluted': self._parse_float(row.get('加权每股收益')),
                    'bps': self._parse_float(row.get('每股净资产')),

                    # 盈利能力
                    'roe_weighted': self._parse_float(row.get('净资产收益率')),
                    'roe_diluted': self._parse_float(row.get('摊薄净资产收益率')),
                    'roa': self._parse_float(row.get('总资产报酬率')),
                    'net_profit_margin': self._parse_float(row.get('销售净利率')),
                    'gross_profit_margin': self._parse_float(row.get('销售毛利率')),
                    'core_profit_margin': self._parse_float(row.get('主营业务利润率')),

                    # 运营效率
                    'total_asset_turnover': self._parse_float(row.get('总资产周转率')),
                    'inventory_turnover': self._parse_float(row.get('存货周转率')),
                    'receivable_turnover': self._parse_float(row.get('应收账款周转率')),
                    'inventory_turnover_days': self._parse_float(row.get('存货周转天数')),
                    'receivable_turnover_days': self._parse_float(row.get('应收账款周转天数')),

                    # 偿债能力
                    'debt_asset_ratio': self._parse_float(row.get('资产负债率')),
                    'equity_ratio': self._parse_float(row.get('股东权益比率')),
                    'current_ratio': self._parse_float(row.get('流动比率')),
                    'quick_ratio': self._parse_float(row.get('速动比率')),
                    'cash_ratio': self._parse_float(row.get('现金比率')),

                    # 成长能力
                    'revenue_growth': self._parse_float(row.get('主营业务收入增长率')),
                    'profit_growth': self._parse_float(row.get('净利润增长率')),
                    'asset_growth': self._parse_float(row.get('总资产增长率')),
                    'equity_growth': self._parse_float(row.get('净资产增长率')),
                }

                records.append(record)

            except Exception as e:
                logger.warning(f"解析{stock_code}财务指标行数据失败: {e}")
                continue

        return records

    def _parse_float(self, value) -> Optional[float]:
        """安全解析浮点数"""
        try:
            if pd.isna(value):
                return None
            return float(value)
        except (ValueError, TypeError):
            return None

    def _get_report_period(self, report_date: date) -> str:
        """判断报告期类型"""
        month = report_date.month
        if month == 12:
            return "年报"
        elif month == 6:
            return "半年报"
        elif month == 9:
            return "三季报"
        elif month == 3:
            return "一季报"
        else:
            return "季报"

    def _calculate_balance_ratios(self, record: Dict) -> Dict:
        """计算资产负债表相关比率"""
        total_assets = record.get('total_assets', 0)
        total_liabilities = record.get('total_liabilities', 0)
        total_equity = record.get('total_equity', 0)
        current_assets = record.get('current_assets', 0)
        current_liabilities = record.get('current_liabilities', 0)
        inventory = record.get('inventory', 0)
        cash = record.get('cash_and_equivalents', 0)

        # 资产负债率
        if total_assets and total_assets > 0:
            record['debt_ratio'] = (total_liabilities / total_assets) * 100

        # 流动比率
        if current_liabilities and current_liabilities > 0:
            record['current_ratio'] = current_assets / current_liabilities

        # 速动比率 (流动资产 - 存货) / 流动负债
        if current_liabilities and current_liabilities > 0:
            record['quick_ratio'] = (current_assets - inventory) / current_liabilities

        # ROE (股东权益回报率，需要净利润数据，暂时不计算)

        return record

    def _calculate_income_ratios(self, record: Dict) -> Dict:
        """计算利润表相关比率"""
        total_revenue = record.get('total_revenue', 0)
        net_profit = record.get('net_profit', 0)
        gross_profit = record.get('gross_profit', 0)

        # 毛利率
        if total_revenue and total_revenue > 0:
            record['gross_margin'] = (gross_profit / total_revenue) * 100

        # 净利率
        if total_revenue and total_revenue > 0:
            record['net_margin'] = (net_profit / total_revenue) * 100

        return record

    async def download_fundamental_data(self, stock_code: str) -> Dict[str, int]:
        """
        下载单个股票的所有基本面数据

        Returns:
            {'financial_reports': int, 'indicators': int}
        """
        result = {'financial_reports': 0, 'indicators': 0}

        try:
            # 1. 获取财务报表数据
            balance_df = await self.fetch_balance_sheet(stock_code)
            income_df = await self.fetch_income_statement(stock_code)
            cash_flow_df = await self.fetch_cash_flow(stock_code)

            # 解析并合并
            balance_records = self.parse_balance_sheet(balance_df, stock_code)
            income_records = self.parse_income_statement(income_df, stock_code)
            cash_flow_records = self.parse_cash_flow(cash_flow_df, stock_code)

            # 保存到数据库
            with get_db_session() as session:
                for record in balance_records + income_records + cash_flow_records:
                    # 使用 upsert 逻辑
                    existing = session.query(StockFinancialReport).filter_by(
                        code=record['code'],
                        report_date=record['report_date'],
                        report_type=record['report_type']
                    ).first()

                    if existing:
                        # 更新现有记录
                        for key, value in record.items():
                            if hasattr(existing, key):
                                setattr(existing, key, value)
                    else:
                        # 创建新记录
                        report = StockFinancialReport(**record)
                        session.add(report)

                result['financial_reports'] = len(balance_records) + len(income_records) + len(cash_flow_records)

            # 2. 获取财务指标数据
            indicators_df = await self.fetch_financial_indicators(stock_code)
            indicator_records = self.parse_financial_indicators(indicators_df, stock_code)

            with get_db_session() as session:
                for record in indicator_records:
                    existing = session.query(StockFinancialIndicator).filter_by(
                        code=record['code'],
                        report_date=record['report_date']
                    ).first()

                    if existing:
                        for key, value in record.items():
                            if hasattr(existing, key):
                                setattr(existing, key, value)
                    else:
                        indicator = StockFinancialIndicator(**record)
                        session.add(indicator)

                result['indicators'] = len(indicator_records)

            logger.info(f"✅ {stock_code} 基本面数据下载完成: {result}")

        except Exception as e:
            logger.error(f"下载{stock_code}基本面数据失败: {e}")
            self.failed_stocks.append(stock_code)

        return result


# 全局实例
fundamental_fetcher = FundamentalDataFetcher()
