"""因子数据获取与落库

管理迅投QMT因子看板400+因子，同步到PostgreSQL因子仓库。
关键: 必须先 download_financial_data2 下载, 再 get_financial_data 读取。

因子来源:
- 财务因子: 通过 get_financial_data 从 Pershareindex / Balance / Income / CashFlow / Capital 获取
- 技术/动量/情绪因子: 通过 K 线数据自行计算 (后续扩展)
"""
from datetime import date, datetime
from typing import List, Dict, Any, Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import FactorMeta, FactorValue
from src.data.qmt_client import QMTClient
from src.data.download_engine import DownloadEngine

logger = get_logger(__name__)

FACTOR_CATALOG: Dict[str, List[Dict[str, str]]] = {
    "fundamental": [
        {"name": "total_assets", "qmt_field": "Balance.tot_assets", "desc": "总资产"},
        {"name": "total_liabilities", "qmt_field": "Balance.tot_liab", "desc": "总负债"},
        {"name": "total_equity", "qmt_field": "Balance.total_equity", "desc": "股东权益"},
        {"name": "total_revenue", "qmt_field": "Income.revenue", "desc": "营业总收入"},
        {"name": "operating_profit", "qmt_field": "Income.oper_profit", "desc": "营业利润"},
        {"name": "net_profit", "qmt_field": "Income.net_profit_incl_min_int_inc", "desc": "归母净利润"},
        {"name": "operating_cash_flow", "qmt_field": "CashFlow.net_cash_flows_oper_act", "desc": "经营现金流"},
        {"name": "net_cash_flow", "qmt_field": "CashFlow.net_incr_cash_cash_equ", "desc": "现金净增加额"},
    ],
    "quality": [
        {"name": "roe", "qmt_field": "Pershareindex.du_return_on_equity", "desc": "净资产收益率(加权)"},
        {"name": "roe_diluted", "qmt_field": "Pershareindex.net_roe", "desc": "净资产收益率(摊薄)"},
        {"name": "roa", "qmt_field": "Pershareindex.total_roe", "desc": "总资产收益率(摊薄)"},
        {"name": "gross_margin", "qmt_field": "Pershareindex.gross_profit", "desc": "毛利率"},
        {"name": "net_margin", "qmt_field": "Pershareindex.net_profit", "desc": "净利率"},
        {"name": "actual_tax_rate", "qmt_field": "Pershareindex.actual_tax_rate", "desc": "实际税率"},
    ],
    "per_share": [
        {"name": "eps", "qmt_field": "Pershareindex.s_fa_eps_basic", "desc": "基本每股收益"},
        {"name": "eps_diluted", "qmt_field": "Pershareindex.s_fa_eps_diluted", "desc": "稀释每股收益"},
        {"name": "bps", "qmt_field": "Pershareindex.s_fa_bps", "desc": "每股净资产"},
        {"name": "cfps", "qmt_field": "Pershareindex.s_fa_ocfps", "desc": "每股经营现金流"},
        {"name": "undistributed_ps", "qmt_field": "Pershareindex.s_fa_undistributedps", "desc": "每股未分配利润"},
        {"name": "surplus_capital_ps", "qmt_field": "Pershareindex.s_fa_surpluscapitalps", "desc": "每股资本公积"},
        {"name": "eps_deducted", "qmt_field": "Pershareindex.adjusted_earnings_per_share", "desc": "扣非每股收益"},
    ],
    "growth": [
        {"name": "revenue_growth_yoy", "qmt_field": "Pershareindex.inc_revenue_rate", "desc": "主营收入同比增长"},
        {"name": "profit_growth_yoy", "qmt_field": "Pershareindex.du_profit_rate", "desc": "净利润同比增长"},
        {"name": "parent_profit_growth_yoy", "qmt_field": "Pershareindex.inc_net_profit_rate", "desc": "归母净利润同比增长"},
        {"name": "deducted_profit_growth_yoy", "qmt_field": "Pershareindex.adjusted_net_profit_rate", "desc": "扣非净利润同比增长"},
        {"name": "revenue_growth_qoq", "qmt_field": "Pershareindex.inc_total_revenue_annual", "desc": "营收滚动环比增长"},
        {"name": "profit_growth_qoq", "qmt_field": "Pershareindex.inc_net_profit_to_shareholders_annual", "desc": "归母净利润滚动环比"},
    ],
    "valuation": [
        {"name": "sales_gross_profit", "qmt_field": "Pershareindex.sales_gross_profit", "desc": "销售毛利率"},
        {"name": "pre_pay_revenue_ratio", "qmt_field": "Pershareindex.pre_pay_operate_income", "desc": "预收款/营收"},
        {"name": "sales_cash_flow_ratio", "qmt_field": "Pershareindex.sales_cash_flow", "desc": "销售现金流/营收"},
        {"name": "gear_ratio", "qmt_field": "Pershareindex.gear_ratio", "desc": "资产负债率"},
        {"name": "inventory_turnover", "qmt_field": "Pershareindex.inventory_turnover", "desc": "存货周转率"},
    ],
    "risk_style": [
        {"name": "total_capital", "qmt_field": "Capital.total_capital", "desc": "总股本"},
        {"name": "circulating_capital", "qmt_field": "Capital.circulating_capital", "desc": "流通A股"},
        {"name": "restrict_capital", "qmt_field": "Capital.restrict_circulating_capital", "desc": "限售流通股"},
    ],
    "sentiment": [],
    "technical": [],
    "momentum": [],
}


