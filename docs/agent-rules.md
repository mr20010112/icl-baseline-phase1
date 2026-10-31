# 共同 agent 规则（唯一维护入口）

优先读取：本文件 → README → 当前状态恢复入口 → `idea-stage/docs/research_contract.md` → 其中引用的冻结协议。只在任务需要时检索完整候选池、历史日志和失败记录。调用 skill 前读取对应固定版本 `SKILL.md` 及其共享协议；不得凭记忆杜撰命令。

## 回复语言

- Claude Code 默认使用简体中文与用户交流，包括进度说明、解释、评审结论和最终回答；即使输入材料或上游 skill 使用英文，也保持简体中文回复。用户明确要求其他语言时遵循用户要求。
- 代码、命令、路径、标识符、原始日志和引用原文保留原样，相关解释使用简体中文。

## 科研真实性

- 每条结果的链路为：研究问题→hypothesis→方法→实现位置→配置→实际运行→原始输出→分析→claim。缺失一段时标记 pending/blocked，不补造。
- 原始数值仅从真实输出读取。失败、超时、中断、负结果、无效实验保留；exit 0 但指标缺失仍不是成功。
- 每个运行保存命令、环境、seed、数据版本/split、代码快照、冻结协议版本及原始输出。论文报告值标为 `paper_reported`，本地复现值标为 `reproduced`，不得互换。
- `mock`、`toy`、`real` 必须分开。toy 只证明工程链路；不能用于真实研究的性能 claim，也不能伪装 baseline 复现。
- 文献按研究问题组织，记录来源和章节，分别标注 `verified`、`author_opinion`、`model_inference`、`hypothesis`。元数据可核实不等于科学主张成立。优先 LaTeX/Markdown；筛选读摘要/引言，复现再读方法/实现/评测。已有论文库同等核实，不因熟悉而加权。覆盖相关与交叉领域。
- 方法与代码逐模块对应，写明入口、配置与版本。GT 来自数据/任务定义；代理评测按上游协议明确标记。容差、统计方案和判据须预先定义；不承诺跨硬件逐位一致。
- 新协议 signal 使用唯一稳定 ID、rule 和 metrics；分析恰好逐项判定，引用运行原始指标或索引文件。每条实证 claim 引用 signal_ids 和独立 result-review receipt。评审必须读取协议、分析和全部运行证据，分析者/实现者不能为自己的结果提供独立接受。

## 角色与上下文边界

| 角色 | 默认产品偏好（可替换） | 责任 |
|---|---|---|
| architect / orchestrator | Claude Code | 维护原生阶段状态、收敛决策、预算与停止 |
| scout | Antigravity | 多角度检索与可核实证据 |
| idea proposer | Antigravity | 约 10 个候选；依据领域上下文与 baseline |
| independent reviewer | Claude Code/ Codex | 分别评审 idea、实现和结果，直接读原始文件 |
| implementer | Codex | baseline、方法、公式推导、代码编写和实验执行 |
| analyst | GPT Pro / Ultra | 区分解释、提出有预算的分析实验 |
| writer | Codex | 仅依据已成立证据组织论文 |

科研阶段通过 `/project-research` 入口执行；`configs/models.json` 与本表保持一致。`python3 tools/model_routes.py check` 核对角色和本地传输配置，`.aris/reviewer.json` 固定原生默认评审到 Claude Code。项目安装只更新登记的本地定制，不修改固定上游。

这些偏好来自指南的使用体验，**不是永久能力排序**。不得把 `ChatGPT Ultra` 转写为猜测的 API model ID。身份记录请求值与返回的实际身份，未知保持 unknown。

每个候选单独创建评审包和新会话，只含该候选、baseline 原文、研究问题与必要资源约束，不含其他候选、生成讨论、ranking、architect 倾向性理由。实现阶段只载入选定 idea 的工作文档；评审可直接读契约、代码、配置和原始结果。不同角色或不同会话不等于不同模型 family；同 family 只能 provisional。人工转交保留原始响应与身份凭据；未完成的检查保持 blocked。评审限定轮数与预算，architect 决定 go/revise/kill；评审分数或口头认同不替代实验。

