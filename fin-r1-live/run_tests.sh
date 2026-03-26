#!/bin/bash
# =============================================================================
# Fin-R1 测试运行脚本
# 运行完整测试套件并生成报告
# =============================================================================

set -e

# 彩色输出
print_info() { echo -e "\033[32m[INFO] $1\033[0m"; }
print_warn() { echo -e "\033[33m[WARN] $1\033[0m"; }
print_error() { echo -e "\033[31m[ERROR] $1\033[0m"; }
print_success() { echo -e "\033[1;32m[SUCCESS] $1\033[0m"; }
print_header() { echo -e "\033[1;36m$1\033[0m"; }

# 配置
TEST_DIR="$(cd "$(dirname "$0")" && pwd)/test"
RESULTS_DIR="${TEST_DIR}/results"
COVERAGE_THRESHOLD=99

# 创建结果目录
mkdir -p "${RESULTS_DIR}"

echo ""
print_header "╔══════════════════════════════════════════════════════════════╗"
print_header "║         Fin-R1 Live Data Middleware - 测试套件               ║"
print_header "╚══════════════════════════════════════════════════════════════╝"
echo ""

# 检查依赖
print_info "检查测试依赖..."
if ! python -c "import pytest" 2>/dev/null; then
    print_info "安装测试依赖..."
    pip install -q -r "${TEST_DIR}/requirements.txt"
fi
print_success "依赖检查完成"

# 清理之前的测试结果
print_info "清理历史测试结果..."
rm -rf "${TEST_DIR}/__pycache__"
rm -rf "${TEST_DIR}"/*/__pycache__
rm -rf "${TEST_DIR}/.pytest_cache"
rm -f "${TEST_DIR}/.coverage"
rm -f "${RESULTS_DIR}"/*.xml
rm -f "${RESULTS_DIR}"/*.html

echo ""
print_header "═══════════════════════════════════════════════════════════════"
print_header "阶段 1/4: 运行单元测试 (Unit Tests)"
print_header "═══════════════════════════════════════════════════════════════"

python -m pytest "${TEST_DIR}/test_api_middleware/test_config.py" -v \
    --tb=short \
    -p no:warnings \
    --color=yes 2>&1 | tee "${RESULTS_DIR}/test_config.log"

python -m pytest "${TEST_DIR}/test_api_middleware/test_realtime_fetcher.py" -v \
    --tb=short \
    -p no:warnings \
    --color=yes 2>&1 | tee "${RESULTS_DIR}/test_realtime_fetcher.log"

python -m pytest "${TEST_DIR}/test_api_middleware/test_database_client.py" -v \
    --tb=short \
    -p no:warnings \
    --color=yes 2>&1 | tee "${RESULTS_DIR}/test_database_client.log"

echo ""
print_header "═══════════════════════════════════════════════════════════════"
print_header "阶段 2/4: 运行 API 中间层测试"
print_header "═══════════════════════════════════════════════════════════════"

python -m pytest "${TEST_DIR}/test_api_middleware/test_main.py" -v \
    --tb=short \
    -p no:warnings \
    --color=yes 2>&1 | tee "${RESULTS_DIR}/test_main.log"

echo ""
print_header "═══════════════════════════════════════════════════════════════"
print_header "阶段 3/4: 运行 Data Hub 测试"
print_header "═══════════════════════════════════════════════════════════════"

python -m pytest "${TEST_DIR}/test_data_hub/" -v \
    --tb=short \
    -p no:warnings \
    --color=yes 2>&1 | tee "${RESULTS_DIR}/test_data_hub.log"

echo ""
print_header "═══════════════════════════════════════════════════════════════"
print_header "阶段 4/4: 覆盖率检查 (目标: >99%)"
print_header "═══════════════════════════════════════════════════════════════"

python -m pytest "${TEST_DIR}/" \
    --cov=api-middleware \
    --cov=data-hub \
    --cov-report=term-missing \
    --cov-report=html:"${RESULTS_DIR}/coverage_html" \
    --cov-report=xml:"${RESULTS_DIR}/coverage.xml" \
    --cov-fail-under=${COVERAGE_THRESHOLD} \
    --tb=short \
    -p no:warnings \
    --color=yes 2>&1 | tee "${RESULTS_DIR}/coverage.log"

# 生成测试报告
print_info "生成 HTML 测试报告..."
python -m pytest "${TEST_DIR}/" \
    --html="${RESULTS_DIR}/report.html" \
    --self-contained-html \
    --tb=short \
    -p no:warnings 2>/dev/null || true

echo ""
print_header "═══════════════════════════════════════════════════════════════"
print_success "测试完成!"
print_header "═══════════════════════════════════════════════════════════════"
echo ""

# 显示结果摘要
if [ -f "${RESULTS_DIR}/coverage.xml" ]; then
    # 解析覆盖率
    COVERAGE=$(python3 << 'EOF'
import xml.etree.ElementTree as ET
import sys
try:
    tree = ET.parse(sys.argv[1])
    root = tree.getroot()
    coverage = float(root.get('line-rate', 0)) * 100
    print(f"{coverage:.2f}")
except:
    print("0.00")
EOF
    "${RESULTS_DIR}/coverage.xml")
    
    echo "📊 覆盖率报告:"
    echo "  - 行覆盖率: ${COVERAGE}%"
    echo "  - 目标: >${COVERAGE_THRESHOLD}%"
    
    if (( $(echo "$COVERAGE > $COVERAGE_THRESHOLD" | bc -l) )); then
        print_success "✅ 覆盖率达标!"
    else
        print_warn "⚠️  覆盖率未达标 (目标: ${COVERAGE_THRESHOLD}%)"
    fi
fi

echo ""
echo "📁 测试报告位置:"
echo "  - HTML报告: ${RESULTS_DIR}/report.html"
echo "  - 覆盖率报告: ${RESULTS_DIR}/coverage_html/index.html"
echo "  - XML覆盖率: ${RESULTS_DIR}/coverage.xml"
echo "  - 详细日志: ${RESULTS_DIR}/*.log"
echo ""

# 生成简化摘要
print_header "═══════════════════════════════════════════════════════════════"
print_header "测试摘要"
print_header "═══════════════════════════════════════════════════════════════"

PASSED=$(grep -c "PASSED" "${RESULTS_DIR}"/*.log 2>/dev/null || echo "0")
FAILED=$(grep -c "FAILED" "${RESULTS_DIR}"/*.log 2>/dev/null || echo "0")
ERRORS=$(grep -c "ERROR" "${RESULTS_DIR}"/*.log 2>/dev/null || echo "0")

echo "  ✅ 通过: ${PASSED} 个测试"
echo "  ❌ 失败: ${FAILED} 个测试"
echo "  ⚠️  错误: ${ERRORS} 个错误"
echo ""

if [ "$FAILED" -eq 0 ] && [ "$ERRORS" -eq 0 ]; then
    print_success "🎉 所有测试通过! 项目可以安全部署。"
else
    print_error "⚠️  存在失败的测试，请检查日志文件。"
    exit 1
fi

echo ""
print_header "═══════════════════════════════════════════════════════════════"
echo ""
