# Fin-R1 数据清单与完整性报告

## 📊 已实现的数据表

| 表名 | 中文名 | 必要性 | 数据源 | 状态 |
|------|--------|--------|--------|------|
| `stocks` | 股票基础信息 | ✅ 必须 | `akshare.stock_info_a_code_name` | ✅ 已实现 |
| `stock_daily` | 日线历史数据 | ✅ 必须 | `akshare.stock_zh_a_hist` | ✅ 已实现 |
| `stock_realtime` | 实时行情数据 | 可选 | `akshare.stock_zh_a_spot_em` | ✅ 已实现 |
| `market_index` | 大盘指数数据 | 可选 | `akshare.index_zh_a_hist` | ✅ 已实现 |
| `sector_data` | 板块行业数据 | 可选 | `akshare.stock_sector_fund_flow_rank` | ✅ 已实现 |
| `stock_financial_report` | 财务报表数据 | 可选 | `akshare.stock_balance_sheet_by_report_em` | ✅ 已实现 |
| `stock_financial_indicator` | 财务分析指标 | 可选 | `akshare.stock_financial_analysis_indicator` | ✅ 已实现 |
| `data_sync_log` | 数据同步日志 | ✅ 必须 | - | ✅ 已实现 |

## 📈 已实现的数据字段

### 1. stocks (股票基础信息)
```
- code: 股票代码 (PK)
- name: 股票名称
- exchange: 交易所 (SH/SZ/BJ)
- industry: 所属行业
- sector: 所属板块
- list_date: 上市日期
- pe_ttm: 市盈率TTM
- pb: 市净率
- roe: 净资产收益率
- market_cap: 总市值(亿)
- updated_at: 更新时间
```

### 2. stock_daily (日线历史数据)
```
- id: 自增ID
- code: 股票代码
- trade_date: 交易日期
- open: 开盘价
- high: 最高价
- low: 最低价
- close: 收盘价
- pre_close: 昨收价
- volume: 成交量(股)
- amount: 成交额(元)
- change: 涨跌额
- change_pct: 涨跌幅%
- turnover_rate: 换手率
- amplitude: 振幅% ← 新增
```

### 3. stock_realtime (实时行情数据)
```
- id: 自增ID
- code: 股票代码
- timestamp: 数据时间戳
- price: 当前价格
- change: 涨跌额
- change_pct: 涨跌幅%
- volume: 累计成交量
- amount: 累计成交额
- high: 当日最高
- low: 当日最低
- open: 当日开盘
- pre_close: 昨收价
- turnover_rate: 换手率 ← 新增
- amplitude: 振幅 ← 新增
- rise_speed: 涨速 ← 新增
- change_5min: 5分钟涨跌 ← 新增
- change_60d: 60日涨跌幅 ← 新增
- change_ytd: 年初至今涨跌幅 ← 新增
- market_cap: 总市值 ← 新增
- float_market_cap: 流通市值 ← 新增
- pe_dynamic: 市盈率(动态) ← 新增
- pb: 市净率 ← 新增
```

### 4. market_index (大盘指数数据)
```
- id: 自增ID
- index_code: 指数代码
- index_name: 指数名称
- trade_date: 交易日期
- open: 开盘
- high: 最高
- low: 最低
- close: 收盘
- change: 涨跌额
- change_pct: 涨跌幅%
- volume: 成交量
- amount: 成交额
```

### 5. sector_data (板块行业数据)
```
- id: 自增ID
- sector_name: 板块名称
- trade_date: 交易日期
- change_pct: 涨跌幅%
- net_inflow: 资金净流入(亿)
- leading_stock: 领涨股
```

### 6. stock_financial_report (财务报表数据) ← 新增表
```
资产负债表:
- total_assets: 总资产
- total_liabilities: 总负债
- total_equity: 股东权益
- current_assets: 流动资产
- current_liabilities: 流动负债
- inventory: 存货
- accounts_receivable: 应收账款
- cash_and_equivalents: 货币资金
- fixed_assets: 固定资产

利润表:
- total_revenue: 营业收入
- operating_profit: 营业利润
- net_profit: 净利润
- gross_profit: 毛利润
- operating_cost: 营业成本
- selling_expenses: 销售费用
- admin_expenses: 管理费用
- financial_expenses: 财务费用
- rd_expenses: 研发费用

现金流量表:
- net_cash_flow: 净现金流
- operating_cash_flow: 经营活动现金流
- investing_cash_flow: 投资活动现金流
- financing_cash_flow: 筹资活动现金流

财务比率(计算得出):
- gross_margin: 毛利率%
- net_margin: 净利率%
- roe: 净资产收益率%
- roa: 总资产收益率%
- debt_ratio: 资产负债率%
- current_ratio: 流动比率
- quick_ratio: 速动比率
```

