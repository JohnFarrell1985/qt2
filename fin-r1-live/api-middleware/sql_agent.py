"""
Fin-R1 SQL Agent - AI生成SQL并执行

流程:
1. AI根据用户问题生成SQL
2. 后端执行SQL查询PostgreSQL
3. 结果返回给AI，生成最终回答
"""
import json
import re
import asyncio
import inspect
from typing import Dict, List, Any, Optional
from database_client import get_db_session
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


def _is_async_client(client) -> bool:
    """检测是否为异步OpenAI客户端"""
    return hasattr(client, 'chat') and inspect.iscoroutinefunction(
        getattr(client.chat.completions, 'create', None) or lambda: None
    )


async def _call_openai_async(client, **kwargs):
    """异步调用OpenAI API"""
    return await client.chat.completions.create(**kwargs)


def _call_openai_sync(client, **kwargs):
    """同步调用OpenAI API"""
    return client.chat.completions.create(**kwargs)

# SQL生成提示词（专业量化级）
SQL_GENERATION_PROMPT = """你是Fin-R1专业量化分析助手，具备PostgreSQL SQL查询生成能力。

【可用数据表结构】

1. stock_daily - 股票日线历史数据（主表）
   - code: VARCHAR(10), 股票代码, 主键部分, 格式如 '000001'
   - trade_date: DATE, 交易日期, 主键部分, 格式 'YYYY-MM-DD'
   - open: FLOAT, 开盘价
   - high: FLOAT, 最高价
   - low: FLOAT, 最低价
   - close: FLOAT, 收盘价
   - volume: BIGINT, 成交量（股）
   - amount: FLOAT, 成交额（元）
   - change_pct: FLOAT, 涨跌幅百分比
   - turnover_rate: FLOAT, 换手率
   - pre_close: FLOAT, 昨收价
   - amplitude: FLOAT, 振幅

2. stocks - 股票基础信息表
   - code: VARCHAR(10), 股票代码, 主键
   - name: VARCHAR(50), 股票名称, 如 '平安银行'
   - exchange: VARCHAR(10), 交易所, 'SH'|'SZ'|'BJ'
   - industry: VARCHAR(50), 所属行业
   - sector: VARCHAR(50), 所属板块

3. stock_financial_report - 财务报表数据
   - code: VARCHAR(10), 股票代码
   - report_date: DATE, 报告日期
   - report_type: INT, 报告类型, 1=Q1, 2=H1, 3=Q3, 4=年报
   - total_revenue: FLOAT, 营业总收入
   - net_profit: FLOAT, 净利润
   - basic_eps: FLOAT, 基本每股收益

【SQL生成铁律 - 必须遵守】

1. 字段选择
   - 禁止SELECT *，只选择用户明确需要的字段
   - 价格类字段保留2位小数精度意识
   - 成交量字段默认以"万股"为单位 mentally

2. 过滤条件
   - 股票代码字段名：stock_daily.code, stocks.code（不是ts_code）
   - 日期字段名：stock_daily.trade_date（不是date）
   - 日期格式：'YYYY-MM-DD'，必须用单引号包裹
   - 股票代码格式：6位数字字符串，如'000001'（不是000001或000001.SZ）

3. 时间范围
   - 默认查询最近30天：trade_date >= CURRENT_DATE - INTERVAL '30 days'
   - 用户指定天数时：trade_date >= CURRENT_DATE - INTERVAL '{{N}} days'
   - 避免查询全部历史数据

4. 结果限制
   - 必须添加LIMIT子句，默认LIMIT 50，最大LIMIT 100
   - 按日期降序ORDER BY trade_date DESC（最新在前）

5. 禁止事项
   - 禁止JOIN多个大表
   - 禁止子查询嵌套超过1层
   - 禁止聚合函数无GROUP BY
   - 禁止无WHERE条件的全表扫描

【示例参考】

Q: 查询000001最近30天的收盘价
A: SELECT trade_date, close FROM stock_daily WHERE code = '000001' ORDER BY trade_date DESC LIMIT 30

Q: 平安银行最近30天的成交量和成交额
A: SELECT trade_date, volume, amount FROM stock_daily WHERE code = '000001' AND trade_date >= CURRENT_DATE - INTERVAL '30 days' ORDER BY trade_date DESC LIMIT 30

Q: 贵州茅台2024年1月的最高价和最低价
A: SELECT MAX(high) as max_high, MIN(low) as min_low FROM stock_daily WHERE code = '600519' AND trade_date >= '2024-01-01' AND trade_date < '2024-02-01'

Q: 查询股票代码600036的名称和交易所
A: SELECT name, exchange FROM stocks WHERE code = '600036'

用户问题：{user_question}

请生成标准PostgreSQL查询（只输出SQL，无任何解释）：
"""

