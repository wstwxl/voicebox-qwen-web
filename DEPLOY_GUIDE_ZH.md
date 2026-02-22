# Voicebox Qwen Web UI - 公网部署与高级网络调优指南

本指南将教你如何将部署在个人主机（如家用 Ubuntu）上的 Voicebox Qwen Web UI 项目发布到互联网上。

为了解决国内外网络环境的延迟与 Web 设备必须使用 HTTPS (安全上下文) 的问题，本文档详细记录了一套基于**“Cloudflare 接管 DNS + SakuraFrp 国内极速穿透 + 手动颁发正式全站 SSL 证书”**的终极极客解决方案。

---

## 🎯 为什么需要这套复杂的架构？
1. **Cloudflare 官方 Tunnels（方案 A 废除原因）**：虽然 CF 自带免费内网穿透与全球 SSL 证书，但其针对国内免费用户未开放大陆节点。国内用户访问会被强制绕路至美国西海岸机房（如 `sjc06` 圣何塞），物理延迟高达 300ms+ 且疯狂丢包，直接导致语音播放卡顿、后台服务反馈严重滞后。
2. **SakuraFrp / 樱花穿透（当前选择）**：国内出色的内网穿透服务商。通过选择其提供的“新加坡”或“国内/香港”节点，网络延迟可骤降至 50ms 左右，彻底解决语音卡顿和后台响应慢的问题。
3. **WebRTC SSL 证书限制**：现代浏览器为了保护隐私，一旦发现你没有使用真实合法的 `https://` 加密协议，将直接屏蔽（设为 undefined）麦克风的调用权限。如果使用未受认证的“自签发伪造证书”，电脑端浏览器则会被 HSTS（HTTP 严格传输安全）机制死死拦截。
4. **终极方案目标**：我们既要国内穿透节点的“极速低延迟”，又要 Cloudflare 的“秒级解析”，还要“完美不报错的小绿锁证书”来解禁麦克风。

---

## 🚀 终极部署全流程说明

### 步骤 1：让 Cloudflare 管理你的独立域名
1. 准备一个个人域名（如 `amorwest.cn`）。
2. 在 Cloudflare 注册账号，添加该域名，并前往你原域名服务商（如阿里云/腾讯云），将其 DNS 域名服务器修改为 Cloudflare 指定的服务器。
3. 等待 Cloudflare 面板显示域名状态为 **Active（已激活）**。

