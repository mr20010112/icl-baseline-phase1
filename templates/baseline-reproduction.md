# Baseline 复现记录模板

- `baseline_id / source_paper / source_sections`: 待填真实论文与方法/评测位置。
- `repository / commit / license / entrypoint`: 待核实代码来源。
- `data_version / fingerprint / split / preprocessing`: 待填；测试集是否用于调参必须说明。
- `environment / hardware / precision`: 实际环境与硬件，不使用预计值冒充实际值。
- `protocol_ref / seeds / tolerance / statistical_rule`: 启动前冻结。
- `data_check / environment_check / evaluation_check / reproduction_check`: pending / pass / fail + 证据文件；不能只填pass。

| metric | paper_reported_value | source_locator | reproduced_value | run_ids | comparison_rule | status |
|---|---|---|---|---|---|---|
| 待填 | 留空 | 待填 | 留空 | 留空 | 预先约定容差/统计判据 | pending |

复现 value 只能由实际 run 导入。失败、中断、负结果、硬件差异与偏离原文之处逐项记录；未达到复现判据时，不以论文报告值替代本项目 baseline。

## 机器门禁需要的 JSON

`configs/research.json` 的 `baseline.validation_record` 指向 JSON 文件；对应基本结构如下（示例全部待填，不能用于声称检查通过）：

```json
{
  "kind":"real",
  "baseline_commit":null,
  "checks":{
    "data":{"status":"pending","evidence_file":null},
    "environment":{"status":"pending","evidence_file":null},
    "evaluation":{"status":"pending","evidence_file":null}
  },
  "reproduction":{"run_ids":[],"analysis_file":null,"result_review_receipt":null}
}
```

准备 baseline 时前三项必须各有非空证据并真实检查为 `pass`。复现完成后，`run_ids` 必须完整覆盖同一冻结 baseline 协议的全部 seeds，每个 seed 一个 completed run。单个历史 `run_id` 可作为单元素输入，但不能代替多 seed 证据。

比较分析使用 `analysis.example.json` 的逐 signal 结构，另填写 `decision: pass`、`tolerance`（`metric`、`atol`、`rtol`、`statistical_rule`、`aggregation`，与冻结统计方案一致）以及 `comparison`（`paper_reported`、`reproduced` 数值和 `paper_source` 原文路径）。登记的论文报告值必须在冻结 baseline 中明确引用，实测值由 run 原始指标聚合得到。目前支持显式 `mean` 或 `median`；统计方案和容差必须在运行前冻结。

复现门禁统一核验协议登记与快照、配置、实现、执行入口、原始指标及产物索引，并比较当前数据 fingerprint、版本、split、环境与 baseline commit。分析完成后通过 `context-pack --idea baseline --purpose result-review --analysis ...` 取得独立结果评审，导入 receipt 后填入验证记录。旧 analysis 自声明 pass、缺 seed、数据变化、快照变化或缺评审均不能作为后续方法的 baseline 锚点。论文原值来源及统计解释仍需评审者直接核查。
