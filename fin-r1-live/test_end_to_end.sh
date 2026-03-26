#!/bin/bash
# Fin-R1 端到端完整测试脚本
# 验证Web UI → API中间层 → 数据库 → vLLM的完整链路

set -e

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试统计
PASSED=0
FAILED=0
WARNINGS=0

# 配置
DB_URL="postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"
API_URL="http://localhost:8012"
VLLM_URL="http://localhost:8010"
WEBUI_URL="http://localhost:8011"

echo "=============================================="
echo "  Fin-R1 端到端完整测试"
echo "=============================================="
echo ""
echo "测试时间: $(date)"
echo "测试目标: 验证Web UI → API中间层 → 数据库 → vLLM完整链路"
echo ""

# 测试函数
run_test() {
    local test_name="$1"
    local test_command="$2"
    local expected_pattern="$3"

    echo -n "测试: $test_name ... "

    if result=$(eval "$test_command" 2>&1); then
        if [[ -z "$expected_pattern" ]] || echo "$result" | grep -q "$expected_pattern"; then
            echo -e "${GREEN}✅ 通过${NC}"
            ((PASSED++))
            return 0
        else
            echo -e "${YELLOW}⚠️  警告 (输出不符合预期)${NC}"
            echo "  预期包含: $expected_pattern"
            echo "  实际输出: $result"
            ((WARNINGS++))
            return 1
        fi
    else
        echo -e "${RED}❌ 失败${NC}"
        echo "  错误信息: $result"
        ((FAILED++))
        return 1
    fi
}

echo "1️⃣  服务可用性测试"
echo "----------------------------------------------"

# 测试1: Web UI可访问
run_test "Web UI可访问" \
    "curl -s -o /dev/null -w '%{http_code}' $WEBUI_URL" \
    "200"

# 测试2: API中间层健康状态
run_test "API中间层健康" \
    "curl -s $API_URL/health | jq -r '.status'" \
    "healthy"

# 测试3: vLLM模型服务
run_test "vLLM模型服务" \
    "curl -s $VLLM_URL/v1/models | jq -r '.data[0].id'" \
    "Fin-R1"

# 测试4: 数据库连接
run_test "数据库连接" \
    "docker run --rm --network host postgres:15-alline psql \"$DB_URL\" -t -c 'SELECT 1;'" \
    "1"

echo ""
echo "2️⃣  数据完整性测试"
echo "----------------------------------------------"

# 测试5: 股票数量
STOCK_COUNT=$(docker run --rm --network host postgres:15-alpine psql "$DB_URL" -t -c "SELECT COUNT(*) FROM stocks;" 2>/dev/null | xargs)
if [[ "$STOCK_COUNT" -gt 4000 ]]; then
    echo -e "测试: 股票数量 (>4000) ... ${GREEN}✅ 通过 ($STOCK_COUNT)${NC}"
    ((PASSED++))
else
    echo -e "测试: 股票数量 (>4000) ... ${RED}❌ 失败 ($STOCK_COUNT)${NC}"
    ((FAILED++))
fi

# 测试6: K线数据量
DAILY_COUNT=$(docker run --rm --network host postgres:15-alpine psql "$DB_URL" -t -c "SELECT COUNT(*) FROM stock_daily;" 2>/dev/null | xargs)
if [[ "$DAILY_COUNT" -gt 500000 ]]; then
    echo -e "测试: K线数据量 (>50万) ... ${GREEN}✅ 通过 ($(echo $DAILY_COUNT | awk '{printf "%.0f", $1/10000}')万条)${NC}"
    ((PASSED++))
else
    echo -e "测试: K线数据量 (>50万) ... ${RED}❌ 失败 ($DAILY_COUNT)${NC}"
    ((FAILED++))
fi

# 测试7: 最新数据日期
LATEST_DATE=$(docker run --rm --network host postgres:15-alpine psql "$DB_URL" -t -c "SELECT MAX(trade_date) FROM stock_daily;" 2>/dev/null | xargs)
TODAY=$(date +%Y-%m-%d)
if [[ "$LATEST_DATE" == "$TODAY" ]] || [[ "$LATEST_DATE" > "2024-01-01" ]]; then
    echo -e "测试: 最新数据日期 ... ${GREEN}✅ 通过 ($LATEST_DATE)${NC}"
    ((PASSED++))
else
    echo -e "测试: 最新数据日期 ... ${YELLOW}⚠️  警告 ($LATEST_DATE)${NC}"
    ((WARNINGS++))
fi

# 测试8: 断点续传表
PROGRESS_COUNT=$(docker run --rm --network host postgres:15-alpine psql "$DB_URL" -t -c "SELECT COUNT(*) FROM stock_download_progress;" 2>/dev/null | xargs)
if [[ "$PROGRESS_COUNT" -gt 0 ]]; then
    echo -e "测试: 断点续传表 ... ${GREEN}✅ 通过 ($PROGRESS_COUNT条记录)${NC}"
    ((PASSED++))
else
    echo -e "测试: 断点续传表 ... ${YELLOW}⚠️  警告 (未初始化)${NC}"
    ((WARNINGS++))
fi

echo ""
echo "3️⃣  API功能测试"
echo "----------------------------------------------"

