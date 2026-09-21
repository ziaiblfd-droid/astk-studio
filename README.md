# ASTK Studio 初版

这是论文配套 ASTK Web 平台的第一版交互原型。当前版本已经包含轻量任务后端：

- 任务配置与文件上传交互
- SUPPA2 分析任务创建、进度轮询与状态保存
- 七类可变剪切事件概览
- 事件分布、PSI PCA、热图、火山图
- 事件浏览器、搜索、事件类型和方向筛选
- 论文数据集入口与流程说明
- 上传文件接收与任务目录隔离
- 分析结果 JSON 与报告 ZIP 下载
- 任意文件名的 CSV 样本表校验与分析元数据生成
- 不等生物学重复支持
- 安全 ZIP 解压与路径穿越拦截
- SUPPA2 七类事件、PSI/dPSI 分析和真实结果解析

默认使用内置的心脏发育数据执行演示任务。正式 Linux 服务器通过内置的 SUPPA2
执行真实分析，不再依赖原 Linux 服务器上的 ASTK 环境。

## 发布模式

项目支持两种运行方式：

- **GitHub Pages**：公开的论文数据与交互演示，不上传数据、不执行计算。
- **Docker 自托管**：在任意持续在线的 Linux 云主机执行真实 SUPPA2 分析。

详细方案见 [docs/deployment-options.md](docs/deployment-options.md)。仓库处于私有开发阶段时，
Pages 工作流仅支持手动触发；正式公开前先在仓库设置中启用 GitHub Pages，再运行
`Deploy GitHub Pages` 工作流。公开发布后可按需要恢复 `main` 分支自动部署。

## 本地打开

在当前目录运行：

```powershell
py -3 backend/server.py
```

然后打开 `http://localhost:4173`。

## API

- `GET /api/health`：服务状态与运行模式
- `POST /api/jobs`：创建任务，可接收 JSON 或 multipart 文件
- `GET /api/jobs/{id}`：任务状态与进度
- `GET /api/jobs/{id}/results`：分析结果
- `GET /api/jobs/{id}/download`：下载结果 ZIP

任务保存在 `data/jobs/{job_id}`，每个任务有独立的输入和输出目录。
默认在任务完成或失败 7 天后自动删除整个任务目录，可通过
`ASTK_RETENTION_DAYS` 和 `ASTK_CLEANUP_INTERVAL` 调整。

输入规范见 [docs/input-format.md](docs/input-format.md)，示例表格位于 `templates/samples.csv`。

## SUPPA2 分析引擎

默认配置：

```powershell
$env:ASTK_EXECUTION_MODE = "demo"
py -3 backend/server.py
```

Linux 部署时设置：

```bash
export ASTK_EXECUTION_MODE=command
export ASTK_RUNNER_COMMAND='/opt/astk-studio/scripts/run-astk-job.sh {job_dir}'
python3 backend/server.py
```

外部执行脚本读取任务目录中的 `job.json` 和 `input/`。网站会自动生成：

- `metadata/astk_metadata.json`
- `metadata/astk_metadata.csv`
- `plan.json`

`plan.json` 中包含可复现的事件生成参数。Linux 环境可以直接使用：

```bash
export ASTK_EXECUTION_MODE=command
export ASTK_RUNNER_COMMAND='/opt/astk-studio/scripts/run-astk-job.sh {job_dir}'
```

执行完成后，`backend.result_parser` 会把 SUPPA2 的 `psi/`、`dpsi/`、
显著事件和元数据转换为网页使用的 `output/results.json`。项目内置的是
SUPPA2 v2.4 的最小运行代码，许可和版本信息见 `vendor/suppa2/UPSTREAM.txt`。

## Docker 部署

项目提供了 `Dockerfile` 和 `compose.yaml`。正式运行前，将参考文件放到：

```text
references/mm10/gencode.vM25.annotation.gtf
references/hg38/gencode.v44.annotation.gtf
```

然后运行：

```bash
docker compose up --build -d
```

