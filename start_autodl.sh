#!/bin/bash
echo "==================================================="
echo "    Qwen3-TTS Web UI - AutoDL / Ubuntu 启动脚本"
echo "    Powered by FastAPI & Qwen3-TTS"
echo "==================================================="

echo "[1] 安装基本依赖 (如果已安装会自动跳过)..."
# In AutoDL's 12.4 PyTorch image, just run this:
pip install -r requirements.txt

echo "[2] 尝试下载模型 (如果已下载会自动保留)..."
python download_models.py

echo "[3] 启动 FastAPI 服务 (跑在开放的 6006 端口上)..."
echo "[INFO] 在 AutoDL 控制台找到 【自定义服务】，点击访问！"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 6006