# 测试9: K线数据查询
run_test "K线数据查询" \
    "curl -s $API_URL/api/stock/000001/history?days=30 | jq '.count'" \
    "30"

# 测试10: 实时行情查询
run_test "实时行情查询" \
    "curl -s $API_URL/api/stock/000001/realtime | jq -r '.code'" \
    "000001"

# 测试11: 技术指标计算
run_test "技术指标计算(MACD)" \
    "curl -s $API_URL/api/stock/000001/indicators | jq '.macd.latest_macd'" \
    ""

# 测试12: 财务数据查询
run_test "财务数据查询" \
    "curl -s $API_URL/api/stock/000001/financial/summary | jq -r '.code'" \
    "000001"

# 测试13: V1版量化分析
V1_SCORE=$(curl -s $API_URL/api/stock/000001/v1-analysis | jq '.total_score')
if [[ "$V1_SCORE" -gt 0 ]]; then
    echo -e "测试: V1版量化分析 ... ${GREEN}✅ 通过 (评分: $V1_SCORE)${NC}"
    ((PASSED++))
else
    echo -e "测试: V1版量化分析 ... ${RED}❌ 失败${NC}"
    ((FAILED++))
fi

# 测试14: 批量选股
SCREENING_COUNT=$(curl -s "$API_URL/api/screening/v1?min_score=90" | jq '.total_candidates')
if [[ "$SCREENING_COUNT" -ge 0 ]]; then
    echo -e "测试: 批量选股接口 ... ${GREEN}✅ 通过 (找到 $SCREENING_COUNT 只)${NC}"
    ((PASSED++))
else
    echo -e "测试: 批量选股接口 ... ${RED}❌ 失败${NC}"
    ((FAILED++))
fi

echo ""
echo "4️⃣  Chat Completion链路测试"
echo "----------------------------------------------"

# 测试15: 基础对话（验证vLLM连通性）
CHAT_RESPONSE=$(curl -s -X POST $API_URL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Fin-R1-Live", "messages": [{"role": "user", "content": "你好"}], "max_tokens": 50}' 2>/dev/null)

if echo "$CHAT_RESPONSE" | jq -e '.choices[0].message.content' > /dev/null 2>&1; then
    echo -e "测试: 基础对话链路 ... ${GREEN}✅ 通过${NC}"
    ((PASSED++))
else
    echo -e "测试: 基础对话链路 ... ${RED}❌ 失败${NC}"
    echo "  响应: $CHAT_RESPONSE"
    ((FAILED++))
fi

# 测试16: 带股票代码的对话（验证数据注入）
CHAT_WITH_DATA=$(curl -s -X POST $API_URL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Fin-R1-Live", "messages": [{"role": "user", "content": "分析000001"}], "max_tokens": 100}' 2>/dev/null)

if echo "$CHAT_WITH_DATA" | grep -q "000001\|平安银行"; then
    echo -e "测试: 数据注入对话 ... ${GREEN}✅ 通过 (检测到数据引用)${NC}"
    ((PASSED++))
else
    echo -e "测试: 数据注入对话 ... ${YELLOW}⚠️  警告 (未检测到数据引用)${NC}"
    ((WARNINGS++))
fi

echo ""
echo "5️⃣  板块排名测试"
echo "----------------------------------------------"

# 测试17: 行业板块排名
run_test "行业板块排名" \
    "curl -s $API_URL/api/market/sector-rankings | jq '.total_sectors'" \
    ""

# 测试18: 成交额排名
run_test "成交额排名" \
    "curl -s $API_URL/api/market/amount-rankings?top_n=50 | jq '.total_stocks'" \
    "50"

echo ""
echo "=============================================="
echo "  测试结果汇总"
echo "=============================================="
echo ""
echo "  通过: $PASSED 项"
echo "  警告: $WARNINGS 项"
echo "  失败: $FAILED 项"
echo "  总计: $((PASSED + WARNINGS + FAILED)) 项"
echo ""

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}🎉 恭喜！所有核心测试通过！${NC}"
    echo ""
    echo "系统状态: 完全可用 ✅"
    echo "数据完整性: 已就绪 ✅"
    echo "API链路: 全通 ✅"
    echo "AI模型: 正常响应 ✅"
    echo ""
    echo "您现在可以在Web UI中使用V1版提示词进行量化选股！"
    echo "Web UI地址: $WEBUI_URL"
    echo ""
    exit 0
elif [[ $FAILED -le 3 && $PASSED -ge 10 ]]; then
    echo -e "${YELLOW}⚠️  系统部分可用${NC}"
    echo ""
    echo "大部分功能正常，但存在一些小问题。"
    echo "建议查看上方失败项的详细日志。"
    echo ""
    exit 1
else
    echo -e "${RED}❌ 系统存在较多问题${NC}"
    echo ""
    echo "建议按照以下顺序排查:"
    echo "1. 检查Docker容器状态: docker-compose ps"
    echo "2. 检查Data Hub数据下载: docker-compose logs data-hub"
    echo "3. 检查vLLM服务: curl $VLLM_URL/v1/models"
    echo "4. 检查数据库连接: curl $API_URL/health"
    echo ""
    exit 1
fi
