# 🎙️ Voicebox Qwen Web UI — 个人主机版

基于 **Qwen3-TTS** 大语言模型 + **Whisper-Base** 语音识别引擎打造的**零样本声音克隆与实时语音合成工作站**。
本分支 (`ubuntu20.04`) 适配 **Ubuntu 20.04 个人主机**部署，支持多用户公网访问。

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 🎤 **十秒音色克隆** | 仅需 10～20 秒人声录音，即可提取声纹特征张量 |
| ⚡ **流式秒发播报** | SSE 流式合成，长文本"边生成边播放" |
| 🧠 **双模型热切换** | 1.7B 满血模型（支持情感指令）+ 0.6B 极速模型 |
| 📝 **语音听写** | 内置 Whisper 语音识别，对着麦克风说话自动转文本 |
| 🔥 **FlashAttention-2** | C++ 算子级显存优化，大幅降低推理显存峰值 |
| 📱 **移动端适配** | 响应式 UI，手机浏览器也能流畅操作 |
| 🎫 **多用户排队系统** | 个人"排队票"机制，每个用户精确看到自己的排位 |
| 📊 **服务器监控仪表盘** | 终端实时显示设备上下线、任务生命周期、显存占用 |
| 🧹 **启动自动清理** | 自动清除临时文件和孤儿音色数据 |

---

## 🚀 部署指南（Ubuntu 20.04 + Miniconda）

### 前置要求

- Ubuntu 20.04 系统
- NVIDIA GPU（推荐 RTX 3060 12GB 及以上）
- 已安装 NVIDIA 驱动 + CUDA 12.x
- 已安装 [Miniconda](https://docs.conda.io/en/latest/miniconda.html)
- 可访问外网

### 第一步：克隆项目

```bash
git clone -b ubuntu20.04 https://github.com/wstwxl/voicebox-qwen-web.git
cd voicebox-qwen-web
```

### 第二步：首次环境配置（仅需运行一次）

```bash
chmod +x setup.sh
./setup.sh
```

此脚本会自动完成：
- 创建 Conda 环境 `voicebox`（Python 3.12）
- 安装预编译版 FlashAttention-2
- 安装所有 Python 依赖和 Qwen3-TTS
- 下载约 4GB 的预训练模型

首次运行约需 10～15 分钟。

### 第三步：日常启动

```bash
chmod +x run.sh
./run.sh
```

看到以下输出说明服务已就绪：

```
=======================================================
    🎙️  Voicebox Qwen Web UI (个人主机版)
    📡 监听端口: 6006
    🎮 GPU: NVIDIA GeForce RTX XXXX | 显存: XXG
    📦 已有音色: 3 个 | 历史记录: 12 条
    🧹 启动清理: 磁盘很干净，无需清理 ✨
=======================================================
```

### 第四步：访问网页

- 本机访问：`http://localhost:6006`
- 局域网访问：`http://你的IP:6006`
- 公网访问：配置端口转发或反向代理后即可通过域名访问

---

## 📂 目录结构

```
📦 voicebox-qwen-web/
┣ 📂 backend/               # FastAPI 后端（路由、数据库、GPU 队列、模型调用）
┣ 📂 static/                # 前端（纯 HTML + TailwindCSS + 原生 JS）
┣ 📂 data/                  # 运行时数据目录（自动生成）
┃  ┣ 📂 profiles/           #   音色仓库
┃  ┣ 📂 history/            #   生成历史（WAV 音频）
┃  ┣ 📂 temp/               #   临时文件（启动时自动清理）
┃  ┗ 📜 voicebox_local.db   #   SQLite 数据库
┣ 📜 environment.yml        # Conda 环境配置
┣ 📜 requirements.txt       # Pip 依赖清单
┣ 📜 download_models.py     # 模型下载脚本
┣ 📜 setup.sh               # 首次环境配置脚本
┗ 📜 run.sh                 # 日常启动脚本
```

---

## 🔧 终端监控

启动后，终端实时显示关键事件（中文输出，无 uvicorn 刷屏）：

```
📱 [设备上线] 192.168.1.100 | 当前在线设备: 1 台
🔥 [任务开始] 流式合成     | 来自 192.168.1.100 | 队列: 1 个任务
✅ [任务完成] 流式合成     | 来自 192.168.1.100 | 耗时 15.2秒 | 📊 显存 8.2/12.0GB
💤 [服务器空闲] 当前无任务运行，可安全关机
```

---

*Have fun generating clones! 🎉*
