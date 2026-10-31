# 冻结协议字段说明

协议采用 JSON 语法，扩展名 `.yaml`：JSON 是 YAML 1.2 子集，离线检查只需 Python 标准库。请勿在此格式内写 YAML 注释；解释放在本文。填写文件按 `contracts/<idea_id>/vN.yaml` 命名。样例文件是示例，不是已冻结的真实研究协议。

| 字段 | 说明 |
|---|---|
| `idea_id`, `version`, `kind` | 稳定标识、正整数版本、`real`/`toy`/`mock`，不得混用 |
| `question`, `hypothesis` | 研究问题与可证伪预测，不能仅写“有提升” |
| `method.description` | 方法与原文/设计的对应说明 |
| `method.implementation` | 计划实现文件或 `{path,symbol}` 列表；启动时必须有实际文件 |
| `metrics.primary`, `metrics.secondary` | 名称、定义、方向、单位、聚合方式；次要指标无则明确 `[]` |
| `data` | 数据身份、版本或fingerprint与 `split`；说明预处理和泄漏检查 |
| `baseline` | 对照定义、论文值来源与本项目复现引用；未知不可伪填 |
| `hyperparameters` | 关键超参及允许变化范围，明确调参预算和依据 |
| `seeds` | 整数列表或含 `values` 的方案；定义方差估计与缺seed处理 |
| `success_signals` | 提前定义改善幅度、比较方向、区间/统计检验和样本范围 |
| `failure_signals` | 独立定义反证或实际失败，例如预定义干扰下崩溃；不是“没成功” |
| `inconclusive_signals` | 缺数据、seed不足、区间跨阈值、scope不足等证据不足条件 |
| `ablations` | 每个消融改变什么、预期区别哪些机制；不做时明确原因，不能留空冒充规划 |
| `budget`, `stopping` | 含 baseline、pilot、失败重试、正式与追加分析的成本上界、超时和停止理由 |
| `provenance.mode` | `preregistered` 或 `exploratory`；基于已见结果写的新版本要披露探索性质 |
| `provenance.observed_runs` | 写协议时已经见过的真实 run ID；无则 `[]`，不能隐瞒同idea既有结果 |
| `provenance.hypothesis_basis_runs` | 新协议必填列表：形成当前假设所依据的已见结果 run ID，包括其他 idea 的失败；无依赖时显式 `[]`。必须是 observed_runs 的子集；非空时 mode 必须为 exploratory。仅作背景或独立确认研究的观察放在 observed_runs，另说明其用途，不冒充假设形成依据 |
| `amendment`（v2起） | `previous`、`reason`、带时区的 `created_at`、`seen_results`、`impact`；已见结果与 provenance 一致 |

硬件容差填写示例（仅形式）：主要指标按多seed聚合，预定义绝对/相对容差、置信区间及比较规则；具体数值必须由任务、原文与资源决定，不沿用 toy 的数值。脚本能验证字段存在和版本链，判据是否有科学意义仍由独立 reviewer 判断。

冻结后改字节会被检测。请复制成 v2 并补变更说明，不修改登记文件以规避检测。运行在启动时绑定冻结版本，后续升级不改变旧 run 的协议引用。工作文档 `idea-stage/docs/research_contract.md` 可更新当前结果，但不能充当改判据的入口。

真实协议另强制 statistics.metric/aggregation/atol/rtol/statistical_rule/hardware_scope；容差必须有限非负。baseline比较必须使用冻结的metric/atol/rtol/statistical_rule，不能结果出来后改变。统计方法是否恰当仍需独立评审。

每类 signal 都是非空列表，每项必须含 `id`、`rule` 和非空 `metrics`（冻结指标名列表）。ID 在整个协议内唯一；同一 idea 的后续版本保留同 ID 时，类别、规则和指标不得改变。改变判据必须使用新 ID 并填写版本修订信息。例如：

```json
{"id":"heldout-improvement","rule":"按预定统计方案比较留出集误差","metrics":["mse"]}
```

每份分析必须在 `signal_results` 中恰好判定全部 signal 一次，状态为 `met`、`not_met` 或 `inconclusive`，并给出理由与原始证据。证据为 `{run_id,metric}`，或针对失败/不足使用 `{run_id,artifact}`（运行目录内且受产物索引校验的文件）。分析结果的科学意义由独立结果评审确认，字段存在不能代替判断。格式见 `analysis.example.json` 和 `analysis-question.md`。

历史冻结文件不会自动添加 ID 或重写字节。其哈希仍可验证；进入新的分析/接受门禁时，应建立新版本，披露已有结果并使用稳定 ID，不能补写历史预注册。

历史冻结协议缺少 `hypothesis_basis_runs` 时仍可 `verify`，重复 `freeze` 只核验已有字节，不改写或重新分类历史。新冻结协议及新版本必须显式填写该字段；不要回填旧文件。脚本检查所声明的依赖与分类一致性，是否漏报形成假设的结果仍需独立 reviewer 读取研究记录核查。
