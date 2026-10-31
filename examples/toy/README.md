# CPU toy 示例

此目录只验证计算、配置、协议、日志、原始输出和报告之间的工程证据链。它使用纯 Python 在 CPU 上拟合合成数据 `y = 2x + 1 + noise`，不代表真实研究结果或 baseline 复现。

使用项目入口 `python3 tools/research.py smoke`。启动器提供 `RESEARCH_RUN_DIR` 和 `RESEARCH_SEED`；训练脚本接收 `--config <JSON文件>` 与可选 `--seed <整数>`。配置必须包含 `"kind": "toy"`；可设置 `n_train`、`n_test`、`epochs`、`learning_rate` 和 `noise_std`。默认值仅用于工程演示，不是科研推荐超参。

运行会保存 `metrics.json`、`predictions.csv`、`trajectory.json`、`model.json` 和 `progress.json`。可由 `predictions.csv` 独立重算测试集 MSE；`trajectory.json` 记录每轮真实计算的训练误差。`--fail`、`--missing-metrics`、`--sleep` 只用于故障注入测试。

固定 seed 在当前 Python/CPU 环境下给出可重算结果。项目不承诺不同硬件、解释器或数学库之间逐位相同；正式研究应预先写明容差、重复次数和统计判据。