方法启动前必须有完整 selection_record：配置数量的所有候选、各自内容指纹与独立评分receipt、全体排名、architect身份和理由。revise保留旧评审及逐请求处理证据，并以当前内容重新取得go评审。完整池与ranking不进入单候选review上下文。selection_record为候选选择决策入口。

## 主导与委托

Claude Code 主导全程。任务落入下列角色范围时，主动委托，不要自己代做；architect 与 independent reviewer 不对外委托。

- scout → `literature-search`、`novelty-search`
- idea proposer → `candidate-generation`
- implementer → `implementation`、`formula-derivation`
- writer → `paper-writing`
- analyst → `result-analysis`（首选 [steipete/oracle](https://github.com/steipete/oracle) 的浏览器引擎，回退人工交接；不走 API）

委托前先运行 `python3 tools/model_routes.py delegate TASK`，按输出的触发条件、可发送/须隐去的材料、调用方式和提示骨架执行。规程数据只在 `tools/model_routes.py` 的 `DELEGATION` 维护。

必须做：
- 只发送规程允许的材料，每次开新会话；不同候选、不同任务不共用会话。
- 保存完整 prompt、原始响应和实际返回身份（未知写 unknown）。
- 收到结果后按规程的核查项逐条验证，通过前视为未验证，不写入证据、协议或状态。
- 调用后运行 `python3 tools/model_routes.py log-delegation`，计入 `policy.max_review_calls`。
- 受托方遇到协议偏差，退回给你决定；协议变更走新版本。

禁止：
- 传输不可用或调用失败时自己顶替，或换角色；标 blocked 并告知用户。
- 把评审自己委托并整合的结果当作独立评审；评审只走隔离包。
- 通过委托绕过门禁；训练只经 `research.py run`。

## 冻结协议与探索

所有会运行训练的 baseline/sanity/pilot/formal/analysis（main/ablation用formal阶段并在配置中标明variant） 都先绑定对应协议。真实方法 pilot 前还须 baseline 通过、idea 决策、novelty 核查和必要评审。协议包含独立定义的成功、失败、证据不足三种判定；失败不是未成功的机械反面。

冻结协议 `contracts/<idea_id>/vN.yaml` 不原地修改。新版本记录原因、时间、已见结果、前版本、受影响运行和判据变化；旧运行永远保留旧引用。根据已见结果提出的新 hypothesis 标为 exploratory，不能追溯包装为 confirmatory。原生 `idea-stage/docs/research_contract.md` 可更新进度和结果，仅引用冻结协议。

新协议显式填写 `provenance.hypothesis_basis_runs`；形成假设所依据的已见运行同时列入 `observed_runs`，不因换 idea_id 而重新标为 preregistered。纯背景观察与独立确认研究单独表达，不一概归为 exploratory。历史导入协议不为新增字段修改原字节或追认冻结。

每次探索循环记录：问题→现有证据→竞争解释→可区分解释的新实验→预期信息→成本→停止条件→结果→认识。失败是研究记忆，不删除。达到预算、review 轮数、资源缺失、关键输入缺失、判据变更时停止自动推进并写明阻塞。

## 可靠运行与恢复

安装、下载前先读资源登记（数据、权重、环境、GPU），优先复用已存在版本；没有登记不能静默下载。密钥仅从环境变量或私有配置读取，不写日志和仓库。数据、权重、大型产物不进源码仓库。

长任务用独立工作进程；远程使用 tmux 或现有调度器。区分 training、waiting_resource、stalled、exited、failed、interrupted；使用有界超时/重试，所有尝试计入总预算。恢复先查进程/调度器与已有产物，不重复提交 active 或 completed 任务。不因 PID 不可见就假定远程任务已经退出。

科学接受和执行完成分开：原生 `done` 表示已执行/已写文件，`accepted` 需要确定性检查或合格独立评审的证据。确定性检查只接受它确实能验证的工程事实，不判断 novelty、有效性或可发表性。不能绕过 gate 直接编辑状态为 accepted。
