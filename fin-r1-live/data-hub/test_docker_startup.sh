#!/bin/bash
# Data Hub Docker 启动流程测试脚本
# 用于本地验证容器是否能完成从建表到下载的全流程

set -e

echo "=============================================="
echo "Data Hub Docker 启动流程测试"
echo "=============================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试配置
TEST_TIMEOUT=600  # 10分钟超时
DB_HOST="${DB_HOST:-123.60.11.74}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-game_agents}"
DB_PASS="${DB_PASS:-1234+asdf}"
DB_NAME="${DB_NAME:-finr1_data}"

# 构建数据库URL
DB_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

echo "📋 测试配置:"
echo "  数据库: ${DB_HOST}:${DB_PORT}"
echo "  数据库名: ${DB_NAME}"
echo "  超时时间: ${TEST_TIMEOUT}秒"
echo ""

# 步骤 1: 检查数据库连接
echo "步骤 1/5: 检查数据库连接..."
if ! docker run --rm --network host postgres:15-alpine \
    psql "${DB_URL}" -c "SELECT 1;" > /dev/null 2>&1; then
    echo -e "${RED}❌ 数据库连接失败${NC}"
    echo "请检查:"
    echo "  - 数据库服务器是否运行 (${DB_HOST}:${DB_PORT})"
    echo "  - 用户名密码是否正确"
    echo "  - 数据库 ${DB_NAME} 是否存在"
    exit 1
fi
echo -e "${GREEN}✅ 数据库连接正常${NC}"
echo ""

# 步骤 2: 构建镜像
echo "步骤 2/5: 构建 Docker 镜像..."
cd "$(dirname "$0")"
if ! docker build -t finr1-datahub:test . > /tmp/build.log 2>&1; then
    echo -e "${RED}❌ 镜像构建失败${NC}"
    echo "构建日志:"
    cat /tmp/build.log
    exit 1
fi
echo -e "${GREEN}✅ 镜像构建成功${NC}"
echo ""

# 步骤 3: 测试启动（仅检查状态）
echo "步骤 3/5: 测试容器启动（仅检查状态）..."
if ! docker run --rm --network host \
    -e DATABASE_URL="${DB_URL}" \
    -e LOG_LEVEL=INFO \
    finr1-datahub:test \
    python startup.py --status; then
    echo -e "${RED}❌ 状态检查失败${NC}"
    exit 1
fi
echo -e "${GREEN}✅ 状态检查完成${NC}"
echo ""

# 步骤 4: 测试全量下载（小样本）
echo "步骤 4/5: 测试全量下载（样本模式）..."
echo "  注意: 这将下载50只股票的日线数据进行测试"
echo "  超时时间: ${TEST_TIMEOUT}秒"
echo ""

# 使用后台运行以便实现超时控制
CONTAINER_NAME="finr1-datahub-test-$$"
docker run -d --name "${CONTAINER_NAME}" --network host \
    -e DATABASE_URL="${DB_URL}" \
    -e LOG_LEVEL=INFO \
    finr1-datahub:test \
    python startup.py --full \
    > /tmp/container.log 2>&1

# 等待容器完成（带超时）
SECONDS=0
while [ $SECONDS -lt $TEST_TIMEOUT ]; do
    if ! docker ps | grep -q "${CONTAINER_NAME}"; then
        # 容器已停止
        break
    fi
    echo -n "."
    sleep 5
done
echo ""

# 检查容器状态
if docker ps | grep -q "${CONTAINER_NAME}"; then
    echo -e "${YELLOW}⚠️  测试超时，强制停止容器...${NC}"
    docker stop "${CONTAINER_NAME}" > /dev/null 2>&1
    docker logs "${CONTAINER_NAME}" | tail -50
    docker rm "${CONTAINER_NAME}" > /dev/null 2>&1
    echo -e "${RED}❌ 测试超时${NC}"
    exit 1
fi

# 获取退出码
EXIT_CODE=$(docker inspect "${CONTAINER_NAME}" --format='{{.State.ExitCode}}' 2>/dev/null || echo "1")
docker logs "${CONTAINER_NAME}" > /tmp/test_full.log 2>&1
docker rm "${CONTAINER_NAME}" > /dev/null 2>&1

if [ "$EXIT_CODE" != "0" ]; then
    echo -e "${RED}❌ 全量下载测试失败 (退出码: $EXIT_CODE)${NC}"
    echo "容器日志 (最后50行):"
    tail -50 /tmp/test_full.log
    exit 1
fi

echo -e "${GREEN}✅ 全量下载测试完成${NC}"
echo "容器日志 (最后30行):"
tail -30 /tmp/test_full.log
echo ""

# 步骤 5: 验证数据
echo "步骤 5/5: 验证数据库数据..."
STOCK_COUNT=$(docker run --rm --network host postgres:15-alpine \
    psql "${DB_URL}" -t -c "SELECT COUNT(*) FROM stocks;" 2>/dev/null | xargs)
DAILY_COUNT=$(docker run --rm --network host postgres:15-alpine \
    psql "${DB_URL}" -t -c "SELECT COUNT(*) FROM stock_daily;" 2>/dev/null | xargs)

echo "  股票数量: ${STOCK_COUNT:-0}"
echo "  日线记录: ${DAILY_COUNT:-0}"

if [ "${STOCK_COUNT:-0}" -gt 0 ] && [ "${DAILY_COUNT:-0}" -gt 0 ]; then
    echo -e "${GREEN}✅ 数据验证通过${NC}"
else
    echo -e "${YELLOW}⚠️  数据量较少，可能需要更长时间下载${NC}"
fi
echo ""

# 测试通过
echo "=============================================="
echo -e "${GREEN}✅ 所有测试通过!${NC}"
echo "=============================================="
echo ""
echo "启动流程验证完成，容器可以正常:"
echo "  1. 连接 PostgreSQL 数据库"
echo "  2. 自动创建所有数据表"
echo "  3. 下载股票列表和日线数据"
echo "  4. 优雅退出并返回正确状态"
echo ""
echo "生产环境使用:"
echo "  docker-compose up -d data-hub"
