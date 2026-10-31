# 已做假设与待配置事项

本项目已从 `research idea icl` 导入真实 ICL 历史研究与原始证据，研究问题、pi0 / 原生 ContextFlow baseline、`icl-bridge-midtraining` 方向和资源路径已有登记。历史 seed42 四臂训练、v2/v3 评测及其负结果和限制按原字节保留，导入状态为 pending ARIS acceptance；不据此补造冻结登记、独立评审 receipt 或论文 claim。下一方向 P_S/L seed43 的协议仍为未冻结草案，尚未执行。真实训练预算继续关闭，数据/环境/资源复核、baseline接受链、候选选择、novelty、代码/结果评审及新协议仍须完成；复制历史材料和本轮配置同步不授权新增训练或外部支出。

离线入口只需Python>=3.10、bash、git。执行器本次限定Linux/POSIX本地Python；必须在登记的Python解释器中启动，job.command[0]使用{python}。包版本清单属于该解释器环境。shell激活、容器、远程调度尚未接入自动验证。若目标环境缺少/proc，后台恢复用os.kill(pid,0)只能观察进程是否存在，不能充分核验PID身份；此时保留queued/running并标process_identity_verified=false，绝不因此宣称完成或重复提交。当前环境以最新reports/doctor.json为准，历史报告保留原环境信息。

模型偏好按共同规则配置：Antigravity检索/生成、Claude Code评审、Codex实现/写作，Claude Code主持，GPT Pro / Ultra人工分析。MCP已登记Codex、Antigravity和claude-review；本地路径及initialize/tools-list协议检查以 `reports/configuration-sync-20261029/report.json` 为准，未调用外部模型或探测账号，实际model_id/provider/model_family仍为空。ChatGPT Ultra是产品称呼，不能推断API ID。人工评审显式记录human，不能当作跨模型运行测试。导入的identity证据是带原始附件的声明，需接入方核实真实性；不是密码学身份认证。

指南原文中的模型相对能力、ensemble普遍收益和个别案例结果仅视作作者观点，未独立核实，不作为项目假设或验收结果。已有论文库与用户insight可用作来源，权重取决于相关性和证据质量。

历史交付环境缺少/dev/fd，原生安装器曾失败：Claude已完成链接后最终shell验证失败；Codex在inventory阶段失败。init保留失败日志，并以Python核验Claude原生manifest、按上游文档建立完整Codex pack的原生flat links与manifest。vendor源码未改。当前init先检查全部已管理内容，在独立目录运行上游安装器，再应用当前项目链接及路径；显式登记的本地定制从项目canonical文件安装。发行zip将链接展开为副本，解压后init会恢复项目链接并保留登记的定制。

预算采用超时上限保守预留，不自动退还失败任务额度；CPU/GPU时间与费用不是硬件计费系统。本地cpus及线程变量是声明及软约束，未做cgroup硬隔离；真实GPU利用率/云账单须由调度器/provider进一步核验。模型费用与外部手工调用无法从本地launch账本自动核验；设置review总次数与轮数，外部付费调用必须另按授权模型预算执行。

工具校验证据结构、来源路径/指纹、新鲜度和状态，不能证明来源内容真实、统计结论正确或novelty成立。科学/实现/统计问题仍需要独立评审和ARIS原生审计；done/completed不是accepted。
