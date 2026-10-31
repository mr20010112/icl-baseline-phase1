# Idea card 模板

每候选一份，建议 `idea-stage/ideas/<idea_id>.json`（机器读取）；额外论证可放独立 Markdown；不要将其他候选内容放入独立评审包。

| 字段 | 说明与填写示例 |
|---|---|
| idea_id / title | 稳定英文标识 / 待填标题 |
| research_question / hypothesis | 可证伪预测；例：待填机制在待填setting下改变待填指标 |
| baseline | 原文路径、版本、实现版本、复现证据；未知留空 |
| method / implementation_map | 拟修改模块、代码路径、配置开关 |
| novelty_evidence | 最近邻工作、真实来源、区别与未核实点 |
| compatibility | 数据/模型/评测接口约束，不能只写“兼容” |
| implementation_cost | 人时、计算、改动范围与依赖 |
| expected_signal | 成功/独立失败/证据不足，各自可观察 |
| risks / confounders | 泄漏、额外算力、调参不公平等实际相关风险 |
| proposer_identity | 实际模型与来源凭据；未知写 unknown |
| reviewer_identity / independence | 实际模型、family、会话、证据；same-family不得称cross-model |
| verdict / reasons | go / revise / kill + 理由；例：revise，待明确评测混淆因素 |
| architect_decision | 收敛决定、时间、采用/不采用的建议 |
| contract_reference | 冻结后填路径和版本；未冻结写 pending |

评分只能辅助排序，不能写成 hypothesis 已被证明。每轮评审追加原始响应并引用，不覆盖之前的理由。

机器可读评分位于导入结果的 `scorecard`，字段见 `candidate-review.example.json`。五维均取0到5分且越高越好；`complexity` 表示复杂度可控程度。`recommendation` 为 go/revise/kill，revise 必须列出带稳定 ID 的 `revision_requests`。

architect 使用 `selection.example.json` 汇总整个候选池：每个候选绑定源文件SHA和最终review receipt；候选数量与research配置一致；ranking列出全部候选，非kill按总分降序、kill排后；同分填写tie_break_reason。选定候选必须是排名第一且已取得go。修订候选保留review_history，在revision_resolutions逐项引用旧请求、处理理由和证据，再以最新内容重新评审。此完整选择记录不加入任何单候选评审包。
