# ASTK Studio 输入格式

真实 ASTK 任务由一个数据 ZIP 和一个 CSV 样本表组成。CSV 文件名可以保留为
`facial_11.csv` 等原始名称，不需要改成 `samples.csv`。

## 数据 ZIP

建议保留 Salmon 的样本目录结构：

```text
quant.zip
└── quant/
    ├── heart_e11_rep1/quant.sf
    ├── heart_e11_rep2/quant.sf
    ├── heart_e12_rep1/quant.sf
    └── heart_e12_rep2/quant.sf
```

每个 `quant.sf` 必须包含 Salmon 标准列：

```text
Name  Length  EffectiveLength  TPM  NumReads
```

## CSV 样本表

模板可从 `/api/templates/samples.csv` 下载，字段使用 ASTK 元数据格式：

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `group` | 是 | 比较组名称 |
| `condition` | 是 | 样本角色，必须为 `ctrl` 或 `case` |
| `name` | 是 | 唯一样本名称，用于结果列名 |
| `path` | 是 | ZIP 内 `quant.sf` 的相对路径 |
| `replicate` | 是 | 组内重复编号，从 1 开始 |

示例：

```csv
group,condition,name,path,replicate
E11.5_vs_E12.5,ctrl,heart_e11_rep1,quant/heart_e11_rep1/quant.sf,1
E11.5_vs_E12.5,ctrl,heart_e11_rep2,quant/heart_e11_rep2/quant.sf,2
E11.5_vs_E12.5,case,heart_e12_rep1,quant/heart_e12_rep1/quant.sf,1
E11.5_vs_E12.5,case,heart_e12_rep2,quant/heart_e12_rep2/quant.sf,2
```

同一任务的 Ctrl/Case 重复数必须一致。旧版网页的
`sample_id,condition,quant_path,baseline,order` 格式仍可读取，但新任务建议使用上面的
ASTK 原生格式。
