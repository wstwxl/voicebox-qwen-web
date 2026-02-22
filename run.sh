#!/bin/bash
# =========================================================
#  Voicebox Qwen Web UI - 日常启动脚本
#  适用于：个人 Ubuntu 主机
# =========================================================

# 确保在脚本所在目录执行
cd "$(dirname "$0")"

# 激活 Conda 环境
eval "$(conda shell.bash hook)"
conda activate voicebox

echo "==================================================="
echo "    🎙️ Voicebox Qwen Web UI"
echo "    正在启动服务，监听端口 6006..."
echo "==================================================="

# 注入国内 HuggingFace 镜像源，彻底摆脱 VPN 依赖和连通性报错
export HF_ENDPOINT=https://hf-mirror.com

# 启动 FastAPI 服务 (挂载手工获取的全站 SSL 证书，解析加密的 HTTPS 流量)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 6006 --ssl-keyfile=../amorwest.cn.key --ssl-certfile=../amorwest.cn.crt --no-access-log
