# ASTK Studio 初版

这是论文配套 ASTK Web 平台的第一版交互原型。当前版本已经包含轻量任务后端：

- 任务配置与文件上传交互
- ASTK 任务创建、进度轮询与状态保存
- 七类可变剪切事件概览
- 事件分布、PSI PCA、热图、火山图
- 事件浏览器、搜索、事件类型和方向筛选
- 论文数据集入口与流程说明
- 上传文件接收与任务目录隔离
- 分析结果 JSON 与报告 ZIP 下载
- `samples.csv` 校验与 ASTK 兼容元数据生成
- 不等生物学重复支持
- 安全 ZIP 解压与路径穿越拦截
- `astk dsflow` 命令计划和真实结果解析

默认使用内置的心脏发育数据执行演示任务。正式 Linux 服务器可通过环境变量切换到外部 ASTK 执行器。

## 发布模式

项目支持两种运行方式：

- **GitHub Pages**：公开的论文数据与交互演示，不上传数据、不执行 ASTK。
- **Docker 自托管**：研究者在自己的 Linux 环境执行真实 ASTK 分析。

详细方案见 [docs/deployment-options.md](docs/deployment-options.md)。推送到 `main` 后，GitHub Actions 会自动构建并发布静态站点。

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

## 接入 ASTK

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

`plan.json` 中包含完整 `astk dsflow` 参数。Linux 环境可以直接使用：

```bash
export ASTK_EXECUTION_MODE=command
export ASTK_RUNNER_COMMAND='/opt/astk-studio/scripts/run-astk-job.sh {job_dir}'
```

执行完成后，`backend.result_parser` 会把 ASTK 的 `psi/`、`sig01/` 和元数据转换为网页使用的 `output/results.json`。

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

默认只启动一个 ASTK worker，后续任务进入队列。可通过 `ASTK_WORKERS` 调整并发数，但每个 ASTK 任务可能消耗较多 CPU 和内存。
