# ASTK Studio 输入格式

真实 ASTK 任务由一个数据 ZIP 和一个 `samples.csv` 组成。

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

## samples.csv

模板可从 `/api/templates/samples.csv` 下载。字段定义如下：

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `sample_id` | 是 | 唯一样本名称，用于结果列名 |
| `condition` | 是 | 实验条件或发育阶段 |
| `quant_path` | 是 | ZIP 内 `quant.sf` 的相对路径 |
| `baseline` | 是 | 基线组填 `true`，其他组填 `false` |
| `order` | 否 | 相邻阶段比较时的顺序数字 |

示例：

```csv
sample_id,condition,quant_path,baseline,order
heart_e11_rep1,E11.5,quant/heart_e11_rep1/quant.sf,true,1
heart_e11_rep2,E11.5,quant/heart_e11_rep2/quant.sf,true,1
heart_e12_rep1,E12.5,quant/heart_e12_rep1/quant.sf,false,2
heart_e12_rep2,E12.5,quant/heart_e12_rep2/quant.sf,false,2
```

基线模式会生成 `E11_5_vs_E12_5` 这样的比较。不同条件可以拥有不同数量的生物学重复。