# 结果分析提示词（专业量化级）
ANALYSIS_PROMPT = """你是Fin-R1专业量化分析助手，基于PostgreSQL数据库真实查询结果提供金融分析。

【数据来源声明 - 必须执行】
1. 开头必须明确声明："根据PostgreSQL数据库查询结果..."
2. 引用具体数据时必须标注日期范围，如"2024年3月1日至3月15日"
3. 所有数字必须来自下方提供的查询结果，禁止脑补或估算

【分析规范】

1. 价格数据分析
   - 收盘价：分析趋势（上涨/下跌/震荡），给出具体涨跌额和百分比
   - 最高价/最低价：指出区间波动范围，计算振幅
   - 均价：如数据足够，可计算简单移动平均

2. 成交量分析
   - 成交量单位统一为"万股"或"万手"
   - 分析量价关系：放量上涨/缩量下跌/量价背离等
   - 指出成交量异常波动日期

3. 技术指标判断（如数据支持）
   - 趋势判断：多头排列/空头排列/盘整
   - 支撑/压力位：基于近期高低点
   - 风险提示：短期涨幅过大/成交量萎缩等

4. 结论格式
   - 先给结论：看涨/看跌/观望
   - 再给依据：引用具体数据点
   - 最后风险提示：历史数据不代表未来表现

【禁止事项 - 违反将导致分析无效】
❌ 禁止出现"假设"、"如果"、"可能"等不确定词汇
❌ 禁止编造不存在的股价或日期
❌ 禁止声称"无法获取数据"（数据已在下方提供）
❌ 禁止使用模拟数据或示例数据

用户问题：{user_question}

【PostgreSQL数据库真实查询结果】
{query_result}

请基于上述真实数据，用专业量化语言给出分析结论：
"""