class FactorDataManager:
    """因子数据管理器"""

    def __init__(self, client: Optional[QMTClient] = None):
        self.client = client or QMTClient()
        self.engine = DownloadEngine(self.client)

    def init_factor_meta(self) -> int:
        """初始化因子元信息表"""
        count = 0
        with get_session() as session:
            for category, factors in FACTOR_CATALOG.items():
                for f in factors:
                    stmt = insert(FactorMeta).values(
                        factor_name=f["name"],
                        category=category,
                        description=f["desc"],
                        data_source="qmt",
                        qmt_field=f.get("qmt_field", ""),
                    ).on_conflict_do_nothing(index_elements=["factor_name"])
                    session.execute(stmt)
                    count += 1
        logger.info(f"已初始化 {count} 个因子元信息")
        return count

    def get_factor_meta(self) -> Dict[str, int]:
        """获取因子名到ID的映射"""
        with get_session() as session:
            rows = session.query(FactorMeta).all()
            return {r.factor_name: r.factor_id for r in rows}

    def sync_factors(
        self,
        stock_list: List[str],
        start_time: str = "",
        end_time: str = "",
    ) -> int:
        """从QMT同步因子数据到数据库

        流程: download_financial_data2 → get_financial_data → 解析入库
        """
        meta_map = self.get_factor_meta()
        if not meta_map:
            self.init_factor_meta()
            meta_map = self.get_factor_meta()

        table_to_fields: Dict[str, List[Dict[str, str]]] = {}
        for category, factors in FACTOR_CATALOG.items():
            for f in factors:
                qmt_field = f.get("qmt_field", "")
                if not qmt_field or "." not in qmt_field:
                    continue
                table_name = qmt_field.split(".")[0]
                table_to_fields.setdefault(table_name, []).append(f)

        if not table_to_fields:
            logger.warning("无QMT因子字段可同步")
            return 0

        table_list = list(table_to_fields.keys())

        self.engine.download_financial(
            stock_list,
            table_list=table_list,
            start_time=start_time,
            end_time=end_time,
        )

        raw_data = self.client.get_financial_data(
            stock_list=stock_list,
            table_list=table_list,
            start_time=start_time,
            end_time=end_time,
            report_type="announce_time",
        )

        total = 0
        with get_session() as session:
            for table_name, table_df in raw_data.items():
                if table_df is None or not isinstance(table_df, pd.DataFrame) or table_df.empty:
                    continue
                factor_defs = table_to_fields.get(table_name, [])
                for f_def in factor_defs:
                    qmt_field = f_def["qmt_field"]
                    field_col = qmt_field.split(".", 1)[1] if "." in qmt_field else qmt_field
                    factor_name = f_def["name"]
                    if factor_name not in meta_map:
                        continue
                    factor_id = meta_map[factor_name]

                    if field_col not in table_df.columns:
                        logger.debug(f"字段 {field_col} 不在 {table_name} 的列中, 跳过")
                        continue

                    for idx, val in table_df[field_col].items():
                        if pd.isna(val):
                            continue
                        try:
                            trade_date = pd.Timestamp(idx).date()
                        except Exception:
                            continue

                        code = str(idx).split(".")[0] if "." in str(idx) else str(idx)

                        stmt = insert(FactorValue).values(
                            trade_date=trade_date,
                            code=code,
                            factor_id=factor_id,
                            value=float(val),
                        ).on_conflict_do_update(
                            constraint="uq_factor_value",
                            set_={"value": float(val)},
                        )
                        session.execute(stmt)
                        total += 1
        logger.info(f"已同步 {total} 条因子数据")
        return total

    def get_factor_values(
        self,
        factor_names: List[str],
        stock_list: List[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """查询因子值, 返回透视表 (index=date+code, columns=factor_name)"""
        meta_map = self.get_factor_meta()
        factor_ids = [meta_map[n] for n in factor_names if n in meta_map]

        with get_session() as session:
            sql = text("""
                SELECT fv.trade_date, fv.code, fm.factor_name, fv.value
                FROM factor_values fv
                JOIN factor_meta fm ON fv.factor_id = fm.factor_id
                WHERE fv.factor_id = ANY(:fids)
                  AND fv.code = ANY(:codes)
                  AND fv.trade_date BETWEEN :start AND :end
                ORDER BY fv.trade_date, fv.code
            """)
            result = session.execute(sql, {
                "fids": factor_ids,
                "codes": stock_list,
                "start": start_date,
                "end": end_date,
            })
            rows = result.fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["trade_date", "code", "factor_name", "value"])
        pivot = df.pivot_table(
            index=["trade_date", "code"],
            columns="factor_name",
            values="value",
        )
        return pivot
