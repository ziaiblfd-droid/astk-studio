# 发布与计算部署方案

ASTK Studio 分为公开前端和计算后端两部分。固定前端使用 Streamlit Community
Cloud，计算后端运行在持续在线的 Linux 主机上。

## 架构约束

当前 `Dockerfile` 基于标准 Python 3.12，并从 PyPI 安装 `astk`。依赖中的
`pysam` 提供 `manylinux` 的 x86_64 与 ARM64 wheel，因此后端镜像可以在两类
架构上构建。生产部署仍建议至少 4 GB 内存；1 GB 实例需要额外 swap 并进行
真实任务压测。

| 方案 | CPU 架构 | 估算内存 | 结论 |
| --- | --- | --- | --- |
| Oracle `VM.Standard.E2.1.Micro` | x86_64 | 1 GB + swap | 可试，运行 ASTK 前必须压测内存 |
| Oracle `VM.Standard.A1.Flex` | ARM64 | 最多 12 GB | 可构建，需先做一次端到端验收 |
| 付费/试用通用 x86 VM | x86_64 | 4 GB 及以上 | 最稳妥，推荐生产使用 |
| 现有校内 x86 服务器 | x86_64 | 已满足 | 若有公网入口和最简反向代理可优先复用 |

## 固定后端部署

前提：

- Ubuntu 22.04/24.04 或兼容的 Linux（x86_64 或 ARM64）
- 已安装 Docker Engine 和 Compose plugin
- 已安装 Caddy（或改用 Nginx）
- 一个归你控制的域名，例如 `astk-api.example.com`
- 域名 A/AAAA 记录已经指向 VM 公网 IP
- 云安全组放行 TCP `80` 和 `443`
- 至少一份实际使用的参考注释 GTF，放在 `references/` 下

在仓库目录执行：

```bash
export ASTK_DOMAIN=astk-api.example.com
export ASTK_TLS_EMAIL=you@example.com
bash scripts/deploy-fixed-backend.sh
```

脚本会：

1. 启动只绑定 `127.0.0.1:4173` 的 ASTK Docker 服务。
2. 等待并检查 `/api/health`。
3. 生成 `Caddyfile`，用于自动申请 TLS 和反向代理。

脚本不会自动启动 Caddy，避免未经确认就修改系统服务。安装 Caddy 后执行：

```bash
sudo caddy run --config ./Caddyfile --adapter caddyfile
```

确认 HTTPS 正常后，将 Caddy 注册为 systemd 服务，或在部署平台使用其原生
HTTPS 入口。仓库中的 `deploy/nginx-astk.conf` 也可以替代 Caddy；它需要把
`${ASTK_DOMAIN}` 替换成实际域名。

## 验收

从外部网络执行：

```bash
ASTK_BACKEND_URL=https://astk-api.example.com bash scripts/verify-fixed-backend.sh
```

该脚本会检查健康接口、下载样本模板，并上传一个最小 ZIP/CSV 测试任务。
确认返回 `job_id` 后，再轮询：

```bash
curl -fsS https://astk-api.example.com/api/jobs/JOB_ID
```

任务完成后，从 Streamlit 页面或以下地址下载报告：

```text
https://astk-api.example.com/api/jobs/JOB_ID/download
```

## 数据与安全

公共部署至少应配置：

- HTTPS 和数据保留期限
- 单任务 CPU/内存限制
- 上传大小限制
- 身份认证或匿名配额
- 恶意文件扫描与日志审计
- 每日备份 `data/jobs` 中需要保留的结果

GitHub Pages 和 Streamlit Cloud 只承载界面，不接收 ASTK 计算任务。不要把
TryCloudflare 或 Localtunnel 临时地址写入长期配置；它们只适合一次性联调。

### Quick Tunnel 网络诊断

如果服务器日志出现端口 `7844` 的 QUIC/TCP pre-check 失败，说明网络策略阻断了
Cloudflare Tunnel 默认出站路径。先请网络管理员放行出站 `7844`；若只是临时联调，
可以尝试强制 HTTP/2：

```bash
bash scripts/start-public-tunnel-http2.sh
```

这只改变传输协议，不解决地址漂移和公共服务条款问题。得到固定域名后仍应切换到
Caddy/Nginx HTTPS 部署。

## 现有 x86 服务器迁移

如果继续使用当前 `yushiye@172.18.236.93`（`x86_64`、完整 Conda ASTK 环境），
优先补齐固定公网入口，而不是重建计算环境：

1. 为服务器申请可管理的域名和公网映射。
2. 只向公网开放 `443`，服务仍监听 `127.0.0.1:4173`。
3. 在域名侧配置 TLS，并由 Caddy/Nginx 反代。
4. 用 `scripts/verify-fixed-backend.sh` 通过 HTTPS 完成验收。
5. 在 Streamlit Secrets 中把 `ASTK_BACKEND_URL` 更新为固定 HTTPS 地址。

该服务器当前没有 `sudo`，所以不能直接开放 `80/443` 或修改 `firewalld`。
固定后端必须由服务器管理员提供端口映射和证书，或迁移到有管理员权限的 VM。
