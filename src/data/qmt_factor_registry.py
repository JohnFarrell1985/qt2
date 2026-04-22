"""迅投 QMT get_financial_data 全量财务/股东表字段 + Qlib 价量(Alpha158) 元数据注册

字段名来源: 迅投 `dict.thinktrader` 财务数据字段列表 (与 xtdata 表列名一致)
说明:
- Qlib 官方 **Alpha158** 为**价量因子**, 无单独「财报一维表」; 此处将 Alpha158 名称作为
  ``data_source=calculated`` 的元数据, 与 QMT 财报表区分.
- 十大股东/流通股东中仅数值列参与 ``sync_factors`` 落地; 文本列可登记元数据, 值同步时会跳过.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterator, List, Tuple

from src.data.factor_i18n import describe_qmt_field, describe_qlib_alpha158_column, infer_factor_meta

# type: (table, field) -> 中文描述 (由 ``factor_i18n`` + ``qmt_field_labels.zh.json`` 生成)
# 表名使用 get_financial_data 的表名: Balance, Income, CashFlow, Pershareindex, Capital, Holdernum, Top10holder, Top10flowholder

# --- Balance: 资产负债表 (字段与迅投文档一致) ---
BALANCE: Tuple[str, ...] = (
    "m_anntime", "m_timetag", "internal_shoule_recv", "fixed_capital_clearance",
    "should_pay_money", "settlement_payment", "receivable_premium",
    "accounts_receivable_reinsurance", "reinsurance_contract_reserve",
    "dividends_payable", "tax_rebate_for_export", "subsidies_receivable",
    "deposit_receivable", "apportioned_cost", "profit_and_current_assets_with_deal",
    "current_assets_one_year", "long_term_receivables", "other_long_term_investments",
    "original_value_of_fixed_assets", "net_value_of_fixed_assets",
    "depreciation_reserves_of_fixed_assets", "productive_biological_assets",
    "public_welfare_biological_assets", "oil_and_gas_assets", "development_expenditure",
    "right_of_split_share_distribution", "other_non_mobile_assets",
    "handling_fee_and_commission", "other_payables", "margin_payable",
    "internal_accounts_payable", "advance_cost", "insurance_contract_reserve",
    "broker_buying_and_selling_securities", "acting_underwriting_securities",
    "international_ticket_settlement", "domestic_ticket_settlement", "deferred_income",
    "short_term_bonds_payable", "long_term_deferred_income", "undetermined_investment_losses",
    "quasi_distribution_of_cash_dividends", "provisions_not", "cust_bank_dep", "provisions",
    "less_tsy_stk", "cash_equivalents", "loans_to_oth_banks", "tradable_fin_assets",
    "derivative_fin_assets", "bill_receivable", "account_receivable", "advance_payment",
    "int_rcv", "other_receivable", "red_monetary_cap_for_sale", "agency_bus_assets",
    "inventories", "other_current_assets", "total_current_assets", "loans_and_adv_granted",
    "fin_assets_avail_for_sale", "held_to_mty_invest", "long_term_eqy_invest",
    "invest_real_estate", "accumulated_depreciation", "fix_assets", "constru_in_process",
    "construction_materials", "long_term_liabilities", "intang_assets", "goodwill",
    "long_deferred_expense", "deferred_tax_assets", "total_non_current_assets", "tot_assets",
    "shortterm_loan", "borrow_central_bank", "loans_oth_banks", "tradable_fin_liab",
    "derivative_fin_liab", "notes_payable", "accounts_payable", "advance_peceipts",
    "fund_sales_fin_assets_rp", "empl_ben_payable", "taxes_surcharges_payable", "int_payable",
    "dividend_payable", "other_payable", "non_current_liability_in_one_year",
    "other_current_liability", "total_current_liability", "long_term_loans", "bonds_payable",
    "longterm_account_payable", "grants_received", "deferred_tax_liab",
    "other_non_current_liabilities", "non_current_liabilities", "tot_liab", "cap_stk", "cap_rsrv",
    "specific_reserves", "surplus_rsrv", "prov_nom_risks", "undistributed_profit",
    "cnvd_diff_foreign_curr_stat", "tot_shrhldr_eqy_excl_min_int", "minority_int",
    "total_equity", "tot_liab_shrhdr_eqy",
)

# --- Income: 利润表 ---
INCOME: Tuple[str, ...] = (
    "m_anntime", "m_timetag", "revenue_inc", "earned_premium", "real_estate_sales_income",
    "total_operating_cost", "real_estate_sales_cost", "research_expenses", "surrender_value",
    "net_payments", "net_withdrawal_ins_con_res", "policy_dividend_expenses", "reinsurance_cost",
    "change_income_fair_value", "futures_loss", "trust_income", "subsidize_revenue",
    "other_business_profits", "net_profit_excl_merged_int_inc", "int_inc", "handling_chrg_comm_inc",
    "less_handling_chrg_comm_exp", "other_bus_cost", "plus_net_gain_fx_trans",
    "il_net_loss_disp_noncur_asset", "inc_tax", "unconfirmed_invest_loss",
    "net_profit_excl_min_int_inc", "less_int_exp", "other_bus_inc", "revenue", "total_expense",
    "less_taxes_surcharges_ops", "sale_expense", "less_gerl_admin_exp", "financial_expense",
    "less_impair_loss_assets", "plus_net_invest_inc", "incl_inc_invest_assoc_jv_entp",
    "oper_profit", "plus_non_oper_rev", "less_non_oper_exp", "tot_profit", "net_profit_incl_min_int_inc",
    "net_profit_incl_min_int_inc_after", "minority_int_inc", "s_fa_eps_basic", "s_fa_eps_diluted",
    "total_income", "total_income_minority", "other_compreh_inc",
)

# --- CashFlow: 现金流量表 (去重 net_incr_fund_borr_ofi 重复行) ---
CASHFLOW: Tuple[str, ...] = (
    "m_anntime", "m_timetag", "cash_received_ori_ins_contract_pre", "net_cash_received_rei_ope",
    "net_increase_insured_funds", "cash_for_interest", "net_increase_in_repurchase_funds",
    "cash_for_payment_original_insurance", "cash_payment_policy_dividends", "disposal_other_business_units",
    "cash_received_from_pledges", "cash_paid_for_investments", "net_increase_in_pledged_loans",
    "cash_paid_by_subsidiaries", "increase_in_cash_paid", "cass_received_sub_abs",
    "cass_received_sub_investments", "minority_shareholder_profit_loss", "unrecognized_investment_losses",
    "ncrease_deferred_income", "projected_liability", "increase_operational_payables",
    "reduction_outstanding_amounts_less", "reduction_outstanding_amounts_more",
    "goods_sale_and_service_render_cash", "net_incr_dep_cob", "net_incr_loans_central_bank",
    "net_incr_fund_borr_ofi", "tax_levy_refund", "cash_paid_invest", "other_cash_recp_ral_oper_act",
    "stot_cash_inflows_oper_act", "goods_and_services_cash_paid", "net_incr_clients_loan_adv",
    "net_incr_dep_cbob", "handling_chrg_paid", "cash_pay_beh_empl", "pay_all_typ_tax",
    "other_cash_pay_ral_oper_act", "stot_cash_outflows_oper_act", "net_cash_flows_oper_act",
    "cash_recp_disp_withdrwl_invest", "cash_recp_return_invest", "net_cash_recp_disp_fiolta",
    "other_cash_recp_ral_inv_act", "stot_cash_inflows_inv_act", "cash_pay_acq_const_fiolta",
    "stot_cash_outflows_inv_act", "net_cash_flows_inv_act", "cash_recp_cap_contrib", "cash_recp_borrow",
    "proc_issue_bonds", "other_cash_recp_ral_fnc_act", "stot_cash_inflows_fnc_act", "cash_prepay_amt_borr",
    "cash_pay_dist_dpcp_int_exp", "other_cash_pay_ral_fnc_act", "stot_cash_outflows_fnc_act",
    "net_cash_flows_fnc_act", "eff_fx_flu_cash", "net_incr_cash_cash_equ", "cash_cash_equ_beg_period",
    "cash_cash_equ_end_period", "net_profit", "plus_prov_depr_assets", "depr_fa_coga_dpba",
    "amort_intang_assets", "amort_lt_deferred_exp", "decr_deferred_exp", "incr_acc_exp",
    "loss_disp_fiolta", "loss_scr_fa", "loss_fv_chg", "fin_exp", "invest_loss",
    "decr_deferred_inc_tax_assets", "incr_deferred_inc_tax_liab", "decr_inventories", "decr_oper_payable",
    "others", "im_net_cash_flows_oper_act", "conv_debt_into_cap", "conv_corp_bonds_due_within_1y",
    "fa_fnc_leases", "end_bal_cash", "less_beg_bal_cash", "plus_end_bal_cash_equ", "less_beg_bal_cash_equ",
    "im_net_incr_cash_cash_equ",
)

# --- Pershareindex: 每股/主要指标 (迅投表名 Pershareindex) ---
PERSHARE: Tuple[str, ...] = (
    "m_anntime", "m_timetag", "s_fa_ocfps", "s_fa_bps", "s_fa_eps_basic", "s_fa_eps_diluted",
    "s_fa_undistributedps", "s_fa_surpluscapitalps", "adjusted_earnings_per_share", "du_return_on_equity",
    "sales_gross_profit", "inc_revenue_rate", "du_profit_rate", "inc_net_profit_rate", "adjusted_net_profit_rate",
    "inc_total_revenue_annual", "inc_net_profit_to_shareholders_annual", "adjusted_profit_to_profit_annual",
    "equity_roe", "net_roe", "total_roe", "gross_profit", "net_profit", "actual_tax_rate",
    "pre_pay_operate_income", "sales_cash_flow", "gear_ratio", "inventory_turnover",
)

# --- Capital: 股本 ---
CAPITAL: Tuple[str, ...] = ("m_timetag", "m_anntime", "total_capital", "circulating_capital", "restrict_circulating_capital")

# --- Holdernum: 股东户数 (数值) ---
HOLDNUM: Tuple[str, ...] = (
    "declareDate", "endDate", "shareholder", "shareholderA", "shareholderB", "shareholderH",
    "shareholderFloat", "shareholderOther",
)

# --- Top10: 仅数值/可解析列 (名称类不入库因子值) ---
TOP10_NUMERIC: Tuple[str, ...] = ("quantity", "ratio", "rank")

TABLE_CATEGORY: Dict[str, str] = {
    "Balance": "fundamental",
    "Income": "fundamental",
    "CashFlow": "fundamental",
    "Pershareindex": "qmt_pershareindex",
    "Capital": "risk_style",
    "Holdernum": "qmt_shareholder",
    "Top10holder": "qmt_top10",
    "Top10flowholder": "qmt_top10",
}


def _mk_name(table: str, field: str) -> str:
    """``factor_name`` 稳定短名, 与旧版手填名并存时用 qmt_field 去重."""
    t = table.lower().replace("index", "idx")
    return f"qmt_{t}_{field}"[:100]


def iter_qmt_table_fields() -> Iterator[Dict[str, Any]]:
    specs: List[Tuple[str, Tuple[str, ...]]] = [
        ("Balance", BALANCE), ("Income", INCOME), ("CashFlow", CASHFLOW),
        ("Pershareindex", PERSHARE), ("Capital", CAPITAL), ("Holdernum", HOLDNUM),
    ]
    for table, fields in specs:
        cat = TABLE_CATEGORY[table]
        for field in fields:
            qf = f"{table}.{field}"
            fk, uf, sh = infer_factor_meta(qf, "qmt")
            yield {
                "name": _mk_name(table, field),
                "qmt_field": qf,
                "desc": describe_qmt_field(table, field),
                "category": cat,
                "data_source": "qmt",
                "factor_kind": fk,
                "update_freq": uf,
                "storage_hint": sh,
            }
    for table in ("Top10holder", "Top10flowholder"):
        cat = TABLE_CATEGORY[table]
        for field in TOP10_NUMERIC:
            qf = f"{table}.{field}"
            fk, uf, sh = infer_factor_meta(qf, "qmt")
            yield {
                "name": _mk_name(table, field),
                "qmt_field": qf,
                "desc": describe_qmt_field(table, field),
                "category": cat,
                "data_source": "qmt",
                "factor_kind": fk,
                "update_freq": uf,
                "storage_hint": sh,
            }


def iter_qlib_alpha158_meta(windows: List[int] | None = None) -> Iterator[Dict[str, Any]]:
    """Qlib 风格名: 与项目 ``Alpha158Calculator`` 输出列名一致 (价量, 非财报)."""
    from src.factor.alpha158 import Alpha158Calculator

    calc = Alpha158Calculator(windows=windows)
    for n in calc.factor_names:
        yield {
            "name": f"qlib_a158_{n}"[:100],
            "qmt_field": "",
            "desc": describe_qlib_alpha158_column(n),
            "category": "qlib_alpha158",
            "data_source": "calculated",
            "factor_kind": "price_volume",
            "update_freq": "daily",
            "storage_hint": "not_stored",
        }


def merge_with_legacy(
    legacy: Dict[str, List[Dict[str, str]]],
) -> Dict[str, List[Dict[str, Any]]]:
    """legacy 手填项优先, 按 ``Table.field`` 去重后追加迅投全量 + Qlib Alpha158 元数据."""
    seen_qmt: set[str] = set()
    seen_names: set[str] = set()
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for cat, items in legacy.items():
        if not items:
            out[cat] = []
            continue
        for it in items:
            name = it["name"]
            seen_names.add(name)
            qf = (it.get("qmt_field") or "").strip()
            if qf and "." in qf:
                seen_qmt.add(qf)
            ds = it.get("data_source", "qmt")
            fk, uf, sh = infer_factor_meta(qf, ds)
            out[cat].append(
                {
                    "name": name,
                    "qmt_field": qf,
                    "desc": it.get("desc", ""),
                    "category": cat,
                    "data_source": ds,
                    "factor_kind": it.get("factor_kind") or fk,
                    "update_freq": it.get("update_freq") or uf,
                    "storage_hint": it.get("storage_hint") or sh,
                }
            )

    for e in iter_qmt_table_fields():
        qf = (e.get("qmt_field") or "").strip()
        if not qf or qf in seen_qmt:
            continue
        seen_qmt.add(qf)
        seen_names.add(e["name"])
        out[e["category"]].append(
            {
                "name": e["name"],
                "qmt_field": qf,
                "desc": e.get("desc", ""),
                "category": e["category"],
                "data_source": e.get("data_source", "qmt"),
                "factor_kind": e.get("factor_kind", "unknown"),
                "update_freq": e.get("update_freq", "unknown"),
                "storage_hint": e.get("storage_hint", "factor_values"),
            }
        )

    for e in iter_qlib_alpha158_meta():
        if e["name"] in seen_names:
            continue
        seen_names.add(e["name"])
        out["qlib_alpha158"].append(
            {
                "name": e["name"],
                "qmt_field": "",
                "desc": e.get("desc", ""),
                "category": "qlib_alpha158",
                "data_source": "calculated",
                "factor_kind": e.get("factor_kind", "price_volume"),
                "update_freq": e.get("update_freq", "daily"),
                "storage_hint": e.get("storage_hint", "not_stored"),
            }
        )

    return dict(out)
