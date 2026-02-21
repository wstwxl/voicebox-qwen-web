# Voicebox Qwen Web UI

基于 **Qwen3-TTS** 模型以及 **Whisper-Base** 打造的纯本地、开箱即用的前端语音克隆与零样本合成工作室。

## ✨ 特性 (Features)
1. **纯净高效的 Web UI 面板**：基于原生的 HTML/JS 前端与 FastAPI 后端，跨平台支持，没有复杂的 React 或 Vue 依赖。
2. **极速音色提取及无感切换**：在创建新音色时（仅需 2 到 10 秒源音频），系统会在后台为您一秒内并发抽取并持久化基于 `1.7B` 和 `0.6B` 双模型的权重特征缓存！这意味着您在进行 TTS 推理时可以在不同量级模型中进行 **0 延迟的热切换**验证效果！
3. **原生无损音频提纯：** 我们在浏览器内存里手工手写了 `16-bit PCM WAV` 的分离重构解码器。无论你在面板里麦克风直录、系统音频直录，还是随便上传奇形怪状的录音件，都会在游览器通过硬件级无损解码被转化成极其纯净的标准流，抛弃对底层 ffmpeg 的依赖环境污染，实现真正的开箱免折腾。
4. **Whisper 听写内联**：自带 OpenAI 的 Whisper base 翻译能力，创建时可为您光速自动抽写出“发音参考文本”，彻底解放手动打字的劳力！支持 10 种主干语言强锁定识别或 Auto 探测。
5. **TTS 硬控语种**：您可以在推理生成界面指定 Qwen 生成目标的强制语系和重音方案（如锁定英语口音来强读中文拼音等），同时支持输入 Delivery Instruction。
6. **记忆时空下载：** 所有曾经合成的成品，除了拥有无损云端保存并在右侧附带列表外。支持进行无痛一键批量转 ZIP 并带有时空排序号的统筹打包下载，远离浏览器的强制中断墙！

## ⚙️ 环境安装 (Installation)

由于此项目依赖于现代化的深度学习环境（PyTorch + CUDA），请确保你的独立显卡显存至少在 **6GB 以上 (推荐 RTX系列 8G 或以上)**。

### 第一步：克隆仓库
```bash
git clone https://github.com/wstwxl/voicebox-qwen-web.git
cd voicebox-qwen-web
```

### 第二步：部署环境
为您提供了两种恢复依赖的方式，我们强烈推荐使用 **Conda**。

**方式 A: (推荐) 通过 Conda Environment.yml 一键复刻**
```bash
conda env create -f environment.yml
conda activate voicebox
```

**方式 B: 使用 pip 安装**
对于已经有 Python 3.10+ 原生环境的用户：
```bash
pip install -r requirements.txt
```
*(注意：请确保您手动配置好支持您 CUDA 版本的 `torch` 和 `torchaudio`，以获得极速 GPU 推理，否则会因跑在 CPU 上而变得奇慢无比)*

### 第三步：自动下载底层大模型
在此项目运行前，我们需要提前将高达 4 个 GB 的 LLM 预训练模型储备到本地 HF 缓存中。我们提供了一个极其简单的自动化对流脚本。
请确保全程开启无障碍访问 Hugging Face 的网络通道。

执行下面这行指令即可全自动下载对应的 Qwen3-TTS(1.7B & 0.6B) 以及 Whisper 模型文件：
```bash
python download_models.py
```
*(如果你有部分模型了或者是部分模型下载到中途失败，重新运行这个脚本它会自动从断点处续传，非常贴心)*

---

## 🚀 启动与使用 (Usage)

在环境激活的状态下，在项目的根目录执行主服务器启动令：

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 9090
```
或在 Windows 环境下直接双击根目录为您制作好的集成化脚本：
👉 **双击运行 `run_app.bat`** 即可自动激活环境拉起服务器！

当控制台提示 `Uvicorn running on http://127.0.0.1:9090`，请在您的浏览器 (Edge / Chrome / Safari) 打开此地址畅聊创作！

---
## 目录结构
```
📦 voicebox-qwen-web
┣ 📂 backend/               # FastAPI 路由逻辑、SQLite管理以及调用模型接口核心
┣ 📂 static/                # 极致轻量级前端（纯手工 HTML+TailwindCSS+原生 JS）
┣ 📂 data/                  # （由系统动态生成保管）所有历史听写原件及合成作品数据库
┣ 📜 environment.yml        # Conda 运行环境指纹备份
┣ 📜 requirements.txt       # Pip 运行环境指纹备份
┣ 📜 download_models.py     # HF 依赖模型极速化预下载执行脚本
┗ 📜 run_app.bat            # Windows 懒人启动批处理
```

*Have fun generating clones!*