默认只启动一个 ASTK worker，后续任务进入队列。可通过 `ASTK_WORKERS`
调整并发数，但每个分析任务可能消耗较多 CPU 和内存。

## 公网 Linux 部署

要让其他人在本机关机后仍能访问，必须把网站和 SUPPA2 执行环境部署到持续运行的 Linux 服务器，并为其分配公网端口或域名。仓库提供了三种方式：

1. 临时公网验证：运行 `scripts/run-public-server.sh`，服务监听 `0.0.0.0:4173`，然后由服务器管理员在安全组和防火墙中放行该端口。
2. 生产单机服务：使用 `deploy/astk-studio.service` 注册 systemd 服务，再用 `deploy/nginx-astk.conf` 反向代理并配置 HTTPS。
3. 容器部署：使用仓库根目录的 `Dockerfile` 和 `compose.yaml`，把 `ASTK_HOST` 设为 `0.0.0.0`，并将数据卷挂载到持久化磁盘。

直接暴露 `4173` 端口只适合临时测试。正式公开前应配置域名、HTTPS、身份认证、上传限制和定期备份。Nginx 示例中的 `astk.example.com` 需要替换为实际域名。

### 固定后端最短路径

新的后端镜像基于标准 Python 3.12，固定安装 ASTK `dev` 分支提交
`db165a2e5e6c5cc63305247e87409b1e1362fd90`，并保留内置 SUPPA2 v2.4 作为兼容回退。
镜像可在 `linux/amd64` 和 `linux/arm64` 上构建。正式分支会同时推送
`ghcr.io/<owner>/astk-studio-backend:latest` 多架构镜像。准备一台持续在线的
Linux VM、一个可配置 DNS 的域名和 TLS 邮箱后：

```bash
export ASTK_BACKEND_IMAGE=ghcr.io/ziaiblfd-droid/astk-studio-backend:latest
export ASTK_DOMAIN=astk-api.example.com
export ASTK_TLS_EMAIL=you@example.com
bash scripts/deploy-fixed-backend.sh
```

如果云服务器尚未登录 GHCR，先执行 `docker login ghcr.io`；私有仓库需要可读取
该 Package 的 Token。脚本会拉取镜像、启动仅绑定 `127.0.0.1:4173` 的 Docker
服务、执行本机健康检查并生成
`Caddyfile`。按脚本提示启动 Caddy 后，从外部网络验收：

```bash
ASTK_BACKEND_URL=https://astk-api.example.com bash scripts/verify-fixed-backend.sh
```

验收通过后，在 Streamlit Community Cloud 的 Secrets 中将
`ASTK_BACKEND_URL` 更新为该固定 HTTPS 地址。不要把 TryCloudflare 或
Localtunnel 临时地址用于正式配置。

## Streamlit Cloud 固定前端

仓库还提供了一个 Streamlit 入口 `streamlit_app.py`。它可以把界面部署到固定的
`https://<app-name>.streamlit.app` 地址，同时把计算任务提交给远程 SUPPA2 API：

```text
用户 -> Streamlit Cloud -> Linux API -> SUPPA2 计算
```

本地运行：

```powershell
py -3 -m pip install -r requirements.txt
$env:ASTK_BACKEND_URL = "http://127.0.0.1:4173"
py -3 -m streamlit run streamlit_app.py
```

部署到 Streamlit Community Cloud：

1. 将仓库推送到 GitHub。
2. 在 Streamlit Community Cloud 创建 App，选择本仓库和 `main` 分支。
3. 入口文件填写 `streamlit_app.py`。
4. 在 App 的 Secrets 中配置 `ASTK_BACKEND_URL`：

```toml
ASTK_BACKEND_URL = "https://your-astk-backend.example.com"
```

Streamlit 会提供固定 HTTPS 地址。真正的分析计算仍由 Linux 服务执行，因此
Streamlit 免费实例休眠或重建时，已经提交到后端的任务不会因此丢失。后端地址必须
是长期稳定的 HTTPS 地址；临时 TryCloudflare 地址会变化，只适合测试。
