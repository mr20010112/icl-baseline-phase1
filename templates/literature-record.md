# 文献证据记录模板

填写位置建议：`idea-stage/literature/<paper_id>.md`。下例是字段说明，不是实际论文。

- `paper_id`: 留空待填；本地稳定标识。
- `research_question_ids`: 该文献回答哪些研究问题。
- `title/authors/year/venue/publication_status`: 从原始来源核实；区分 preprint/peer_reviewed，未知写 unresolved。
- `source_url/doi/arxiv_id/version/retrieved_at`: 真实来源与读取时间；不猜 DOI。
- `source_format`: latex / markdown / pdf；`local_path` 与 fingerprint。
- `sections_read`: 例：abstract、introduction；复现时另加 method、implementation、evaluation。
- `verification`: verified / pending / contradicted；证据来源和核实内容。
- `evidence_items`: 每条包含原文位置（章节/页/表）、陈述、知识类型、核实依据。
- `knowledge_type`: `verified_fact`（本项目已核实）、`author_claim`（作者报告）、`model_inference`（模型推断）、`hypothesis`（待验证）。
- `problem/method/assumptions/datasets/baselines/results/limitations`: 未读到的字段留空；不能以摘要补齐细节。
- `relevance/cross_domain_link/contradictions/open_questions`: 说明与当前问题的关系，不以“已读过”增加权重。

填写示例：`knowledge_type: author_claim; statement: 待填; locator: 待填表号; verification: pending`。没有来源时不要写入科学事实或正式 bibliography。

## 机器检查记录

实际结构化记录保存在 `idea-stage/literature/evidence.jsonl`，每行一个 JSON 对象。脚本字段是 `classification`，枚举与上述中文含义对应：`verified`（已核实）、`author_opinion`（作者观点/报告）、`model_inference`、`hypothesis`。不要把 prose 的 `knowledge_type` 原样写入 JSONL 代替此字段。

所有类型需要 `source` 与 `locator`。`verified` 另需 `url`、`checked_at`、`artifact`、与原始文件一致的 `artifact_sha256`，以及筛选因子 `venue`（确切会议/期刊+年份，`arXiv preprint` 或 `unresolved`）和 `code_url`（开源代码URL，或 `none`/`unresolved`）。会议级别与有无代码用于调整 baseline/idea 判断，不是科学正确性证明。没有真实来源时保留空文件，不添加下面这样的占位行：

```json
{"id":"待填","classification":"hypothesis","source":"待填真实来源","locator":"待填章节","statement":"待验证预测"}
```

这是字段示例，正式记录须替换占位内容。`python3 tools/research.py audit` 检查记录结构与来源绑定；不代替文献主张的科学核实。
