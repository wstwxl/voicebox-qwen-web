#!/bin/bash
# 确保在脚本所在目录执行
cd "$(dirname "$0")"

echo "==================================================="
echo "    启动 Voicebox Qwen Web UI (AutoDL / Ubuntu 专用)"
echo "    正在监听端口 6006..."
echo "==================================================="

# 执行启动指令并监听全部外部 IP 映射至 6006 端口以兼容 AutoDL 内网穿透
python -m uvicorn backend.main:app --host 0.0.0.0 --port 6006
