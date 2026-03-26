#!/bin/bash
set -e

# ===================== 配置项（根据你的环境调整） =====================
# 虚拟环境路径（替换为你实际的3.9虚拟环境路径）
VENV_PATH="/home/data/python_env/kimi_env39"
# 模型保存目录（必须在/home/data，避免根目录占用）
MODEL_SAVE_DIR="/home/data/Fin-R1"
# 模型名称（Hugging Face仓库名，固定）
MODEL_NAME="SUFE-AIFLM-Lab/Fin-R1"
# 量化版本（可选：fp16/int8/int4，int8最均衡，A800推荐int8）
QUANTIZE_TYPE="int8"
# =====================================================================

# 彩色日志函数（保留原风格）
print_info() { echo -e "\033[32m[INFO] $1\033[0m"; }
print_warn() { echo -e "\033[33m[WARN] $1\033[0m"; }
print_error() { echo -e "\033[31m[ERROR] $1\033[0m"; exit 1; }

# 步骤1：检查root权限
if [ "$(id -u)" -ne 0 ]; then
    print_error "请使用root用户执行：sudo ./download_fin_r1.sh"
fi

# 步骤2：检查虚拟环境是否存在
if [ ! -f "${VENV_PATH}/bin/activate" ]; then
    print_error "虚拟环境不存在！请检查路径：${VENV_PATH}"
fi

# 步骤3：根据量化类型设置所需磁盘空间
print_info "检查磁盘空间..."
case ${QUANTIZE_TYPE} in
    "int4") REQUIRED_SPACE=5 ;;   # INT4约4GB，留1GB余量
    "int8") REQUIRED_SPACE=10 ;;  # INT8约8GB，留2GB余量
    "fp16") REQUIRED_SPACE=15 ;;  # FP16约14GB，留1GB余量
    *) print_error "不支持的量化类型！可选：int4/int8/fp16" ;;
esac

AVAIL_SPACE=$(df -BG "${MODEL_SAVE_DIR%/*}" | grep -v Filesystem | awk '{print $4}' | sed 's/G//')
if [ "$AVAIL_SPACE" -lt "$REQUIRED_SPACE" ]; then
    print_error "可用空间不足！需要${REQUIRED_SPACE}GB，当前：${AVAIL_SPACE}GB"
fi

# 步骤4：激活虚拟环境
print_info "激活Python 3.9虚拟环境..."
source "${VENV_PATH}/bin/activate"

# 步骤5：验证huggingface_hub依赖（核心下载依赖）
print_info "验证Hugging Face环境..."
if ! python -c "import huggingface_hub" 2>/dev/null; then
    print_info "未安装huggingface_hub，开始安装..."
    pip install huggingface_hub git-lfs -i https://pypi.tuna.tsinghua.edu.cn/simple || print_error "huggingface_hub安装失败"
fi
HF_VERSION=$(python -c "import huggingface_hub; print(huggingface_hub.__version__)")
print_info "当前huggingface_hub版本：${HF_VERSION}"

# 步骤6：初始化git-lfs（权重文件依赖）
print_info "初始化git-lfs..."
git lfs install >/dev/null 2>&1 || print_warn "git-lfs初始化警告（不影响下载）"

# 步骤7：创建模型保存目录
print_info "创建模型保存目录：${MODEL_SAVE_DIR}"
mkdir -p "${MODEL_SAVE_DIR}"
chmod 755 "${MODEL_SAVE_DIR}"

# 步骤8：下载Fin-R1模型
python -c """
from huggingface_hub import snapshot_download
import os
import sys

try:
    # 下载模型到指定目录，支持断点续传
    snapshot_download(
        repo_id='${MODEL_NAME}',
        local_dir='${MODEL_SAVE_DIR}',
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    print('✅ Fin-R1模型下载命令执行成功')
except Exception as e:
    print(f'❌ 下载异常：{str(e)}', file=sys.stderr)
    sys.exit(1)
""" || print_error "模型下载失败！请检查网络或重试"

# 步骤9：校验模型文件完整性（核心权重文件校验）
print_info "校验${QUANTIZE_TYPE}模型文件完整性..."
# Fin-R1核心权重文件：safetensors/bin格式，不同量化对应不同后缀
if [ "${QUANTIZE_TYPE}" = "fp16" ]; then
    CORE_FILES=$(find "${MODEL_SAVE_DIR}" -name "*.safetensors" -o -name "*fp16*.bin" | wc -l)
elif [ "${QUANTIZE_TYPE}" = "int8" ]; then
    CORE_FILES=$(find "${MODEL_SAVE_DIR}" -name "*int8*.safetensors" -o -name "*int8*.bin" | wc -l)
elif [ "${QUANTIZE_TYPE}" = "int4" ]; then
    CORE_FILES=$(find "${MODEL_SAVE_DIR}" -name "*int4*.safetensors" -o -name "*int4*.bin" | wc -l)
fi

# 校验逻辑：至少存在1个核心权重文件即视为下载启动成功（Fin-R1 7B通常1-2个核心文件）
if [ "${CORE_FILES}" -ge 1 ]; then
    print_info "======================================"
    print_info "🎉 Fin-R1 ${QUANTIZE_TYPE}模型下载启动成功！"
    print_info "📌 模型目录：${MODEL_SAVE_DIR}"
    print_info "💡 下载为断点续传模式，可通过以下命令查看进度："
    print_info "   ls -lh ${MODEL_SAVE_DIR} | grep -E 'safetensors|bin'"
    print_info "✅ 当前已下载${CORE_FILES}个${QUANTIZE_TYPE}权重文件（最终需1-2个）"
    print_info "======================================"
else
    print_warn "⚠️ 暂未检测到${QUANTIZE_TYPE}核心文件，可能下载仍在进行中！"
    print_info "建议等待5分钟后执行以下命令检查："
    print_info "find ${MODEL_SAVE_DIR} -name '*${QUANTIZE_TYPE}*' | wc -l"
fi

# 步骤10：退出虚拟环境
deactivate
print_info "✅ 脚本执行完成，已退出虚拟环境"