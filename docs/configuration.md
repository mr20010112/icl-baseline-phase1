# 独立包配置 / Standalone package configuration

完整步骤见 [第三方操作指南](../handoffs/third-party/README.md)。v1 和 v2 均已冻结；
v2 是当前执行协议，v1 仅保留版本链。操作员不得手工创建、修改或重新冻结任何协议；唯一例外是负责人授权的 tools/amend_limits.py 后继时限版本，须披露并重新批量代码评审；
其他必要变更均退回项目负责人，以新版本处理。保留原冻结协议字节，仅由授权工具追加后继登记。使用
`experiments/baseline-seed42.json`、seed43、seed44 三个 job。

Follow the [operator guide](../handoffs/third-party/README.md). Both protocols are
already frozen: v2 is active; v1 is retained only for the version chain. Operators
must not create, edit or re-freeze any protocol by hand. The sole owner-authorized exception is a disclosed limit successor created by tools/amend_limits.py; fresh batch code review is required. Return every other needed change to the
project owner as a new version. Preserve all existing frozen protocol bytes; only the sanctioned tool appends successor registry entries.
Resource, review and budget gates still apply. Use the three exported
seed jobs. This package contains no historical registrations or reproduction results.

- `configs/research.json`: replace `baseline.repo_path=<OPERATOR_CONTEXTFLOW_CHECKOUT>`
  with your verified official checkout's absolute path; preserve the pinned commit
  and paper source. The preflight record belongs at
  `reports/third-party/baseline-preflight.json`, based on the supplied template.
- `configs/resources.json`: all four groups start empty. Register your own verified
  data, training interpreter, local compute and initialization weights; synchronize
  their IDs with research.json and all three jobs.
- `configs/budget.json`: real execution starts disabled with zero real limits.
  The resource owner sets authorized values following the protocol and guide.
- `configs/checks.json`: retain mandatory gates. `configs/models.json` retains
  review policy; `init` rebases portable `.mcp.json` and generates reviewer/install
  metadata. The operator uses the manual review round-trip in the guide.

只把实际检查通过且有真实证据的项写成 pass。baseline-preflight 不证明复现成功；
每个 seed 需要自己的 accepted code-review receipt，执行 completed 也不等于科学接受。
Preserve genuine verification evidence. Preflight does not certify reproduction;
each seed needs its own accepted code-review receipt. Completed execution still
requires result analysis and independent result review.

## Authorized limit deviations / 已授权时限偏差

Owner decision 2026-10-31: ONLY `tools/amend_limits.py plan|apply` may append
disclosed limit successors. Existing frozen files, evaluation-params and all
scientific settings remain immutable. `tools/review_batch.py` is included in both
phases for the required fresh per-job review round trip after a binding change.
Before observed runs provenance is unchanged; afterwards the unchanged contract
gate requires **post-hoc, exploratory; results are not preregistered** disclosure.
Record OPERATOR_LOG.md and return reports/third-party/limit-deviation.md plus the
entire old/new chain and evidence. Numeric review-call limits still count every
receipt. See the operator guide section 9 and docs/operator-limit-authorization.md.
负责人授权仅经工具追加时限后继版，必须披露并重新批量评审；原冻结文件不原地修改，
任何已观察运行后的新版本均按既有门禁标记 exploratory；其他科研设置不变。