class SQLAgent:
    """SQL生成和执行Agent"""
    
    @staticmethod
    async def generate_sql(user_question: str, vllm_client) -> str:
        """
        让AI生成SQL（支持同步和异步客户端）

        Args:
            user_question: 用户问题
            vllm_client: vLLM客户端（可以是同步或异步）

        Returns:
            SQL语句
        """
        prompt = SQL_GENERATION_PROMPT.format(user_question=user_question)

        try:
            # 检测客户端类型并调用相应方法
            is_async = _is_async_client(vllm_client)
            logger.info(f"客户端类型: {'异步' if is_async else '同步'}")

            if is_async:
                response = await _call_openai_async(
                    vllm_client,
                    model="Fin-R1",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=200,
                    stop=[";", "\n\n"]
                )
            else:
                response = _call_openai_sync(
                    vllm_client,
                    model="Fin-R1",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=200,
                    stop=[";", "\n\n"]
                )

            sql = response.choices[0].message.content.strip()

            # 清理SQL（去除markdown代码块等）
            sql = re.sub(r'```sql\s*|\s*```', '', sql)
            sql = sql.strip()

            logger.info(f"AI生成SQL: {sql[:100]}...")
            return sql

        except Exception as e:
            logger.error(f"生成SQL失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            return ""
    
    @staticmethod
    def preprocess_sql(sql: str) -> str:
        """
        SQL预处理
        - 处理 INTERVAL 语法兼容
        - 强制添加LIMIT
        """
        # 转换 INTERVAL 语法
        # AI生成的: trade_date >= CURRENT_DATE - INTERVAL '30 days'
        # 转换为: trade_date >= '2024-01-01' (具体日期)
        import re
        from datetime import date, timedelta
        
        def replace_interval(match):
            days_str = match.group(1)
            try:
                days = int(days_str)
                target_date = date.today() - timedelta(days=days)
                return f"'{target_date}'"
            except:
                return match.group(0)
        
        # 替换 CURRENT_DATE - INTERVAL 'N days' 为具体日期
        sql = re.sub(
            r"CURRENT_DATE\s*-\s*INTERVAL\s+'(\d+)\s*days?'",
            replace_interval,
            sql,
            flags=re.IGNORECASE
        )
        
        # 强制添加LIMIT（如果没有）
        if 'LIMIT' not in sql.upper():
            sql = sql.rstrip(';') + " LIMIT 50"
        
        return sql
    
    @staticmethod
    def execute_sql(sql: str) -> Dict[str, Any]:
        """
        执行SQL并返回结果
        
        Args:
            sql: SQL语句
        
        Returns:
            {"columns": [...], "rows": [...], "error": None/str}
        """
        # 安全验证
        sql_upper = sql.upper()
        
        # 禁止危险操作
        forbidden_keywords = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE']
        for keyword in forbidden_keywords:
            if keyword in sql_upper:
                return {
                    "columns": [],
                    "rows": [],
                    "error": f"禁止执行修改操作: {keyword}"
                }
        
        # 预处理SQL
        sql = SQLAgent.preprocess_sql(sql)
        logger.info(f"执行SQL: {sql[:100]}...")
        
        try:
            with get_db_session() as session:
                result = session.execute(text(sql))
                
                # 获取列名
                columns = list(result.keys())
                
                # 获取数据
                rows = []
                for row in result:
                    rows.append([str(cell) for cell in row])
                
                logger.info(f"SQL执行成功: {len(rows)} 行")
                
                return {
                    "columns": columns,
                    "rows": rows,
                    "error": None
                }
                
        except Exception as e:
            logger.error(f"SQL执行失败: {e}")
            return {
                "columns": [],
                "rows": [],
                "error": str(e)
            }
    
    @staticmethod
    def format_result_for_prompt(result: Dict[str, Any]) -> str:
        """将查询结果格式化为字符串，放入prompt"""
        if result["error"]:
            return f"查询失败: {result['error']}"
        
        if not result["rows"]:
            return "查询结果为空（数据库中无匹配数据）"
        
        lines = []
        lines.append(" | ".join(result["columns"]))
        lines.append("-" * 50)
        
        for row in result["rows"][:20]:  # 最多显示20行
            lines.append(" | ".join(row))
        
        if len(result["rows"]) > 20:
            lines.append(f"... 共 {len(result['rows'])} 行数据，显示前20行")
        
        return "\n".join(lines)
    
    @staticmethod
    async def analyze_result(user_question: str, query_result: str, vllm_client) -> str:
        """
        让AI基于查询结果生成分析（支持同步和异步客户端）

        Args:
            user_question: 用户问题
            query_result: 格式化后的查询结果
            vllm_client: vLLM客户端

        Returns:
            AI分析结论
        """
        prompt = ANALYSIS_PROMPT.format(
            user_question=user_question,
            query_result=query_result
        )

        try:
            is_async = _is_async_client(vllm_client)

            if is_async:
                response = await _call_openai_async(
                    vllm_client,
                    model="Fin-R1",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=1000
                )
            else:
                response = _call_openai_sync(
                    vllm_client,
                    model="Fin-R1",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=1000
                )

            analysis = response.choices[0].message.content.strip()
            logger.info(f"AI分析完成: {len(analysis)} 字符")
            return analysis

        except Exception as e:
            logger.error(f"分析失败: {e}")
            import traceback
            logger.error(f"分析详细错误: {traceback.format_exc()}")
            return f"分析过程出错: {e}"
    
    @classmethod
    async def process_query(cls, user_question: str, vllm_client) -> Dict[str, Any]:
        """
        完整处理流程（异步版本）

        Returns:
            {
                "sql": 生成的SQL,
                "result": 查询结果,
                "analysis": AI分析,
                "full_response": 完整回复（包含SQL和结果）
            }
        """
        logger.info(f"处理查询: {user_question}")

        # 1. 生成SQL
        sql = await cls.generate_sql(user_question, vllm_client)
        if not sql:
            return {
                "sql": "",
                "result": {},
                "analysis": "无法生成SQL查询",
                "full_response": "抱歉，我无法理解您的查询需求。"
            }

        # 2. 执行SQL（同步操作，不需要await）
        result = cls.execute_sql(sql)

        # 3. 格式化结果（同步操作，不需要await）
        result_text = cls.format_result_for_prompt(result)

        # 4. AI分析
        analysis = await cls.analyze_result(user_question, result_text, vllm_client)

        # 5. 组装完整回复
        full_response = f"""【查询SQL】
```sql
{sql}
```

【查询结果】
{result_text}

【分析结论】
{analysis}
"""

        return {
            "sql": sql,
            "result": result,
            "analysis": analysis,
            "full_response": full_response
        }
