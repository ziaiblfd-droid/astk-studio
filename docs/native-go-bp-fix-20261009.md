# ASTK GO-BP 富集修复（2026-10-09）

## 范围

只保留 GO Biological Process（BP），移除当前入口中的 MF、CC、KEGG。
过表达富集与长度分组富集比较都按“比较组 × 7 种 AS 类型”运行，互不混合。
结果页展示图片，CSV 保留下载；真正没有富集条目的单元保留明确的空结果 PNG，
不构造虚假的统计结果。

## 实现与原因

旧网站实现使用 Python/GMT 富集和父任务检测基因背景，且 qvalue 的处理与 ASTK
不一致。现在使用 ASTK 安装环境内的 R/clusterProfiler：

- 过表达：`enrichGO`，`ENSEMBL`、`ont="BP"`、`BH`、`readable=TRUE`、
  `pool=FALSE`，背景不指定，沿用 OrgDb GO-BP 默认背景。
- 比较：ASTK `df_len_select` 生成长度分组，R `compareCluster(fun="enrichGO")`。
- 默认 p/q 阈值都是 0.1，与原 ASTK 输入一致；真实 `p.adjust` 和 `qvalue`
  分别保留，不互相替代。
- 保留 `simplifyEnrichment::GO_similarity` / `simplifyGO` / `ht_clusters`
  的可选 GO 聚类结果；聚类异常记录在单元 warnings 与运行日志中。

ASTK 的问题在网站适配层内修复，不更改服务器上安装的 ASTK 或用户的原始目录：

1. SUPPA2 的无版本基因 ID 必须先去除 `;AS:...`，否则 ASTK 原先仅按点号
   截断会将事件坐标一起送入注释映射。
2. `lenCluster` 文件有“两列表头、三列正文”（事件 ID 是索引）的格式。
   `read.delim(header=TRUE)` 会把事件 ID 误当行名，导致比较分析读到 dPSI
   数字而非基因。修复为跳过表头、显式读取三列，与原 ASTK R 脚本一致。
3. `enrichCompare -app auto` 仅检查第一个文件；当 AL 的第一个长度组为空时，
   ASTK 报 `input SUPPA2 must contain one AS type!`。适配层已知事件类型，
   不依赖这个 CLI 检测，空组不阻断其它组。
4. 原 ASTK 某些空结果分支写 PDF 却使用 `.png` 文件名。网站始终生成有效 PNG。
5. 普通 warning 不再令正常的 `compareCluster` 结果被丢弃。
6. 页面轮询上限改为 6 小时，与默认后端富集任务超时对齐，避免计算中的任务
   在旧的 25 分钟轮询上限后被页面误报为超时。

## 原始数据与长度边界

只读参考目录：
`/home/yushiye/project/project2/result/facial_11.5_based/`

本地参考图：
`D:/Desktop/wy/tp/enrich/`

隔离验证目录：
`/tmp/astk-enrich-val-20261009-01/`

原始 `lenc` 分组为 `1-51`、`51-251`、`251-1001`。虽然
`df_len_select` 内部为 `[s,e)`，参考生成流程实际传入 `end + 1`，即包含上边界。
已逐事件核对全部 84 个分组文件，全部一致。因此保留原 ASTK 参考的边界行为，
不擅自改成互斥分箱。

## 验证记录

- 本地 Python 语法检查通过；56 项单元测试通过。
- R 表头解析测试通过：标准三列表头、ASTK 两列表头、前导空列表头、
  空输入、重复基因、带版本与无版本 ID。
- ORA 全量 28 个单元生成 28 张主图。26 个有原始 CSV 的单元共 3,803 个
  GO 条目，其 ID、Description、GeneRatio、BgRatio、Count、pvalue、p.adjust、
  qvalue 和 geneID 集合全部匹配。
- `facial_11.5_12_MX`、`facial_11.5_13_MX` 原 ASTK 没有 CSV；
  新结果均为零条目，生成合法的空结果图和空 CSV。
- 独立回放原 ASTK R 解析方式的比较回归：
  `facial_11.5_12_A3` 匹配 26 行，`facial_11.5_12_AL` 匹配 110 行，
  所有统计量与基因成员匹配。