### 7. stock_financial_indicator (财务分析指标) ← 新增表
```
每股指标:
- eps_basic: 基本每股收益
- eps_diluted: 稀释每股收益
- bps: 每股净资产
- dps: 每股股息
- cfps: 每股现金流

盈利能力:
- roe_weighted: 加权净资产收益率
- roe_diluted: 摊薄净资产收益率
- roa: 总资产报酬率
- net_profit_margin: 销售净利率
- gross_profit_margin: 销售毛利率
- core_profit_margin: 主营业务利润率

运营效率:
- total_asset_turnover: 总资产周转率
- inventory_turnover: 存货周转率
- receivable_turnover: 应收账款周转率
- inventory_turnover_days: 存货周转天数
- receivable_turnover_days: 应收账款周转天数

偿债能力:
- debt_asset_ratio: 资产负债率
- equity_ratio: 股东权益比率
- current_ratio: 流动比率
- quick_ratio: 速动比率
- cash_ratio: 现金比率
- interest_coverage: 利息保障倍数

成长能力:
- revenue_growth: 营业收入增长率
- profit_growth: 净利润增长率
- asset_growth: 总资产增长率
- equity_growth: 净资产增长率
```

## 🎯 推荐但未实现的数据源

| 数据源 | 优先级 | 用途 | 实现难度 |
|--------|--------|------|----------|
| **个股新闻** | 🟡 中 | 舆情分析、事件驱动 | 低 |
| **龙虎榜数据** | 🟡 中 | 追踪游资动向 | 低 |
| **资金流向** | 🔴 高 | 判断主力意图 | 低 |
| **机构持股** | 🟡 中 | 跟踪机构动向 | 中 |
| **大宗交易** | 🟢 低 | 机构交易行为 | 低 |
| **主要财务指标** | 🔴 高 | 基本面快速筛选 | 低 |
| **业绩预告** | 🟡 中 | 提前预知业绩 | 中 |
| **股权质押** | 🟢 低 | 风险预警 | 低 |
| **股票回购** | 🟢 低 | 价值判断 | 低 |
| **分红送股** | 🟡 中 | 股息策略 | 低 |

## 📋 数据完整性检查命令

```bash
# 1. 检查所有数据表状态
cd /home/data/fin-r1-live/data-hub
python data_inventory.py --check

# 2. 查看缺失的数据
python data_inventory.py --missing

# 3. 按股票代码排序查看下载状态
python data_inventory.py --sort code

# 4. 按完整度排序查看
python data_inventory.py --sort completeness

# 5. 导出CSV格式的股票列表
python data_inventory.py --export csv

# 6. 导出JSON格式
python data_inventory.py --export json
```

## 📊 示例输出

```
============================================================
股票下载状态（按 code 排序）
============================================================
代码      名称           日线      财务      完整度      状态
--------------------------------------------------------------------------------
000001    平安银行       245       12       98.00%    ✅
000002    万科A          245       12       98.00%    ✅
000063    中兴通讯       245       12       98.00%    ✅
000100    TCL科技        245       12       98.00%    ✅
000333    美的集团       245       12       98.00%    ✅
000568    泸州老窖       245       12       98.00%    ✅
000651    格力电器       245       12       98.00%    ✅
000725    京东方A        245       12       98.00%    ✅
000858    五粮液         245       12       98.00%    ✅
002001    新和成         230       12       92.00%    ⚠️
002007    华兰生物       220       10       88.00%    ⚠️
002024    苏宁易购       180       8        72.00%    ❌
--------------------------------------------------------------------------------
显示 50/5234 只股票
完整报告请运行: python data_inventory.py --check
```

## 🔧 数据同步顺序建议

```
第一步: 基础数据
├── stocks (股票列表)
├── stock_daily (日线数据)
└── market_index (大盘指数)

第二步: 实时数据
├── stock_realtime (实时行情)
└── sector_data (板块数据)

第三步: 基本面数据
├── stock_financial_report (财务报表)
└── stock_financial_indicator (财务指标)

第四步: 扩展数据 (可选)
├── 资金流向
├── 龙虎榜
├── 个股新闻
└── 机构持股
```

## 📈 数据量估算

| 数据类型 | 记录数/股票 | 总记录数(5000只) | 存储空间 |
|----------|------------|-----------------|----------|
| stocks | 1 | 5,000 | ~2 MB |
| stock_daily (1年) | 250 | 1,250,000 | ~500 MB |
| stock_realtime | 1 | 5,000 | ~1 MB |
| market_index (1年) | 250 | 1,250 | ~1 MB |
| sector_data | 100 | 100,000 | ~50 MB |
| financial_report (8期) | 8 | 40,000 | ~20 MB |
| financial_indicator (8期) | 8 | 40,000 | ~20 MB |
| **总计** | - | **~1,400,000** | **~600 MB** |

## ✅ 数据完整性检查清单

- [x] 股票基础信息 (stocks)
- [x] 日线历史数据 (stock_daily)
- [x] 实时行情数据 (stock_realtime)
- [x] 大盘指数数据 (market_index)
- [x] 板块行业数据 (sector_data)
- [x] 财务报表数据 (stock_financial_report)
- [x] 财务分析指标 (stock_financial_indicator)
- [ ] 资金流向数据 (待实现)
- [ ] 龙虎榜数据 (待实现)
- [ ] 个股新闻数据 (待实现)
- [ ] 机构持股数据 (待实现)
- [ ] 大宗交易数据 (待实现)
