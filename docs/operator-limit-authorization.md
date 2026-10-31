# Operator limit deviation authorization / 操作员时限偏差授权

Owner decision, 2026-10-31 (Task #10): the third-party operator may change
wall-clock timeout and stall limits ONLY through `tools/amend_limits.py`, as a
disclosed deviation. The owner cannot receive mid-run data. This authorization
does not authorize changes to scientific settings, additional seeds/attempts,
training steps, batch size, evaluation, data or model choices.

项目负责人于 2026-10-31 授权：仅通过该工具生成并冻结后继版本，保留原冻结文件，
按原 CPU/GPU 数及尝试次数重新计算预算。默认不得降低限制；降低须显式
`--allow-lower` 并披露。所有门禁、原有重试限制和 phase-2 书面放行条件继续有效。

Before any observed run of the idea, provenance stays unchanged. After observed
runs, follow the existing contract rules: disclose the ledger's observed runs,
set provenance.mode to exploratory, and label the amendment **post-hoc,
exploratory; results are not preregistered**. Hypothesis-basis declarations and
all other scientific bytes remain unchanged. Do not modify contracts.py rules.

Limits and binding changes require the batch code-review round trip again.
Disclose the amendment in OPERATOR_LOG.md and return the complete deviation
report, old/new protocols and registry, jobs/configs, receipts and run evidence.
Existing evidence is never relabelled or removed. Global resource authorization
and budget settings remain the operator/resource owner's responsibility.

本文件记录项目所有者在会话中的授权文本，供偏差记录引用和哈希绑定；工具不将
此文件视为身份签名或新的科研验收，也不自动执行训练、评测或外部模型调用。
