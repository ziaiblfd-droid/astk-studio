# 富集分析更新与部署记录（2026-10-09）

本记录替代 `enrichment-backend-20261008.md` 中关于 motif、单张合并富集图和表格展示的旧描述。

## 当前行为

- 删除 motif 的页面入口、前端实现和后端计算；API 对该模块返回 400。
- 富集结果页面仅展示图片、筛选控件和 CSV 下载，不渲染统计表或示例预览。
- ORA 按每个基础分析比较组分别处理 A3、A5、AF、AL、MX、RI、SE；选择一个数据库后输出 `7 × 比较组数` 张图片，不再混合比较组或事件类型。
- 前景为对应组/类型的显著 dPSI 事件对应基因，可限制为 dPSI 上升/下降；背景为同一组/类型的有效检测事件对应基因，进一步限制到 GMT 注释范围。
- 显著文件缺失但背景存在时，使用父任务的 p-value / abs-dPSI 阈值派生显著事件。缺失背景的组合生成明确标注的图片；全部背景缺失则任务失败。
- 无显著富集时生成明确说明的图片，不使用未显著项冒充显著富集。
- 新增富集比对模式：独立计算上述组合的 ORA，输出显著 term 的气泡图与热图。每页最多 14 个组合，每页两张图；灰色热图格子表示没有通过阈值的结果，而不是数值为零。
- CSV 保留所有检验条目（包括未显著条目）、比较组、事件类型、BH 校正值、显著标记和完整重叠基因列表。

## 输出目录

```text
output/enrichment/{group}_{type}/{database}.png
output/enrichment/{group}_{type}/results.csv
output/enrichment_{database}.csv
output/enrichment_compare/{database}/comparison_bubble.png
output/enrichment_compare/{database}/comparison_heatmap.png
output/enrichment_compare/{database}/comparison.csv
```

超过 14 个组合时，比对图片分入 `page_001/`、`page_002/` 等目录，汇总 CSV 保持在数据库目录。图片路径均带 `output/` 前缀，由现有任务文件接口提供。

## 统计边界

当前是 Python + 离线 GMT 实现的单侧 Fisher/超几何检验与 Benjamini-Hochberg 校正，不直接调用 ASTK 的 R/clusterProfiler `enrich` / `enrichCompare`。API 为向后兼容保留 `qvalue` 参数名，但含义是 BH FDR 阈值，页面已明确标注。GMT 版本、基因 ID 映射、背景集、条目过滤和 q-value 算法不同，都可能导致结果与原生 ASTK 不一致，不应宣称数值完全一致。

## 验证

- 本机全套 unittest：56 项通过。
- Linux 服务器 conda 环境全套 unittest：56 项通过（SciPy 1.13.1，Matplotlib 3.9.4）。
- 回归覆盖：两组产生 14 张 ORA 图、无交叉混合、旧目录推断、缺失输入、空结果、分页、基因名表头误判、完整 CSV、绘图失败、删除模块和非法模式 API。
- Playwright：1440×1000、390×844；真实本地 HTTP 提交/队列/计算/文件请求，两组 14 张图，组筛选 7 张，组+类型筛选 1 张，比对 2 张，CSV 下载成功，无 JS 异常或横向溢出。
- 浏览器使用合成输入，未重新运行用户真实 quant 数据的完整基础分析；此次没有修改基础分析算法。
- 截图/数据位于忽略的 `data/enrichment-browser/` 和 `data/enrichment-smoke-*/`，不纳入 GitHub。

重现浏览器验证：先 `python tests/prepare_enrichment_smoke.py`，使用其打印的目录设 `ASTK_DATA_ROOT` 与 `ASTK_GENESET_DIR`，设 `ASTK_PORT=4180` 启动 `python -m backend.server`。运行 `node tests/enrichment_browser_smoke.cjs`，可设 `PLAYWRIGHT_MODULE`、`CHROMIUM_PATH` 与 `SMOKE_URL`。测试仅将浏览器上下文接到合成父任务，计算和下载走真实接口。

## 已部署

- 站点：<https://astkstudio.dpdns.org/>。
- 后端 release：`/home/yushiye/astk-web/releases/enrichment-20261009-1048`。
- 前一 release：`/home/yushiye/astk-web/releases/909a5d2`，完整保留。
- 切换记录：`/home/yushiye/astk-web/deployments/enrichment-20261009-1048/`。
- 部署前确认 running/queued/inflight 均为 0；服务器候选版本全套测试通过后再切换 `current`，由 `astk-studio.service` 管理。
- Worker 静态资源发布成功，公网页面/脚本包含两个富集标签和 `20261009` 资源标记，无 motif 模块。
- Playwright 公网浏览器检查：两个模式可见，`/api/health` HTTP 200 / status ok，队列空闲，无页面 JavaScript 异常。公网检查未提交真实分析任务。
- 保留 `ASTK_RETENTION_DAYS=0.5`、`ASTK_UPLOAD_RETENTION_SECONDS=43200`，上传与任务恢复配置未改。
- 本机部分公网连接超时，发布借助现有服务器 SSH 转发。Cloudflare 对 Python 默认 User-Agent 返回 1010/403，而 curl/浏览器式请求正常；以实际公网资源和接口检查为准。

## 回退与清理

后端回退前先确认队列空闲，停止用户 systemd 服务，将 `~/astk-web/current` 原子切回 `releases/909a5d2`，然后启动服务并检查 `/api/health`。共享的 `~/astk-web/data` 不需要移动或删除。不要在有运行任务时切换服务。

代码回退基线为 Git 提交 `33b3638`，本次更新提交在原分支 `backup/upload-speed-20261007`。前端应与后端一起回退；不要直接使用仅针对 2026-09-27 的旧 `rollback-worker.ps1`。可在独立 checkout 中检出目标提交，构建 `dist/` 后重新发布 Worker。

本次只移除关联的无用 motif/表格/预览实现。原有未跟踪文档、部署资料、凭据、Cloudflare 状态、用户备份和真实数据均保留，未批量删除或提交。后续可用 `scripts/deploy-enrichment-release.sh` 创建可验证、可回退的新 release，而不是原地覆盖旧版后端。
