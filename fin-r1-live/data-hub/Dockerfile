# Fin-R1 Data Hub - Auto Sync Service Dockerfile
# 自动数据同步服务 - 启动时自动检查并下载缺失数据
# 使用多阶段构建优化镜像体积

# 构建阶段
FROM python:3.9-slim as builder

WORKDIR /app

# 安装编译依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖到虚拟环境（简化安装逻辑）
COPY requirements.txt .
RUN python -m venv /opt/venv
RUN /opt/venv/bin/pip install --upgrade pip
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com

# 运行阶段
FROM python:3.9-slim

WORKDIR /app

# 复制虚拟环境
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 安装运行时必需的系统库并创建用户
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser

# 复制代码
COPY database.py .
COPY history_downloader.py .
COPY history_downloader_with_resume.py .
COPY auto_sync.py .
COPY fundamental_fetcher.py .
COPY fundamental_sync.py .
COPY data_validator.py .
COPY data_inventory.py .
COPY resume_manager.py .
COPY startup.py .
COPY startup_auto_resume.py .
COPY update_stock_names_csv.py .
COPY fetch_all_stocks_complete.py .

# 创建目录并设置权限
RUN mkdir -p /app/logs && chmod 777 /app/logs && chown -R appuser:appuser /app

# 使用非root用户运行
USER appuser

# 默认命令：使用自动断点续传启动脚本
CMD ["python", "startup_auto_resume.py"]
