#!/bin/bash
#
# PostgreSQL Docker 备份脚本
# 适用于 PostgreSQL 运行在 Docker 容器内的场景
#

set -e

# 配置
CONTAINER_NAME="infra-postgresql-1"  # Docker 容器名称
DB_NAME="finr1_data"
DB_USER="game_agents"
BACKUP_DIR="/data/backup/finr1"
RETENTION_DAYS=30

# 日期
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${DATE}.sql.gz"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# 检查容器是否运行
check_container() {
    if ! docker ps | grep -q "$CONTAINER_NAME"; then
        log_error "PostgreSQL 容器未运行: $CONTAINER_NAME"
        exit 1
    fi
    log_info "PostgreSQL 容器运行正常: $CONTAINER_NAME"
}

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 执行备份
log_info "开始备份数据库: $DB_NAME"
log_info "备份文件: $BACKUP_FILE"

# 获取数据库大小
DB_SIZE=$(docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT pg_size_pretty(pg_database_size('$DB_NAME'));" | xargs)
log_info "数据库大小: $DB_SIZE"

# 执行备份（在容器内执行 pg_dump，然后压缩输出到宿主机）
log_info "正在导出数据..."
if docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip > "$BACKUP_FILE"; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log_info "✅ 备份成功! 文件大小: $BACKUP_SIZE"
    
    # 验证备份
    if gunzip -t "$BACKUP_FILE" 2>/dev/null; then
        log_info "✅ 备份文件验证通过"
    else
        log_error "❌ 备份文件损坏"
        rm -f "$BACKUP_FILE"
        exit 1
    fi
else
    log_error "❌ 备份失败"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# 清理旧备份
log_info "清理旧备份（保留${RETENTION_DAYS}天）..."
deleted=0
while IFS= read -r file; do
    log_info "删除旧备份: $(basename "$file")"
    rm -f "$file"
    ((deleted++))
done < <(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f -mtime +$RETENTION_DAYS)

log_info "清理完成，删除了 $deleted 个旧备份文件"

# 显示备份列表
log_info "当前备份文件:"
ls -lh "${BACKUP_DIR}"/*.sql.gz 2>/dev/null || log_warn "无备份文件"

log_info "备份任务完成!"