### 步骤 2：在 SakuraFrp 面板创建建站隧道
1. 注册并登录 [SakuraFrp (樱花穿透)](https://www.natfrp.com)。
2. 进入“服务 -> 隧道列表”，点击**“+ 创建隧道”**。
3. 核心配置：
   - **节点类型**：选择离你较近的亚洲节点（如新加坡或香港节点，免备案且低延迟）。
   - **隧道类型**：必须选择 **`HTTPS 建站隧道`**。
   - **本地 IP**：填 `127.0.0.1`。
   - **本地端口**：填 `6006`（本项目的后端端口）。
   - **绑定域名**：填你的域名（例如 `amorwest.cn` 或 `api.amorwest.cn`）。
   - **创建 HTTP 重定向**：建议选 `301` 或 `307` 强制重定向（这样当用户在手机端手打 `http://` 时，会直接跳转被保护的 HTTPS 里，确保麦克风可用）。
   - **本地端访问协议**：**这一点非常关键！**请确保 SakuraFrp 后台里该隧道的“隧道选项/访问协议”设置为了与你 Uvicorn 后台相同的协议（默认为纯 `HTTP` 访问 6006 端口）。
   **🚨 解决 "Invalid HTTP request received" 报错：**
   如果你在面板中强行选择了 `HTTPS` 的端到端加密，樱花的客户端就会对你本地纯纯的 HTTP FastAPI 服务强行发送加密握手。此时 Uvicorn 解不开包，便会报出这个错误。
   - **正确的作法**： SakuraFrp 控制台上“自动 HTTPS”点**禁用**；但是**隧道必须仍然是建立在你的“内网纯 HTTP 6006”端口上。**樱花的节点集群会负责接收外网用户的安全 HTTPS 流量，并把它解密成 HTTP 灌入你家里的电脑里。只要项目根目录存放了对应的域名 `crt` 和 `key` 证书文件（见步骤4），穿透核心会自动读取并给访客展示绿锁验证。
4. 保存后，记录分配给你的 CNAME 网址（如 `xxx.frp-can.com`）和用于唤起隧道的**启动指令**（如 `-f uxwwjcx...`）。

### 步骤 3：在 Cloudflare 添加 CNAME 解析（灰云极为关键！）
1. 回到 Cloudflare 的 **DNS -> Records** 面板。
2. 添加一条记录（Add record）：
   - 类型：`CNAME`
   - 名称：填 `@`（或你绑定的前缀子域名）。
   - 目标：粘贴刚刚分配的樱花 CNAME 网址。
3. 🚨 **绝对避坑重点**：
   **请务必将后面那朵橙色的云朵图标点一下，让它变成纯灰色的 `仅 DNS (DNS only)`**！！若不关掉橙色云代理功能，你的流量依然会被 Cloudflare 劫持到美国跑一圈，花钱买的新加坡低延迟将全盘作废。

### 步骤 4：通过 acme.sh 签发终极合法 SSL 证书
因为我们使用内网穿透且关闭了 HTTP (80 端口) 入口，常规的自动证书方案经常失败，导致系统下发“伪造证书”，从而触发浏览器恐怖的 HSTS “不安全连接”红色拦截页。
在此我们利用 DNS 验证挑战，在 Ubuntu 手工拿下一张 90 天有效期的合法证书。

在 Ubuntu 终端执行：
```bash
# 1. 安装自动发证神器 acme.sh
curl -s https://get.acme.sh | sh
source ~/.bashrc

# 2. 注册并在机构申请证书（ZeroSSL 或 Let's Encrypt）
~/.acme.sh/acme.sh --register-account -m 你的邮箱@example.com
~/.acme.sh/acme.sh --issue -d amorwest.cn --dns --yes-I-know-dns-manual-mode-enough-go-ahead-please
```
此时，安全机构会临时给你一串**密码签（TXT value）**，以证明你是这个域名的持有人。你需要：
1. 立刻去 Cloudflare 添加一条 **`TXT`** 记录。
2. 名称填写要求的前缀：`_acme-challenge`。
3. 目标（Content）填写那一长串乱码密码单。

**完成验证并提取最终证书：**
保存后，回来执行续签命令进行最终查验：
```bash
~/.acme.sh/acme.sh --renew -d amorwest.cn --yes-I-know-dns-manual-mode-enough-go-ahead-please
```
见到 `Success` 后，代表合法的证书文件已经生成！
将它们拷贝至项目的根目录下（因为后续我们需要将它们与 frpc 放在一起）：
```bash
cp ~/.acme.sh/xxxx_ecc/fullchain.cer /path/to/voice_project/amorwest.cn.crt
cp ~/.acme.sh/xxxx_ecc/ amorwest.cn.key /path/to/voice_project/amorwest.cn.key
```
*(注意：请用你的实际域名重命名这两个文件，即 `你的域名.crt` 和 `你的域名.key`)*

### 步骤 5：启动本项目的服务与极速隧道
进入你存放代码和 `frpc` 二进制文件的项目主目录。

**终端窗口 1：启动 AI 项目服务**
```bash
./run.sh
```
确保显示正在监听 `Uvicorn running on http://0.0.0.0:6006`。

**终端窗口 2：启动 SakuraFrp 隧道**
前往 SakuraFrp 后台获取针对 `Linux amd64` 的最新客户端并赋权后，启动通道：
```bash
chmod +x frpc
./frpc -f 你的专属密钥参数
```
当终端输出 `已为 xxxx 加载证书 [CN = amorwest.cn...]` 以及 `隧道启动成功` 时。

**🎉 恭喜你，大功告成！**
此时用世界上任意角落的手机或电脑访问 `https://你的域名`。由于走的是极速通道且挂载了完全合法的前端证书，网络延迟已经骤降至两位数，且浏览器没有任何警报提示，麦克风将绝对完美地被授权收音工作！
