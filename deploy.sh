#!/bin/bash
# =============================================================================
# Fin-R1 Live Data Middleware - 部署脚本
# 使用现有的 PostgreSQL 服务器 (123.60.11.74:5432)
# 自动下载历史数据（检查并补全）
# =============================================================================

set -e

# 彩色输出
print_info() { echo -e "\033[32m[INFO] $1\033[0m"; }
print_warn() { echo -e "\033[33m[WARN] $1\033[0m"; }
print_error() { echo -e "\033[31m[ERROR] $1\033[0m"; exit 1; }
print_success() { echo -e "\033[1;32m[SUCCESS] $1\033[0m"; }

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     Fin-R1 实时数据中间层 - 部署脚本                          ║"
echo "║     PostgreSQL: 123.60.11.74:5432 / finr1_data              ║"
echo "║     自动同步: 检查缺失数据并自动下载                          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# 配置
BASE_DIR="/home/data/fin-r1-live"
VLLM_URL="http://172.17.0.1:8010"

# 检查root权限
if [ "$(id -u)" -ne 0 ]; then
    print_error "请使用root用户执行: sudo ./deploy.sh"
fi

# 检查Docker
print_info "检查Docker环境..."
if ! command -v docker &> /dev/null; then
    print_error "Docker未安装"
fi
if ! docker info &> /dev/null; then
    print_error "Docker服务未运行"
fi
print_success "Docker环境正常"

# 进入目录
cd "${BASE_DIR}" 2>/dev/null || {
    print_info "创建项目目录: ${BASE_DIR}"
    mkdir -p "${BASE_DIR}"
    cd "${BASE_DIR}"
}

print_info "当前目录: $(pwd)"

# 检查是否是更新部署
if docker ps | grep -q "finr1-middleware"; then
    print_warn "检测到已有部署，执行更新..."
    docker-compose down 2>/dev/null || true
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
print_info "步骤1/3: 构建Docker镜像"
echo "═══════════════════════════════════════════════════════════════"

docker-compose build

print_success "镜像构建完成"

echo ""
echo "═══════════════════════════════════════════════════════════════"
print_info "步骤2/3: 启动数据同步服务（自动检查并下载历史数据）"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "此步骤会:"
echo "  1. 检查 PostgreSQL 中是否有从2024-01-01开始的数据"
echo "  2. 如果没有完整数据，自动下载全部历史数据"
echo "  3. 如果有部分数据，自动补全到今天的数据"
echo ""
read -p "按回车键开始数据同步，或按 Ctrl+C 跳过（之后可手动执行）..."

# 先启动数据服务进行同步
docker-compose up data-hub

print_success "数据同步完成"

echo ""
echo "═══════════════════════════════════════════════════════════════"
print_info "步骤3/3: 启动完整服务栈（vLLM + 中间层 + WebUI）"
echo "═══════════════════════════════════════════════════════════════"

# 启动所有服务（后台运行）
docker-compose up -d

print_info "等待服务启动(15秒)..."
sleep 15

# 健康检查
echo ""
print_info "检查服务状态..."

# 检查 vLLM
if curl -s http://localhost:8010/v1/models > /dev/null 2>&1; then
    print_success "✅ vLLM 服务正常 (http://localhost:8010)"
else
    print_warn "⚠️  vLLM 可能还在启动中（模型加载需要几分钟）"
    echo "    查看日志: docker-compose logs -f fin-r1-vllm"
fi

# 检查中间层
if curl -s http://localhost:8012/health > /dev/null 2>&1; then
    print_success "✅ API中间层正常 (http://localhost:8012)"
    curl -s http://localhost:8012/health | python3 -m json.tool 2>/dev/null || true
else
    print_warn "⚠️  中间层可能还在启动中"
    echo "    查看日志: docker-compose logs -f api-middleware"
fi

# 检查 WebUI
echo ""
print_success "✅ WebUI 已启动 (http://localhost:8011)"

echo ""
echo "═══════════════════════════════════════════════════════════════"
print_success "部署完成!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
# 获取服务器IP
SERVER_IP=$(hostname -I | awk '{print $1}')

echo "服务访问地址（公网可直接访问）:"
echo "  - WebUI:        http://${SERVER_IP}:8011  (直接在浏览器打开)"
echo "  - API中间层:    http://${SERVER_IP}:8012  (应用程序调用)"
echo "  - vLLM服务:     http://localhost:8010    (仅限服务器本地)"
echo "  - PostgreSQL:   123.60.11.74:5432 / finr1_data"
echo ""
echo "GPU配置:"
echo "  - 默认使用GPU: ${GPU_DEVICE_ID:-all} (可在.env文件中通过GPU_DEVICE_ID修改)"
echo ""
echo "常用命令:"
echo "  查看所有日志:       docker-compose logs -f"
echo "  查看vLLM日志:       docker-compose logs -f fin-r1-vllm"
echo "  查看中间层日志:     docker-compose logs -f api-middleware"
echo "  查看WebUI日志:      docker-compose logs -f fin-r1-webui"
echo "  停止所有服务:       docker-compose down"
echo "  重启服务:           docker-compose restart"
echo "  手动数据同步:       docker-compose run --rm data-hub python auto_sync.py"
echo "  检查数据状态:       docker-compose run --rm data-hub python auto_sync.py --status"
echo ""
echo "验证命令:"
echo "  curl http://${SERVER_IP}:8010/v1/models        # 检查vLLM"
echo "  curl http://${SERVER_IP}:8012/health             # 检查中间层"
echo "  curl http://${SERVER_IP}:8012/api/stock/000001/realtime"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "⚠️  安全提示: 8011和8012端口已开放公网访问"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "生产环境建议:"
echo "  1. 配置防火墙限制IP白名单"
echo "  2. 在API中间层前添加Nginx反向代理"
echo "  3. 启用HTTPS加密传输"
echo "  4. 配置API密钥认证（config.py中设置API_KEY）"
echo ""
echo "防火墙配置示例（UFW）:"
echo "  ufw allow from 你的办公IP to any port 8011"
echo "  ufw allow from 你的办公IP to any port 8012"
echo "  ufw deny 8011"
echo "  ufw deny 8012"
echo ""
