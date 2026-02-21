#!/bin/bash
echo "==================================================="
echo "    Qwen3-TTS Web UI - AutoDL 专属环境配置与启动脚本"
echo "    Powered by FastAPI & Qwen3-TTS"
echo "==================================================="

# 确保所有相对路径相对脚本所在目录执行
cd "$(dirname "$0")"

echo -e "\n[0/5] 启动 AutoDL 学术加速 (打通 GitHub 与境外网络通道)..."
# 注意：该指令只在 AutoDL 环境有效
if [ -f "/etc/network_turbo" ]; then
    source /etc/network_turbo
    echo ">> 学术加速已强制开启，已为您破除网络限制！"
else
    echo ">> 未检测到 AutoDL 的 /etc/network_turbo 引擎，跳过网络加速。"
fi

echo -e "\n[1/5] 安装预编译版 FlashAttention-2 核心算子 (跳过所有漫长源码编译)..."
# 卸载可能卡死或编译失败的旧包
pip uninstall flash-attn -y >/dev/null 2>&1
# 这里直接指定了 Python 3.12 / torch 2.5.1 / CUDA 12.4 的预编译轮子，如果您环境变了请自行寻找合适的版本
pip install https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.5.4/flash_attn-2.8.3+cu124torch2.5-cp312-cp312-linux_x86_64.whl
if [ $? -ne 0 ]; then
    echo ">> [警告] 预编译包下载失败。脚本将继续执行，您的 4090 不带 FlashAttention 依然可飞速生成！"
else
    echo ">> FlashAttention-2 已完美嵌入，您的 RTX 4090 显卡已全速解锁！"
fi

echo -e "\n[2/5] 利用阿里和清华源安装系统基本业务依赖..."
# 这里刻意把 extra-index-url 放在后面，确保如果某些库报错还有原生的 PyTorch 源兜底
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple --extra-index-url https://download.pytorch.org/whl/cu124

echo -e "\n[3/5] 从 GitHub 源码全速挂载最新 Qwen3-TTS 驱动..."
pip install git+https://github.com/QwenLM/Qwen3-TTS.git

echo -e "\n[4/5] 利用开启的学术加速，极速拉取 4GB 的预训练模型..."
# 此时 network_turbo 代理已生效，可直接通过官方渠道全量极速下载
python download_models.py

echo -e "\n[5/5] ✨ 恭喜！全环境就位，启动 FastAPI 引擎！ ✨"
echo "==================================================="
echo "|  [操作指南]: 请在您的 AutoDL 控制台找到 【自定义服务】 按钮 |"
echo "|  点击它，即可在浏览器中体验您的极速 TTS 工作室！            |"
echo "==================================================="

# 将 uvicorn 的服务映射到 6006 端口，以配合 AutoDL 的公网隧道
python -m uvicorn backend.main:app --host 0.0.0.0 --port 6006
