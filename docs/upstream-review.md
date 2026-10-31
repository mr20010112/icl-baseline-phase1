# ARIS 采用记录

核实日期：2026-10-28。仓库：[wanshuiyin/Auto-claude-code-research-in-sleep](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep)。采用 commit：`18bceb3c71c638bef58096274e1c9a6d323dbc0a`（2026-10-24）。按固定 commit 分发，不跟随 `main` 自动更新。许可证：MIT，保留上游 `LICENSE` 与版权。

## 实际阅读依据

下列路径均相对于固定版本上游目录；`AGENT_GUIDE.md` 是路由索引，行为以 SKILL 和共享协议为准。

| 依据 | 核实到的行为 |
|---|---|
| `README.md`、`AGENT_GUIDE.md` | 主链 W1→W1.5→W2→W3；主线 Claude 与 Codex mirror 分开安装 |
| `skills/idea-discovery/SKILL.md` | `idea-stage/IDEA_REPORT.md`；`/idea-creator` 可能启动 pilot；原生默认不是本项目的安全起点 |
| `skills/idea-creator/SKILL.md` | 8–12 候选、最多 3 个 pilot；先产生候选再以独立 jury 分配试验预算 |
| `skills/experiment-bridge/SKILL.md` | 优先读取 `refine-logs/EXPERIMENT_PLAN.md`；原生工作契约为 `idea-stage/docs/research_contract.md`；实现→代码评审→sanity→部署 |
| `skills/auto-review-loop/SKILL.md` | 原生 `REVIEW_STATE.json`、`review-stage/REVIEWER_MEMORY.md`，默认 MAX_ROUNDS=4；具体路由与停止由 `review_gate.py` 判定 |
| `skills/paper-writing/SKILL.md` | `NARRATIVE_REPORT.md`→`paper/`；submission 需要真实审计产物及 `verify_paper_audits.sh` |
| `skills/training-check/SKILL.md` | W&B/日志趋势检查；它明确区分训练质量与 `watchdog.py` 进程健康 |
| `skills/result-to-claim/SKILL.md` | 原始结果→数值存在性预检查→独立语义评审→claim，存在性不等于支持性 |
| `skills/shared-references/{reviewer-independence,review-tracing,acceptance-gate,experiment-integrity}.md` | 原始文件由评审者自己读；完整调用留痕；执行完成与科学接受分离；禁止假GT、phantom结果 |
| `skills/shared-references/{resumable-runs,compute-env-contract,integration-contract}.md` | `.aris/runs/` 原生阶段状态；环境登记优先复用；helper 分层解析与明确失败策略 |
| `skills/shared-references/{citation-discipline,assurance-contract,reviewer-backends}.md` | 文献真实性和引用语境分开核实；六态审计；实际模型身份决定独立性 |
| `templates/README.md`、`templates/RESEARCH_CONTRACT_TEMPLATE.md` | 模板索引有概括，契约模板正文明确是可更新的当前 idea 工作文档，不能充当冻结判据 |

## 安装依据与本地适配

上游支持的终端命令是 `bash <aris>/tools/install_aris.sh <project>`（Claude）和 `bash <aris>/tools/install_aris_codex.sh <project>`（Codex）。前者管理 `.claude/skills/` 与 `.aris/installed-skills.txt`，后者管理 `.agents/skills/` 与 `.aris/installed-skills-codex.txt`；`.aris/tools/` 提供 helper。

本项目初始化脚本采用上游安装器，并将依赖固定在项目内。迁移后的链接与 manifest 路径由初始化入口重建，不能直接依赖旧机器的绝对路径。依赖源码与项目规则分开，不编辑上游 SKILL 来追赶临时研究需要。

`/idea-discovery`、`/experiment-bridge` 等是 **agent slash skill**，不能作为 shell 命令粘贴执行。只有 `python3 ...`、`bash ...` 代码块是终端命令。完整 CLI 以项目 README 和 `--help` 为准。

## 项目明确加强的地方

1. 上游 W1 的 pilot 可能早于最终实验计划。本项目用分步入口先完成 baseline、独立评审与协议冻结；pilot 也必须通过运行门禁。不能直接让 W1 越过这些门禁。
2. 主线 Experiment Bridge 在 reviewer 不可用时可继续；本项目所需评审缺失则阻塞，不将 graceful fallback 写成通过。
3. Codex 原生同 family subagent 可做 provisional review，但不能冒充跨模型接受。本项目要求记录实际身份和来源；人工转交也不省略。
4. 上游 contract 可更新；本项目另加不可原地修改的版本化 YAML 协议。进度更新只引用协议，不能修改判据。
5. 实际硬件、CLI、MCP、商业模型、远程训练及投稿审计须在目标环境另行验证。本次工程 toy 不是这些集成的通过证明。

## 复用验证器

`tools/run_state.py` 保留原生阶段状态；`tools/idea_discovery_gate.py` 检查 W1 锚点与评审收据；`tools/evidence_check.py` 检查数值来源存在性；`tools/review_gate.py` 处理原生 review loop；`tools/verify_paper_audits.sh` 检查 paper 审计。它们不能证明科研结论正确。本项目仅补协议版本、资源/预算、运行产物绑定、隔离交接与 claim 链路等缺口。实际执行范围见验收报告。
