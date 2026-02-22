#!/bin/bash
# =========================================================
#  Voicebox Qwen Web UI - 首次环境配置脚本
#  适用于：个人 Ubuntu 主机 (可访问外网)
# =========================================================
echo "==================================================="
echo "    🎙️ Voicebox Qwen Web UI - 环境配置脚本"
echo "    适配：Ubuntu 20.04 个人主机 + Miniconda"
echo "==================================================="

# 确保所有相对路径相对脚本所在目录执行
cd "$(dirname "$0")"

# Step 1: 创建 Conda 环境
echo -e "\n[1/5] 创建 Conda 环境 (voicebox / Python 3.12)..."
if conda info --envs | grep -q "voicebox"; then
    echo ">> Conda 环境 'voicebox' 已存在，跳过创建。"
else
    conda create -n voicebox python=3.12 -y
    echo ">> Conda 环境 'voicebox' 创建完成！"
fi

# 激活环境
echo -e "\n>> 激活 voicebox 环境..."
eval "$(conda shell.bash hook)"
conda activate voicebox

# Step 2: 安装 FlashAttention-2 预编译包
echo -e "\n[2/5] 安装预编译版 FlashAttention-2 核心算子..."
pip uninstall flash-attn -y >/dev/null 2>&1
# Python 3.12 / torch 2.5.1 / CUDA 12.4 预编译轮子
pip install https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.5.4/flash_attn-2.8.3+cu124torch2.5-cp312-cp312-linux_x86_64.whl
if [ $? -ne 0 ]; then
    echo ">> [警告] FlashAttention 预编译包安装失败，但不影响基本功能。"
else
    echo ">> FlashAttention-2 安装成功！"
fi

# Step 3: 安装 Python 依赖
echo -e "\n[3/5] 安装 Python 依赖..."
pip install -r requirements.txt

# Step 4: 安装 Qwen3-TTS
echo -e "\n[4/5] 从 GitHub 安装 Qwen3-TTS 驱动..."
pip install git+https://github.com/QwenLM/Qwen3-TTS.git

# Step 5: 下载预训练模型
echo -e "\n[5/5] 下载预训练模型 (约 4GB)..."
python download_models.py

echo -e "\n==================================================="
echo "    ✅ 环境配置全部完成！"
echo "    日常启动请运行：./run.sh"
echo "==================================================="
