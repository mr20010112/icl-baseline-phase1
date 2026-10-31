# 远程执行交接（未验证）

此交接不自动SSH、申请GPU或付款。先在目标服务器拷贝本项目，在当地登记数据/环境/资源和预算，运行init与doctor，并使用登记的Python解释器。数据与权重只登记路径，不随源码传输。

ContextFlow 独立导出包的完整配置与评审往返见 [第三方指南](../third-party/README.md)。`contracts/baseline/v1.yaml` 已冻结，不得重新冻结；先替换 `configs/research.json:baseline.repo_path` 占位符并登记目标机器资源。

远端必须使用tmux或已有作业调度器。tmux调用形式与固定版本 `vendor/aris/docs/WATCHDOG_GUIDE.md` 相同：

```bash
cd /absolute/path/to/icl-baseline-runner
# Replace the interpreter with the registered ContextFlow Python 3.11 path.
timeout 600 tmux new-session -d -s cf-seed42 \
  "/absolute/path/ContextFlow/.venv/bin/python tools/research.py run --job experiments/baseline-seed42.json --foreground"
timeout 600 tmux attach -t cf-seed42
```

路径、Python环境、session名和job须由资源拥有者填写；此处不是已执行记录。先检查同名session与已有run，禁止重提同一task。调度器优先使用现成集群流程，并记录job ID、配置、进程/调度状态、日志与退出码。作业也必须经过项目run入口；不要绕过协议、评审和预算门禁。

tmux 启动命令在 600s 内返回；后台 launcher 按冻结协议限制执行时间。seed42 完成并检查证据后，再依次提交 `experiments/baseline-seed43.json` 与 `experiments/baseline-seed44.json`，每个 seed 使用自己的 accepted code-review receipt。环境变量传入 tmux 的完整步骤见第三方指南。

完成后连同contracts登记、run完整目录、分析和资源验证记录一起同步回来。跨机器导入应保留原命令/绝对路径为历史，重新检查代码/配置/原始指标的指纹，并让reviewer直接读取。当前没有验证跨机器自动合并、调度器API、GPU内核或tmux安装，不能标成通过。
