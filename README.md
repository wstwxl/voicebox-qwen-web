# Voicebox Qwen Web UI

基于 **Qwen3-TTS** 模型以及 **Whisper-Base** 打造的纯本地、极速响应的前端语音克隆与零样本合成工作室。
支持 FlashAttention-2 满血加速与流式输出（Streaming），体验极尽丝滑的秒级播报响应。

## ✨ 特性 (Features)
1. **开箱即用的 Web UI 面板**：基于原生的 HTML/JS 前端与 FastAPI 后端，跨平台支持，拒绝复杂的框架臃肿。
2. **零延迟流式秒发播报**：借助流式传输（SSE）加上 `⚡ 流式合成` 的支持，让近百字长文的时间达到“首字即出”的即视感。
3. **显存深层压榨与极致生成**：集成了底层 C++ 算子级 `FlashAttention-2` 的显存管理优化，有效把原来 12GB 的峰值显存门槛砸到极低。
4. **极速音色提取及无感切换**：在创建新音色时（仅需 10 到 20 秒源音频），提取 1.7B 模型及 0.6B 特征只需瞬间，并在不同主存量级模型中进行 **0 延迟的热切换**验证！
5. **记忆时空下载：** 所有生成过的作品，都有单独存放的 `data/history` 管理，右侧控制面板实时附带列表与回放。

---

## ☁️ AutoDL 云服务器一键部署指南 (强烈推荐)
如果您为了告别本地显卡不足的困扰，并在 RTX 4090 或 3090 服务器上体验真正能投入生产的流式推理速度，本分支已为您预配置好了完美贴合 **AutoDL 镜像环境（PyTorch 2.5.x, Python 3.12, CUDA 12.4）** 的所有加速部署与防网络阻断功能！

### 1. 将项目部署在数据盘 (`autodl-tmp`)
在通过 JupyterLab 打开的终端（Terminal）内，**请务必将项目安装在高速且免费的 `/root/autodl-tmp/` 目录下**（不要下在系统盘 `/root/`！系统盘仅有几十 G 会塞爆）：

```bash
cd /root/autodl-tmp/
git clone -b ubuntu22.04 https://github.com/wstwxl/voicebox-qwen-web.git
cd voicebox-qwen-web
```

### 2. 执行自动化环境点火脚本
AutoDL 服务器因为安全隔离，很容易无法直连海外 GitHub 源码或是慢如蜗牛，且编译底层 C++ 算子插件（FlashAttention）更是费时费钱！
因此，在 `new_project` 的根目录下，我们打造了一个绕开所有暗坑的**一步登天部署脚本 `start_autodl.sh`**。

它里面为您执行了以下黑魔法：
- `source /etc/network_turbo`: 提前为您物理开启学术代理，加速海外安装环节防卡死。
- 不再本地编译，直接让您瞬间下载 Github 社区的 C++ `FlashAttention` 预编译轮子。
- 采用阿里源及 `hf-mirror` 作为全局镜像，从系统底层彻底解决 `[Errno 101] Network is unreachable` 的恶心报错！

**请直接赋予执行权限并启动这艘穿梭机：**

```bash
chmod +x start_autodl.sh
./start_autodl.sh
```

### 3. 打开网页，体验光速生成！
当您看到终端里最后两行显示：
```text
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:6006 ...
```
说明您的引擎已全速上线！此时直接回到 AutoDL 控制台页面，找到名为 **【自定义服务】** 的按钮。点击它，您就能畅游纯外网的网页流式播报体验馆了。

> **💡 如果您在本地 Windows 有克隆好的音色想移步服务器？**
只需在本地把咱们项目的 `new_project/data` 文件夹打个 `.zip` 包传到云端的 `voicebox-qwen-web/new_project/` 下，解压覆盖即可，所有角色满血复活！

---

## 💻 本地 Windows 部署 (如果您的电脑性能够强)

### 第一步：创建您的 Conda 分区引擎

```bash
conda env create -f environment.yml
conda activate voicebox
```

### 第二步：安装底层依赖
请通过阿里云提供的镜像加速您的搭建过程：
```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple
```

### 第三步：全自动下载大模型
为防止 HuggingFace 抽风，我们早已设定好了强力的防失联备用链路：
```bash
python download_models.py
```

### 第四步：双击懒人工具启动
一切妥当之后，👉 **双击运行项目里的 `run_app.bat`**。
您的浏览器将自动唤醒 `127.0.0.1:9090`，马上就可以使用您的强力独显去榨干 Qwen 推理引擎了！

---
## 目录结构
```
📦 voicebox-qwen-web
┣ 📂 backend/               # FastAPI 路由逻辑、SQLite管理以及调用模型接口核心
┣ 📂 static/                # 极致轻量级前端（纯手工 HTML+TailwindCSS+原生 JS）
┣ 📂 data/                  # （由系统动态生成保管）所有历史听写原件及合成作品数据库
┣ 📜 environment.yml        # Conda 运行环境指纹备份
┣ 📜 requirements.txt       # Pip 运行环境指纹备份 (自带 Ubuntu FlashAttention-2 编译引导)
┣ 📜 download_models.py     # HF 依赖模型极速化预下载执行脚本
┣ 📜 run_app.bat            # Windows 懒人启动批处理
┗ 📜 start_autodl.sh        # Ubuntu / AutoDL 一键全环境适配与自定义服务端口启动脚本
```

*Have fun generating clones!*
