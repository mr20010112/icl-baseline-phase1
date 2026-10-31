# 指南要求—ARIS 能力—补充实现—验证

上游路径以固定 commit 为准，完整依据见 `upstream-review.md`。新增工具的具体接口见 README；本表区分原生能力与项目加强项，不把模板存在算作集成已完成。

| 指南/用户要求 | ARIS 原生能力 | 项目补充实现 | 验证方式 |
|---|---|---|---|
| 保留指南、方法原则落地 | Markdown skills 可组合 | 原文逐字副本与 fingerprint；本项目共同规则和登记的本地技能 | 原文件 byte/hash 对比 |
| 文献真实来源与知识类型 | `/research-lit`、`verify_papers.py`、citation discipline | 按问题、章节、知识类型、核实证据组织记录 | 文献记录字段/来源检查；联网核查在接入后执行 |
| 相关与交叉领域上下文 | `/research-lit` 多源搜索、wiki | 搜索矩阵与分阶段阅读；已有库不默认加权 | 检查覆盖范围与未核实标记 |
| baseline 先复现 | Experiment Bridge sanity→baseline | baseline 前置门禁、论文值/复现值分离、数据环境评测检查 | 无资源/无复现结果不得通过 |
| 约 10 idea 与逐个独立 review | `/idea-creator`、`/research-review` | project-research入口、干净proposer包、一候选一白名单评审包；五维scorecard；selection_record完整池/排序/修订证据 | 校验候选数量、指纹、独立receipt、全体排名及最高go；隔离包排除其他候选 |
| 可替换多模型角色 | reviewer backend 选择、MCP、manual route | 共同规则/model配置/原生路由一致性检查；角色偏好与实际身份分离；人工导入与身份凭据 | 同 family / unknown 不能成为跨模型接受 |
| architect 收敛 | MAX_ROUNDS、review gate | 显式预算、轮数和决策理由 | 达上限停止；评分不作实证证据 |
| pilot 之前冻结协议 | 原生 W1 可能先 pilot；working contract 可变 | 分步 W1、所有训练类型均需版本化冻结协议 | 未冻结 pilot/main/baseline 拒绝启动 |
| 成功/失败/不足独立判据 | Experiment Plan/contract 模板 | 稳定signal ID、统计容差、逐signal判定与原始证据、独立结果评审 | 缺ID/漏判/未知signal拒绝；判据科学独立性由评审核查 |
| 旧实验保留旧协议 | 原生产物版本与追踪 | run 绑定路径和 fingerprint，新版本变更说明 | 误改检测；v2 后旧 run 仍引 v1 |
| 方法与实现对应 | `/experiment-bridge` code review | 模块映射、execution绑定及代码快照入口 | 未审入口/改命令/配置或快照漂移阻塞 |
| 每指标可追溯真实执行 | Experiment Log、evidence_check | manifest、命令、环境、seed、快照、原始输出索引 | CPU toy 实算→报告→原始指标与配置回溯 |
| 失败/中断/负结果保留 | tracker、watchdog、Findings、wiki | 全部尝试保留，缺指标不造数 | 非零退出、超时、缺指标不得成功 |
| mock/toy/real 分离 | experiment-integrity 的 evaluation types | 显式运行类型；toy 排除科研 claim | toy→正式 claim 引用拒绝 |
| 分析性实验推动 idea 演化 | `/result-to-claim`、`/ablation-planner`、W2 | 竞争解释、成本、停止和hypothesis_basis_runs来源登记；跨idea结果依赖不重置分类 | 分析模板/协议分类检查 |
| claim 必须有实验与分析证据 | result-to-claim、paper-claim-audit | claim→signal_ids→逐项分析→原始run；结果评审绑定完整材料 | 未知signal、缺判定/独立receipt、材料漂移拒绝 |
| 资源登记优先复用 | compute-env-contract、provider ledger | 数据/权重/环境/GPU 配置与 preflight | 缺资源阻塞，离线诊断可运行 |
| 长任务、超时与有界重试 | `/run-experiment`、queue、watchdog | 本地独立 worker、预算预留、心跳/退出状态；远程交接 | 超时/中断/预算/重复提交故障测试；远程集成未验证 |
| 新会话恢复 | `.aris/runs`、run_state、REVIEW_STATE | 简洁恢复视图，只读当前 idea | 恢复不重复 active/completed 任务 |
| 项目级固定安装与迁移 | 两个宿主安装器、manifest、helper resolver | 固定上游副本/记录、重建链接 | 初始化重跑与迁移目录检查 |
| 真实工程验证 | 上游 tests 和确定性 gates | 新门禁的必要测试与 CPU toy | 真实测试日志、验收报告，未测集成显式列出 |

适用边界：脚本检查证据结构和执行事实；科学有效性、novelty、评测设计与数据泄漏仍需独立评审直接读取原始资料。模型 PASS 也只是有范围的第二意见。

ICL历史研究按 `reports/imported-icl/` 原始材料与清单保留；上述新门禁不追认旧协议或补造接受。本轮配置同步的本地检查见 `reports/configuration-sync-20261029/report.json`，外部模型实际调用未验证。
