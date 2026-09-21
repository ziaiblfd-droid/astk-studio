# 发布与计算部署方案

ASTK Studio 分为展示前端和计算后端两部分。固定前端使用 Streamlit Community
Cloud，计算后端运行在持续在线的 Linux 云主机上。后端不再依赖原校内服务器的
ASTK 或 Conda 环境，也不必访问 `172.18.236.93`。

## 计算架构

后端镜像基于标准 Python 3.12，固定安装 ASTK `dev` 分支提交
`db165a2e5e6c5cc63305247e87409b1e1362fd90`，并保留内置 SUPPA2 v2.4 作为兼容回退。
输入为 Salmon `quant.sf` 和一个
CSV 分组表，输出七类可变剪切事件、PSI/dPSI 结果和图表。

镜像发布到 GHCR：

```text
ghcr.io/ziaiblfd-droid/astk-studio-backend:latest
```

GitHub Actions 在 `main` 分支推送时构建并发布 `linux/amd64` 与 `linux/arm64`
两种架构。镜像中的科学计算依赖和 ASTK 提交均已固定，不依赖云服务器预装 Conda 环境。

生产服务器建议至少 4 GB 内存。1 GB 实例需要额外 swap 并完成真实任务压测。

| 方案 | CPU 架构 | 估算内存 | 结论 |
| --- | --- | --- | --- |
| Oracle `VM.Standard.A1.Flex` | ARM64 | 4 GB 及以上 | 推荐先做端到端压测 |
| 通用云主机 | x86_64 | 4 GB 及以上 | 推荐生产使用 |
| 2 GB 云主机 | x86_64/ARM64 | 2 GB + swap | 仅适合小数据或试用 |

## 固定后端部署

前提：

- Ubuntu 22.04/24.04 或兼容 Linux
- Docker Engine 与 Compose plugin
- Caddy（或改用 Nginx）
- 一个归你控制的域名，例如 `astk-api.example.com`
- 域名 A/AAAA 记录已指向 VM 公网 IP
- 云安全组放行 TCP `80` 和 `443`
- 至少一份实际使用的参考注释 GTF 放在 `references/` 下

```bash
export ASTK_BACKEND_IMAGE=ghcr.io/ziaiblfd-droid/astk-studio-backend:latest
export ASTK_DOMAIN=astk-api.example.com
export ASTK_TLS_EMAIL=you@example.com
bash scripts/deploy-fixed-backend.sh
```

脚本会拉取固定镜像、启动只绑定 `127.0.0.1:4173` 的 Docker 服务、等待健康检查，
并生成 Caddyfile。它不会自动修改系统服务；安装 Caddy 后执行：

```bash
sudo caddy run --config ./Caddyfile --adapter caddyfile
```

确认 HTTPS 正常后，可将 Caddy 注册为 systemd 服务。仓库中的
`deploy/nginx-astk.conf` 也可作为替代配置，但需要替换 `${ASTK_DOMAIN}`。

## 验收

先做基础连通与上传验收：

```bash
ASTK_BACKEND_URL=https://astk-api.example.com bash scripts/verify-fixed-backend.sh
```

该模式会验证健康接口、模板下载和任务接收。由于合成探针没有服务端参考注释的
真实转录本 ID，它不会声称计算已经完成。要验证完整分析，请把一份真实测试数据
传给脚本：

```bash
ASTK_BACKEND_URL=https://astk-api.example.com \
ASTK_VERIFY_ZIP=/path/to/quant.zip \
ASTK_VERIFY_CSV=/path/to/samples.csv \
bash scripts/verify-fixed-backend.sh
```

真实数据模式下脚本最多等待 6 小时，并要求任务达到 `completed` 且
`/api/jobs/{id}/results` 返回指标。验收通过后，在 Streamlit Community Cloud
的 Secrets 中设置：

```toml
ASTK_BACKEND_URL = "https://astk-api.example.com"
```

不要把 TryCloudflare、Localtunnel 或临时 SSH 隧道地址用于正式发布。

## 数据与安全

公网部署至少应配置：

- HTTPS 和数据保留期限
- 单任务 CPU/内存限制
- 上传大小限制
- 身份认证或匿名配额
- 恶意文件扫描与日志审计
- 每日备份 `data/jobs` 中需要保留的结果

GitHub Pages 只承载静态演示，不接收计算任务。Streamlit Cloud 只负责前端和
后端 API 转发，真正的 SUPPA2 计算始终在 Linux 云主机执行。

## 从旧服务器迁移

旧的 `yushiye@172.18.236.93` 只作为历史开发环境看待，不需要继续为其补端口、
证书或 Conda 配置。迁移步骤：

1. 在可管理的云主机启动固定后端镜像。
2. 将 `mm10`/`hg38` GTF 放入云主机的 `references/`。
3. 用真实 ZIP/CSV 完成上面的完整验收。
4. 把 Streamlit Secret 的 `ASTK_BACKEND_URL` 切换到新 HTTPS 域名。
5. 确认新任务可轮询、下载报告和后端重启恢复后，再停用旧服务器。
