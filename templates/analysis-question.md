# 分析与追加实验模板

- `analysis_id / idea_id / protocol_ref`: 待填，引用原协议。
- `research_question`: 本分析要解释的现象。
- `input_runs`: 实际 run ID、类型、原始结果、配置与代码快照；失败 run 也列出。
- `observations`: 仅从文件读取到的事实，与推断分开。
- `competing_explanations`: 至少写出会导致不同决策的解释；例：优化不足 vs 方法无效（只是思路示例）。
- `proposed_experiment`: 哪个实验能区分哪些解释；独立变量、因变量、控制和混淆。
- `expected_discriminating_signal`: 各种结果分别会改变什么判断。
- `required_cost`: 计算、人时、失败重试的上界。
- `stopping_conditions`: 什么证据/预算/超时后停止。
- `hypothesis_status`: 根据已观察结果提出则 `exploratory`；后续新协议在新数据上确认可另登记 confirmatory，不能回填过去。
- `protocol_change`: 新版本、原因、时间、已见结果和影响范围；未经冻结不启动训练。
- `decision_and_learning`: 结论、范围、失败带来的认识、仍未知什么。
- `claim_links`: 支持/反驳/不足的 claim ID；语义判定对应独立评审。

## 机器审计入口

claim 引用的 `analysis_file` 为 JSON，必须含 `kind`、`contract`、`outcome`（success/failure/inconclusive）、`decision`、`limitations`、`runs`、`analyst_identity` 和 `signal_results`。`signal_results` 恰覆盖协议的全部 signal ID，每项含 `signal_id`、`status`（met/not_met/inconclusive）、`reason`、非空 `evidence`。证据引用本分析内实际运行的冻结指标或经过索引校验的原始文件。把上述详细分析问题放入同 JSON 的扩展字段或引用 Markdown；不要维护两份不同结论。填写入口见 `analysis.example.json`。

```json
{"signal_id":"replace-signal-id","status":"inconclusive","reason":"待填真实依据","evidence":[{"run_id":"replace-run-id","artifact":"stderr.log"}]}
```

此占位例不代表任何真实实验结果。CPU toy 的分析必须写 `kind: toy`，正式论文审计将拒绝引用。

`outcome` 对应类别至少有一个 `met` signal。结论为 success 时，失败与不足信号必须明确判定为 `not_met`。评审 PASS 表示逐项分析得到支持，也可以接受有证据的 failure/inconclusive，不能用评审 PASS 冒充实证成功。

完成分析后导出独立结果评审包，读取原始运行和冻结协议：

```bash
python3 tools/research.py context-pack --idea IDEA_ID --purpose result-review --analysis analysis/ANALYSIS.json
python3 tools/research.py import-review --package handoffs/PACKAGE --result handoffs/RESULT.json
```

命令中的大写路径是待替换值。reviewer 须与 analyst 独立；真实结果还须与实现者独立。保留原始回答、实际身份附件和直接读取记录。分析文件不回填 receipt，避免循环哈希：由 claim 的 `result_review_receipt` 或 baseline 验证记录的同名字段引用。修改分析、运行材料或协议后，旧评审不能继续通过。

每条实证 claim 使用 `signal_ids` 引用已判定的 signal，`runs` 与 `metrics` 必须有这些 signal 的原始证据支持，并填写 `result_review_receipt`。不存在的 ID、无证据指标、漏判 signal 和不独立评审都会阻塞。该校验核实记录与引用；claim 文字的语义和科学解释仍需论文评审。
