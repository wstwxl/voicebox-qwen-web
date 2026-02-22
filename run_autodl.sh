#!/bin/bash
# 确保在脚本所在目录执行
cd "$(dirname "$0")"

echo -e "\n启动 AutoDL 学术加速 (打通 GitHub 与境外网络通道)..."
# 注意：该指令只在 AutoDL 环境有效
if [ -f "/etc/network_turbo" ]; then
    source /etc/network_turbo
    echo ">> 学术加速已强制开启，已为您破除网络限制！"
else
    echo ">> 未检测到 AutoDL 的 /etc/network_turbo 引擎，跳过网络加速。"
fi

echo "==================================================="
echo "    启动 Voicebox Qwen Web UI (AutoDL / Ubuntu 专用)"
echo "    正在监听端口 6006..."
echo "==================================================="

# 执行启动指令并监听全部外部 IP 映射至 6006 端口以兼容 AutoDL 内网穿透
python -m uvicorn backend.main:app --host 0.0.0.0 --port 6006 --no-access-log