- 比较全量 28 个单元全部完成，生成 28 张合法 PNG；全部 84 个长度分组
  逐事件匹配原始 `lenc` 文件，包括之前自动检测报错的 4 个 AL 单元。
- GO 聚类抽样使用相同的 ASTK / simplifyEnrichment 算法，71 个条目的集合
  完全一致。旧运行未记录随机种子，新运行固定种子为 1；样本中旧图 8 个簇、
  新图 9 个簇，2,485 对条目中仅 2 对同簇关系不同（99.92% 一致）。
  不声称聚类划分或热图布局与未记录种子的旧图完全一致；这不改变 ORA 统计结果。
- 浏览器合约测试使用真实生成的 PNG 和模拟 API，在 1440×1000、
  390×844 下验证 28 张主图、7 张比较组筛选、1 张事件筛选、GO 聚类筛选、
  CSV 下载、图片加载和无横向溢出。此测试不是实际 HTTP 科学计算回归。

验证环境：R 4.5.1，clusterProfiler 4.18.4，enrichplot 1.30.4，
GO.db / org.Mm.eg.db 3.22.0，qvalue 2.42.0，simplifyEnrichment 2.4.1。
不同 OrgDb / GO.db 版本可能改变背景和统计结果；每次任务输出均记录版本信息。

## 运维

新后端入口：`scripts/deploy-native-enrichment.ps1`，调用
`scripts/deploy-enrichment-release.sh`。
勿再使用旧的原地覆盖、上传 GMT 的 `deploy-enrichment-backend.ps1`。

部署策略：新建 release，保留旧 release；切换前两次检查队列，停止后检查持久化
运行/排队任务，发现新任务则恢复旧服务；健康检查失败自动回滚。
前端仍需独立部署 Cloudflare Worker，后端切换不会更新 Worker 静态资源。

服务器 systemd 的 `90-upload-speed.conf` 当前有效配置仍为
`ASTK_RETENTION_DAYS=0.5`、`ASTK_UPLOAD_RETENTION_SECONDS=43200`（12 小时），
不因本次更新重置。

## 复现命令

```bash
python tests/native_enrichment_reference.py \
  --source /home/yushiye/project/project2/result/facial_11.5_based \
  --output /tmp/unique-ora-validation --skip-go-clustering
python tests/native_enrichment_reference.py \
  --source /home/yushiye/project/project2/result/facial_11.5_based \
  --output /tmp/unique-compare-validation --mode compare --skip-go-clustering
Rscript tests/native_enrichment_contract.R backend/native_enrichment.R
Rscript tests/native_enrichment_compare_reference.R \
  /home/yushiye/project/project2/result/facial_11.5_based \
  /tmp/unique-compare-validation
```

`--skip-go-clustering` 仅用于加速统计回归；正式网站任务仍默认保留 GO 聚类输出。
`--reuse-output` 可校验已完成输出，避免重复科学计算。

## 上线记录

- 新后端 release：`/home/yushiye/astk-web/releases/native-bp-20261009`。
- 旧后端 release：`/home/yushiye/astk-web/releases/enrichment-20261009-1048`，
  未修改，保留回滚用途。
- 切换记录：`/home/yushiye/astk-web/deployments/native-bp-20261009/`；
  `previous-release` / `target-release` 分别记录上述目录。
- 切换前两次队列检查均空闲，停止服务后持久化 active jobs 为空；
  新 release 的 56 项测试及 R 表头测试再次通过，systemd 服务 active，
  本地健康检查通过。
- Worker 版本：`a1c8513a-be05-4d07-8329-387d1975263c`。
- 公网页面与 JS 检查通过：BP-only、p/q 默认 0.1、GO 聚类筛选、6 小时轮询。
  公网 `/api/health` 为 command 模式、status ok；
  无效父任务 BP 请求返回 404，MF 请求返回 400，不创建无效任务。
- 真实原始数据的全量科学计算回归在隔离目录完成；线上验证没有向用户任务队列
  额外提交耗时的科学计算任务。
- Git 备份标识：分支 `backup/upload-speed-20261007`，
  回滚标签 `native-go-bp-20261009`。代码回滚与后端 release / Worker 部署回滚
  是不同操作；回滚前仍应确认队列空闲。
