#!/bin/bash
# =========================================================
#  Voicebox Qwen Web UI - 首次环境配置脚本
#  适用于：个人 Ubuntu 主机 (可访问外网)
# =========================================================
set -e  # 遇到错误立即停止

echo "==================================================="
echo "    🎙️ Voicebox Qwen Web UI - 环境配置脚本"
echo "    适配：Ubuntu 20.04 个人主机 + Miniconda"
echo "==================================================="

# 确保所有相对路径相对脚本所在目录执行
cd "$(dirname "$0")"

# Step 1: 安装系统依赖
echo -e "\n[1/6] 安装系统依赖 (sox 音频处理工具)..."
if command -v sox &>/dev/null; then
    echo ">> sox 已安装，跳过。"
else
    echo ">> 安装 sox (需要 sudo 权限)..."
    sudo apt-get install -y sox libsox-fmt-all
    echo ">> sox 安装完成！"
fi

# Step 2: 创建 Conda 环境
echo -e "\n[2/6] 创建 Conda 环境 (voicebox / Python 3.12)..."
if conda info --envs | grep -q "voicebox"; then
    echo ">> Conda 环境 'voicebox' 已存在，跳过创建。"
else
    conda create -n voicebox python=3.12 -y
    echo ">> Conda 环境 'voicebox' 创建完成！"
fi

# 激活环境并验证
echo -e "\n>> 激活 voicebox 环境..."
eval "$(conda shell.bash hook)"
conda activate voicebox

# 验证 pip 指向 conda 环境
PIP_PATH=$(which pip)
if [[ "$PIP_PATH" != *"envs/voicebox"* ]]; then
    echo "❌ 错误: pip 未指向 voicebox 环境 ($PIP_PATH)，请检查 conda 配置！"
    exit 1
fi
echo ">> 已验证 pip 指向: $PIP_PATH"

# Step 3: 安装 FlashAttention-2 预编译包 (manylinux2014 兼容 Ubuntu 20.04+)
echo -e "\n[3/6] 安装预编译版 FlashAttention-2 核心算子..."
pip uninstall flash-attn -y >/dev/null 2>&1
# Python 3.12 / torch 2.5 / CUDA 12.8 (向下兼容cu124) / manylinux2014 (兼容 GLIBC 2.17+)
# --no-deps 避免 wheel 拉入不兼容的 torch 版本
pip install --no-deps https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.7.2/flash_attn-2.6.3+cu128torch2.5-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl
if [ $? -ne 0 ]; then
    echo ">> [警告] FlashAttention 预编译包安装失败，但不影响基本功能。"
else
    echo ">> FlashAttention-2 安装成功！"
fi

# Step 4: 安装 Python 依赖
echo -e "\n[4/6] 安装 Python 依赖..."
pip install -r requirements.txt

# Step 5: 安装 Qwen3-TTS
echo -e "\n[5/6] 从 GitHub 安装 Qwen3-TTS 驱动..."
pip install git+https://github.com/QwenLM/Qwen3-TTS.git

# Step 6: 下载预训练模型
echo -e "\n[6/6] 下载预训练模型 (约 4GB)..."
python download_models.py

echo -e "\n==================================================="
echo "    ✅ 环境配置全部完成！"
echo "    日常启动请运行：./run.sh"
echo "==================================================="
