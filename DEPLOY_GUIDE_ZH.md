# Voicebox Qwen Web UI - 公网部署指南

本指南将教你如何将部署在个人主机（如家用 Ubuntu）上的 Voicebox Qwen Web UI 项目，通过**内网穿透技术**安全地发布到互联网上，让全世界的人都能通过你自己的域名访问。

## 🎯 为什么需要内网穿透？
如果你只有一台个人家庭电脑（有强大的显卡）和一个独立域名，但**没有公网 IP** 和云服务器，你无法直接将域名解析到你家里的路由器。
此时，使用 **Cloudflare Tunnels** 是最佳的免费解决方案。它可以建立一条从你个人电脑直达 Cloudflare 边缘节点的加密隧道，并且**自带 HTTPS 加密保护**。

## 📋 前提条件
1. 已经成功在本机（如 Ubuntu 20.04）上依据 `setup.sh` 配置好环境。
2. 运行 `./run.sh` 能够成功启动服务并在本地 `http://127.0.0.1:6006` 正常访问。
3. 拥有一个顶级域名（例如在阿里云、腾讯云购买的域名，如 `amorwest.cn`）。
4. 注册一个免费的 [Cloudflare 账号](https://dash.cloudflare.com/sign-up)。

---

## 🚀 部署步骤

### 步骤 1：将域名的 DNS 解析交由 Cloudflare 接管
1. 登录 Cloudflare 后台，点击 **"Add a Site"** 并输入你的域名（如 `amorwest.cn`）。
2. 选择 **Free（免费）套餐**。
3. Cloudflare 会扫描域名并为你分配两个**专属 Nameserver (NS) 服务器**（例如 `xxx.ns.cloudflare.com`）。复制它们。
4. 登录你购买域名的服务商控制台（如阿里云），进入域名的 **DNS 管理 / 修改 DNS 服务器** 设置页面。
5. 将原有的 DNS 服务器删除，替换为刚刚复制的两个 Cloudflare NS 服务器。
6. 等待生效（通常几分钟），直到 Cloudflare 页面显示该域名状态为 **Active（已激活）**。

### 步骤 2：在本地服务器安装 Cloudflared 客户端
在运行该模型后端服务的 Ubuntu 终端中执行：
```bash
# 下载并安装 cloudflared
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb
```

### 步骤 3：登录授权并创建隧道
1. **登录账号**：在终端输入 `cloudflared tunnel login`。
   终端会输出一段验证 URL，复制并在浏览器中打开，选择你刚接入的域名进行授权。
2. **创建隧道**：在终端输入 `cloudflared tunnel create voicebox`。
   (其中 `voicebox` 是隧道的名字，可自定义)
3. **绑定域名**：在终端输入 `cloudflared tunnel route dns voicebox amorwest.cn`。
   (如果你想用子域名访问，可以改为 `api.amorwest.cn` 或 `tts.amorwest.cn`)

### 步骤 4：启动项目与隧道！
至此所有配置结束，请开**两个终端窗口**：
1. **终端A (启动项目)**：运行你的服务 `./run.sh`
2. **终端B (启动隧道转发)**：将本地的 6006 端口流量转发给这个隧道。
   ```bash
   cloudflared tunnel run --url http://127.0.0.1:6006 voicebox
   ```
大功告成！现在所有人都可以通过你的域名（如 `https://amorwest.cn`）访问你在本地主机的应用了！

---

## 💡 踩坑与常见问题 (FAQ)

### 1. 绑定域名时报错 `code: 1003 ... An A, AAAA, or CNAME record ... already exists.`
**原因**：这通常是因为你之前用该域名做过其他项目（例如 GitHub Pages），DNS 设置中仍然遗留有旧的 A 记录或 CNAME 记录。同一个域名节点不允许同时配置多种冲突的路由。
**解决**：登录 Cloudflare 后台 -> DNS -> Records，将冲突域名 (`amorwest.cn`) 的旧 A 记录或 CNAME 记录**全部删除**。然后重新运行绑定域名的命令即可。

### 2. 网页能打开，但点击“使用麦克风”报错 `Cannot read properties of undefined (reading 'getUserMedia')`
**原因**：这是浏览器的安全限制。现代浏览器（如 Chrome, Edge）为了防范隐私泄露，**严禁在非 HTTPS（即 `http://`）环境下调用麦克风或摄像头等隐私设备**。如果你用 HTTP 访问，浏览器直接会把媒体接口屏蔽掉。
**解决**：
由于 Cloudflare Tunnels 已经为你自动配置了免费的 SSL 证书：
1. 在浏览器地址栏，强制手动输入 **`https://`** 开头的完整网址访问即可。
2. **⭐️ 强烈推荐的最佳实践**：登录 Cloudflare 后台，进入 **SSL/TLS -> Edge Certificates** 栏目，找到 **"Always Use HTTPS"** 并将开关**打开**。这样无论用户输入什么，都会被强制重定向到安全的 HTTPS 环境中，彻底杜绝此类错误。
