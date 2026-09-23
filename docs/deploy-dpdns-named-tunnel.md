# astkstudio.dpdns.org 长期部署

## 目标架构

```text
astkstudio.dpdns.org     -> Cloudflare Worker（静态前端 + /api 代理）
api.astkstudio.dpdns.org -> Cloudflare Named Tunnel -> http://127.0.0.1:4173
```

不要把 Worker 的根域名填入 `ASTK_BACKEND_URL`，否则 `/api/*` 会递归代理到 Worker 自己。

## 1. Cloudflare Zero Trust

Cloudflare 当前对首次启用 Zero Trust 免费版要求绑定受支持的支付方式。免费版标价为 0 美元/月，但页面仍会要求支付方式，并包含超出免费额度后计费的授权。中国银联卡通常不在该页面列出的支持范围内。不要提交他人的卡，也不要把卡号、有效期或安全码发到聊天中。

可选路径：

- 如果你有可用的 Visa/Mastercard，或自己的 PayPal/Google Pay 可完成验证，可在 Cloudflare 页面由你本人完成最终确认。
- 如果没有任何受支持的支付方式，不要继续结算；改用下面的 VPS/学校反向代理方案。Cloudflare Quick Tunnel 不能提供这个固定域名的长期后端，并且旧临时隧道已经被 Cloudflare 撤销。

1. 登录 Cloudflare，打开 **Zero Trust**。首次使用时先完成账户初始化。
2. 进入 **Networks -> Tunnels**，创建一个 Named Tunnel，例如 `astk-linux`。
3. 添加 Public Hostname：
   - Subdomain：`api`
   - Domain：`astkstudio.dpdns.org`
   - Service：`HTTP://127.0.0.1:4173`
4. 在 Tunnel 的安装页面复制 Linux 命令中的 Token。Token 只保存到 Linux，不要提交到 Git 或发到聊天中。

如果 Cloudflare 要求先创建 Zero Trust team domain，按页面完成初始化即可；这只需做一次。

## 无支付方式时的替代方案

### 方案 A：学校或单位反向代理

让网络管理员把 `api.astkstudio.dpdns.org`（或另一个固定 HTTPS 子域名）反向代理到 Linux 的 `127.0.0.1:4173`，并允许长连接、大文件上传和最长 6 小时响应。然后直接把该地址配置到 Worker 的 `ASTK_BACKEND_URL`，不需要 Cloudflare Zero Trust。

### 方案 B：租用一台有公网 HTTPS 的 VPS

在 VPS 上运行 Nginx/Caddy，VPS 通过 SSH 反向隧道连接校内 Linux：

```bash
ssh -N -R 127.0.0.1:4173:127.0.0.1:4173 user@VPS
```

VPS 的 HTTPS 反向代理再转发到 VPS 的 `127.0.0.1:4173`。这条路线不依赖 Cloudflare Zero Trust，但 VPS 会产生服务商费用。

## 2. Linux 后端

在 Linux 上执行：

```bash
cd ~/astk-web
mkdir -p ~/.config/astk
chmod 700 ~/.config/astk
printf '%s\n' '粘贴刚刚复制的 Tunnel Token' > ~/.config/astk/cloudflare-tunnel.token
chmod 600 ~/.config/astk/cloudflare-tunnel.token

export ASTK_PUBLIC_BACKEND_URL=https://api.astkstudio.dpdns.org
bash scripts/start-cloudflare-named-tunnel.sh
```

启动脚本会检查 Tunnel 是否注册，并检查：

```bash
curl -fsS https://api.astkstudio.dpdns.org/api/health
```

长期运行使用用户级 systemd 服务。发布目录通过稳定软链接切换：

```bash
ln -sfn ~/astk-web/releases/<commit> ~/astk-web/current
mkdir -p ~/.config/systemd/user
cp deploy/astk-studio.service ~/.config/systemd/user/
cp deploy/astk-cloudflare-tunnel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now astk-studio.service astk-cloudflare-tunnel.service
```

确认 `loginctl show-user "$USER" -p Linger` 为 `Linger=yes`，这样注销 SSH 或电脑关闭后，Linux 上的服务仍会继续运行并在 Linux 重启后恢复。

## 3. Worker 变量

在 Worker `astk-studio` 的 **Settings -> Variables and Secrets -> Production** 中添加：

```text
名称：ASTK_BACKEND_URL
值：https://api.astkstudio.dpdns.org
类型：变量（不是 Secret）
```

保存并重新部署后，根域名的 API 请求应转发到 Linux。

## 4. 验收

```bash
curl -fsS https://api.astkstudio.dpdns.org/api/health
curl -fsS https://astkstudio.dpdns.org/api/health
```

两个地址都应返回 `status: ok`。第二个地址还应显示队列 `max_concurrent_jobs: 10`。
然后从浏览器提交一个小型 `quant.zip` + `samples.csv`，确认任务可以进入 `completed`，并能下载 JSON 和 ZIP 报告。

## 当前状态

- `astkstudio.dpdns.org` 已绑定到 Worker，前端返回 HTTP 200。
- `api.astkstudio.dpdns.org` 已通过名为 `astk-linux` 的 Named Tunnel 指向 `127.0.0.1:4173`。
- Linux 后端和 Named Tunnel 均由用户级 systemd 管理，并已启用开机恢复。
- 后端发布目录使用 `/home/yushiye/astk-web/current` 软链接，数据保存在共享目录 `/home/yushiye/astk-web/data`。
- 当前限制为 10 个并发任务，任务与未完成上传均保留 24 小时。
- 2026-09-23 已用 22.8 MB 真实输入完成公网分块上传、七类 AS 分析及报告 ZIP 完整性验证。
- 旧 Quick Tunnel 已失效并不再用于生产环境。
