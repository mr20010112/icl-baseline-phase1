# ContextFlow 第三方操作指南 / Third-party operator guide

中文：本指南在第三方自己的机器上本地执行。v1 和 v2 均已冻结，登记在 `contracts/.registry.json`；当前 job 绑定 `contracts/baseline/v2.yaml`，v1 仅保留版本链。操作员不得手工创建、修改或重新冻结任何协议；唯一例外是负责人授权的 tools/amend_limits.py 后继时限版本，须披露并重新批量代码评审；其他必要变更均退回项目负责人，以新版本处理。原冻结协议保持原字节，registry 只由授权工具追加后继登记。本交付未运行训练、评测或下载。不得把示例、CPU 测试、dry-run、论文值或历史结果当作新复现结果。先由项目负责人确认执行者身份，再完成独立代码评审与预算授权。本文中的安装/下载命令是操作说明，并未由本次实现执行。

English: execute locally on your own machine. Both v1 and v2 are already frozen in `contracts/.registry.json`; v2 is active and v1 is retained only for the version chain. Operators must not create, edit or re-freeze any protocol by hand. The sole owner-authorized exception is a disclosed limit successor created by tools/amend_limits.py; fresh batch code review is required. Return every other needed change to the project owner as a new version. Preserve all existing frozen protocol bytes; only the sanctioned tool appends successor registry entries. Resource, review and budget gates still apply. This delivery has not trained, evaluated or downloaded anything. Examples, CPU fixtures, dry-runs, paper numbers and historical runs are not reproduction evidence. The project owner must confirm implementer identity before independent code review and authorized execution. Installation/download commands below are instructions, not claims of completed work.

## 第二阶段补充 / Phase-2 supplement

原 self-config 问题已解决：60 个 job 分别引用 60 个独立的
`experiments/phase2/configs/<task_id>.json`；配置无 operator 字段，receipt 回填只改 job。
生成与真实执行绑定回归见 [07 Resolution](../../reports/phase2-impl-07-materialize/REPORT.md#resolution)。

中文：以下 v2 的 60 小时、1 CPU 和 6 次尝试说明仍只适用于第一阶段。
第二阶段的 60 个 job 及全部参数定义见
[experiments/phase2/README.md](../../experiments/phase2/README.md)，单一参数来源为
`experiments/phase2/job-params.json`，统一 16 CPU、1 GPU、96 小时 timeout、2 小时 stall。
四个协议的计划/尝试数为 v3=36/72、v4=9/18、v5=9/18、v6=6/12；每次预留
5529600 CPU 秒、96 GPU 小时，美元估算 0。新上限尚未写入任何冻结协议或启用预算。
操作员只可填写 job 的 `environment_id`、`resource_id`、`code_review_receipt`、
`executor_identity`；环境/算力 ID 从自己机器的 verified registry 取得，不能编造。
资源与身份在评审前确定，receipt 在实际导入评审后回填。资源/身份在评审后改动也会改变执行绑定；
改动其他 job 字段使配置失效，须交回 architect 重新生成并评审。保留 registry/协议/数据指纹规则。
第二阶段 v3–v6 仍是待另行编写/冻结的协议路径；未收到负责人确认第一阶段验收通过的书面放行，
不得启动任何第二阶段 job。生成和 `--check` 都不授权执行。

English: the v2 instructions below retain their phase-1 limits. Phase 2 uses the
single parameter file and specification linked above: 16 CPUs, one GPU, 96 h
timeout, 2 h stall; 5529600 CPU seconds and 96 GPU hours per attempt, zero dollar
estimate. Operators may fill only `environment_id`, `resource_id`,
`code_review_receipt` and `executor_identity`. IDs must come from their own
verified registry. Set resources and identity before review; attach the actual
imported receipt afterward. Changing bound resources/identity after review or
any other execution field requires regeneration/review. No phase-2 run before
the owner's written release after phase-1 acceptance; protocols and budgets
still require separate authoring, freezing and authorization.

第二阶段操作顺序 / Exact phase-2 procedure:

1. 负责人提供并冻结 v3–v6，重新物化 60 job + 60 config（config 中 protocol_placeholders 清空），完成第一阶段验收/书面放行与预算授权。操作员不改任何 config。
2. 在 job 填本机 verified registry 的 environment_id/resource_id；executor_identity 也必须在评审前确定。配置 SHA256 不变，但这些值会建立执行绑定。
3. 使用登记解释器运行 `timeout 600 "$OPERATOR_PYTHON" tools/research.py context-pack --idea baseline --purpose code-review --job "$PHASE2_JOB"`，独立评审该包。
4. 收到真实评审后运行 `timeout 600 "$OPERATOR_PYTHON" tools/research.py import-review --package "$REVIEW_PACKAGE" --result "$REVIEW_RESULT"`，只在 job 回填实际 code_review_receipt 路径。不得改独立 config。
5. 所有门禁通过后，经 `tools/research.py run --job "$PHASE2_JOB"` 启动（长任务按下文后台提交规则）。runner 只读取 RESEARCH_CONFIG 指向的 runs/<task_id>/config.json；dry-run 则读取 job.config。

这里的 shell 变量由操作员设为本机实际路径，示例没有执行。只有 receipt 回填（及 JSON 格式变化本身）可以在评审后改变 job 字节而不改变执行绑定。
**executor_identity 的值不是解绑字段**：如 import 后才发现需要更正身份，先更正再重新 context-pack/评审；不能靠同时回填 receipt 绕过身份绑定。environment/resource ID 或 registry 变更也须重评。
English: register environment/compute and establish executor identity **before**
context-pack; import the independent review; fill only the receipt path; then
run under the registered interpreter after every gate passes. Receipt attachment
changes job-file bytes without changing the config hash or binding. If executor
identity needs a value change after import, obtain a fresh review first. Do not
modify any separate config after review. Real runners read only the bound run
copy selected by RESEARCH_CONFIG.

第二阶段共享评测路径统一从环境读取，禁止把本机路径写入
`eval/shared_client/config.json` 或 `evaluation-params.json`。唯一变量表见
[shared-client portable path table](../../eval/shared_client/README.md#portable-definition-and-operator-paths-task-08)：
SHARED_EVAL_PYTHON、PHASE2_LIBERO_ROOT、PHASE2_BPP_ROOT、PHASE2_LIBERO_CONFIG_DIR
及 BPP transport/既有 ContextFlow 变量。LIBERO HEAD 固定 8f1084e3…，BPP HEAD 固定 3471dcf…；
未设置路径或提交不符会直接失败。共享 client 的 LIBERO_CONFIG_PATH 由
PHASE2_LIBERO_CONFIG_DIR 产生，不继承训练的 staged 配置。

科学评测参数唯一来源是 `eval/shared_client/evaluation-params.json`；config.json 仅保留
运行参数和该定义的相对引用。协议作者可冻结两个 portable 文件的 SHA256；操作员不改原文件。
每条 trial 同时记录 evaluation_params_sha256 与 effective_config_sha256（保留旧 config_sha256）。
`timeout 600 python3 -B -m eval.shared_client.client --print-evaluation-sha256` 只打印科学定义哈希，
不执行评测。打包审计中其余源码/历史材料的机器路径见 task-08 报告；本次不改 exporter 行为。

## 1. 硬件和项目 / Hardware and project

中文：Linux/POSIX、bash、git、tmux、uv、Python ≥3.10 用于项目工具；官方训练环境为 Python 3.11，LIBERO 客户端为 Python 3.8。每个 job **恰好一张**兼容官方 JAX CUDA 12 栈且显存 ≥40 GB 的 NVIDIA GPU，推荐 A100 80GB/H100，GPU 独占。32GB 显存不符合 v2。官方配置有 64 个 data-loader workers；主机需有足够 CPU、内存和进程额度，不可减少 batch、workers 或采样参数以“修复”OOM。建议预留 ≥128 GB 主机内存和数百 GB 可用磁盘，并按实际 checkpoint/video 增长留足空间；这些容量建议尚未实测。总数据 34,938,927,454 bytes，另需临时下载区、pi0 权重、三次运行和重试产物。

English: use Linux/POSIX, bash, git, tmux and uv; project tools need Python ≥3.10. Training uses official Python 3.11; the simulator client uses Python 3.8. Each job uses **exactly one** exclusive NVIDIA GPU with ≥40 GB VRAM and support for the official CUDA 12 JAX stack; A100 80GB/H100 are suitable examples. A 32GB card is outside v2. The official config starts 64 data-loader workers: provide sufficient host CPU, RAM and process limits. Do not change batch/workers/sampling to work around failures. Provisioning ≥128 GB RAM and several hundred GB free disk is a planning recommendation, **unverified** here. The data alone is 34,938,927,454 bytes; also retain staging, weights, checkpoints, videos and retry artifacts.

中文：所有尖括号/`/absolute/path/...` 都必须替换。向项目负责人索取独立 `icl-baseline-runner` 导出仓库 URL 和 reviewed commit，或完整导出归档；公开 clone URL 尚未建立。本包包含 vendor、已冻结的 v1/v2、原始 registry 和唯一绑定论文，不含官方 checkout、数据、权重或原机器运行/安装状态；`.claude/`、`.agents/`、`.aris/` 由 init 在本机生成。以下变量只存在于本机 shell/私有启动文件，不写入 reviewed job/config。

English: replace every placeholder. Obtain the standalone `icl-baseline-runner` export URL and reviewed commit, or its complete export archive, from the project owner. No public clone URL has been established. The package includes vendor, both frozen protocols, the original registry and the bound paper. Supply your own official checkout, data and weights; init generates `.claude/`, `.agents/` and `.aris/` locally. Keep machine paths in your shell/private setup and resource registry, not reviewed jobs/config.

```bash
timeout 600 git clone <PROJECT_REPOSITORY_URL> /absolute/path/icl-baseline-runner
cd /absolute/path/icl-baseline-runner
timeout 600 git checkout <REVIEWED_PROJECT_COMMIT>
export PROJECT_DIR="$PWD"
export CF_REPO=/absolute/path/ContextFlow
export DATA_STAGING=/absolute/path/libero-download-staging
export LEROBOT_ROOT=/absolute/path/lerobot-data
export OPENPI_DATA_HOME=/absolute/path/openpi-cache
export CONTEXTFLOW_CHECKPOINT_SCRATCH=/absolute/path/operator-checkpoint-scratch
export CONTEXTFLOW_LIBERO_PYTHON="$CF_REPO/examples/libero/.venv/bin/python"
export CUDA_VISIBLE_DEVICES=0
export CONTEXTFLOW_SERVER_PORT=8000
export MUJOCO_GL=egl
export WANDB_MODE=offline
export PYTHONDONTWRITEBYTECODE=1
timeout 600 python3 tools/research.py init
timeout 600 python3 tools/research.py doctor
timeout 600 python3 tools/research.py validate
timeout 600 python3 tools/research.py contract verify
timeout 600 env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

中文：若使用归档，省略 git clone/checkout，记录归档 SHA256。init/doctor 不证明科研资源已通过。重试安装前先检查已有环境和输出，不删除失败证据。

English: for an archive, omit clone/checkout and record its SHA256. init/doctor do not certify research readiness. Inspect existing installations before retrying; retain failure evidence.

中文：独立包不含原项目可选的本地 agent skills，`configs/local-overrides.json` 两个列表为空；baseline 命令使用原生安装与项目门禁。

English: optional owner-specific agent skills are omitted and both local customization lists are empty. Baseline commands use the native installation and project gates.

中文：导出包 `.mcp.json` 使用 portable 值；init 将其改成本机解释器/路径并生成 reviewer 路由。外部模型 CLI 可缺失，本操作员流程通过手工评审往返，不调用它们。本机生成文件与资源配置可包含本机路径；原机器路径审计只覆盖交付时的已提交文件。`EXPORT_MANIFEST.json` 是交付快照，init/配置后不再是当前工作树指纹。

English: the shipped MCP config uses portable values; init rebases it and generates the reviewer route. External model CLIs are optional for this manual review round-trip and are not invoked. Local generated files/resource configuration may contain local paths; the owner-path audit covers the committed delivery. `EXPORT_MANIFEST.json` describes the delivery snapshot, not the working tree after init/configuration.

中文：在未配置的导出包执行 runner dry-run，预期 exit 2：`Missing evidence: <OPERATOR_CONTEXTFLOW_CHECKOUT>`。按提示设置 `configs/research.json:baseline.repo_path` 为自己的官方 checkout 绝对路径；这不表示数据、权重或算力已核实。每次 dry-run 使用新的输出目录。

English: an initial runner dry-run is expected to exit 2 with `Missing evidence: <OPERATOR_CONTEXTFLOW_CHECKOUT>`. Set `configs/research.json:baseline.repo_path` to your verified official checkout's absolute path. Data, weights and compute still require registration; always use a fresh dry-run directory.

中文：`CONTEXTFLOW_CHECKPOINT_SCRATCH` 必须是 run 和官方 checkout 之外的绝对路径；无需放在源码仓库。runner 用官方 `--checkpoint-base-dir` CLI override，保持 `save_interval=5000`、`keep_period=5000`，通常保留 5000/10000/15000/19999 的完整训练 checkpoint（含 optimizer）。按官方模型配置估算：2048 宽 prompt expert、1024 宽 action expert、SigLIP So400m、词嵌入和 4/2/2 层压缩器合计约 2–2.5B 参数；单份 params/assets 约 **8–12 GB**（混合 FP32/BF16、Orbax 开销/压缩依实际文件为准），含 Adam 状态的完整 checkpoint 约 25–35 GB。每个保留尝试建议 **至少 200 GB scratch**（四份 checkpoint 加异步写入余量），3 个 seed 约 600 GB；重试再加同样空间。run 盘另留每 seed 约 8–12 GB checkpoint 及视频/日志空间。此为静态容量估算，未运行训练测量；实际以 `checkpoint/checkpoint-sha256.json` 的 bytes 总和为准。不要修改保存频率或清除旧证据节省空间。

English: `CONTEXTFLOW_CHECKPOINT_SCRATCH` must be an absolute path outside both the run directory and official checkout. The runner uses the official `--checkpoint-base-dir` override, retaining save_interval/keep_period=5000: full checkpoints normally remain at 5000/10000/15000/19999, including optimizer state. From the official 2048-wide prompt expert, 1024-wide action expert, SigLIP So400m, embedding and 4/2/2-layer compressors, plan roughly 2–2.5B parameters: **8–12 GB** for the returned params/assets payload, and about 25–35 GB per complete training checkpoint. Allow **at least 200 GB scratch per retained attempt**, roughly 600 GB for three seeds, plus the same allowance for each retry. The run disk additionally needs 8–12 GB per seed for copied weights plus videos/logs. These are static planning estimates, not measured training sizes; sum actual manifest bytes after execution. Preserve save settings and prior evidence.

## 2. 官方两个环境 / Both official environments

```bash
timeout 600 git clone --recurse-submodules https://github.com/dingjiansw101/ContextFlow.git "$CF_REPO"
timeout 600 git -C "$CF_REPO" checkout c6dee891f0afd520aec5a8869891e9b06b99f856
timeout 600 git -C "$CF_REPO" submodule update --init --recursive
cd "$CF_REPO"
timeout 600 env GIT_LFS_SKIP_SMUDGE=1 uv sync --python 3.11 --frozen
timeout 600 uv venv --python 3.8 examples/libero/.venv
timeout 600 uv pip install --python examples/libero/.venv/bin/python \
  -r examples/libero/requirements.txt -r third_party/libero/requirements.txt \
  --extra-index-url https://download.pytorch.org/whl/cu113 --index-strategy=unsafe-best-match
timeout 600 uv pip install --python examples/libero/.venv/bin/python \
  -e packages/openpi-client -e third_party/libero
export CF_PY="$CF_REPO/.venv/bin/python"
export PYTHONPATH="$CF_REPO/src:$CF_REPO/third_party/libero:$CF_REPO/packages/openpi-client/src"
cd "$PROJECT_DIR"
timeout 600 mkdir -p reports/third-party
timeout 600 git -C "$CF_REPO" rev-parse HEAD > reports/third-party/checkout.log
timeout 600 git -C "$CF_REPO" status --porcelain >> reports/third-party/checkout.log
timeout 600 "$CF_PY" - <<'PY' > reports/third-party/environment.log 2>&1
import sys, importlib.metadata
from openpi.training import config
print(sys.executable, sys.version)
for name in ('jax', 'flax', 'torch', 'lerobot', 'tyro', 'orbax-checkpoint'):
    print(name, importlib.metadata.version(name))
print(config.get_config('ContextFlow'))
PY
timeout 600 "$CONTEXTFLOW_LIBERO_PYTHON" --version >> reports/third-party/environment.log 2>&1
timeout 600 "$CONTEXTFLOW_LIBERO_PYTHON" "$CF_REPO/examples/libero/main_incontext.py" --help \
  > reports/third-party/client-help.log 2>&1
timeout 600 nvidia-smi > reports/third-party/compute.log 2>&1
```

中文：遵循该 commit 的 README 和 `examples/libero/LIBERO_README.md`；`--frozen` 防止安装改写锁文件。EGL、驱动和 LIBERO 资产路径必须配置好。`--help` 仅检查客户端导入/CLI，不运行 rollout。若 LIBERO 首次导入提示路径，按官方安装位置配置；保留配置和日志，不猜测成功。训练 Python、客户端 Python、锁文件和依赖兼容性均需在你的机器上验证。运行脚本时直接使用已安装解释器，避免 `uv run` 隐式同步环境。

English: follow the pinned README and LIBERO guide. `--frozen` prevents lockfile rewriting. Configure NVIDIA drivers, EGL and LIBERO asset paths. Client `--help` checks imports/CLI without a rollout. If LIBERO asks for paths on first import, use the official installed assets and retain the configuration/log. Both environments and dependency compatibility remain to be verified on your machine. Execution uses installed interpreters directly, avoiding implicit synchronization by `uv run`.

## 3. 固定数据和缓存 / Pinned dataset and caches

中文：先检查资源登记，复用已经完整且版本一致的数据。缺失时，下述操作由你显式下载到 staging，随后仅复制 manifest 列出的 1699 个文件到一个**不存在的新目录**。不要把 HF `.cache`、`.git`、证据文件或其他内容放进数据目录。不要下载 latest/main；snapshot 的 revision 必须固定。

English: inspect the registry first and reuse a complete matching payload if available. If absent, explicitly download to staging and copy only the manifest's 1699 files into a **new, nonexistent directory**. Keep HF `.cache`, `.git`, evidence and all extra files outside the payload. Never substitute latest/main.

```bash
timeout 600 "$CF_PY" - <<'PY'
import json, os, pathlib, shutil
from huggingface_hub import snapshot_download
manifest = json.loads(pathlib.Path('baseline/data/libero-hf-manifest.json').read_text())
stage = pathlib.Path(os.environ['DATA_STAGING'])
snapshot_download(repo_id=manifest['dataset'], repo_type='dataset', revision=manifest['revision'], local_dir=stage)
dest = pathlib.Path(os.environ['LEROBOT_ROOT']) / 'physical-intelligence/libero'
dest.mkdir(parents=True, exist_ok=False)
for row in manifest['files']:
    target = dest / row['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(stage / row['path'], target)
PY
timeout 600 python3 baseline/runner/verify_libero_data.py \
  --data-dir "$LEROBOT_ROOT/physical-intelligence/libero" \
  --output reports/third-party/data-verification.json
```

中文：校验必须包括每个文件的 size+sha256、完整文件集合及 `tools/gates.py:digest()`。预期 tree digest 为 `4ea70de6b864de0ce221abda7b403225aaa5a3cd1b45532af16dc701cced4c56`，不是 manifest 顶部旧的 metadata 指纹 `9d51…`。若下载被 600s 中断，可在 staging 恢复；复制/校验失败的目录先调查并保留证据，另用新的 clean 目录，不能忽略多余文件或 hash 错误。

English: verification covers every size/SHA256, exact file set and `gates.digest()` tree hash. Expected tree hash is `4ea70de6b864de0ce221abda7b403225aaa5a3cd1b45532af16dc701cced4c56`, not the manifest header's older `9d51…` metadata hash. Resume interrupted downloads in staging. Investigate partial copies and use a new clean destination after preserving evidence; never ignore extra files or mismatches.

中文：独立预下载 pi0_base params 和官方 PaliGemma tokenizer（不得用发布的 ContextFlow checkpoint 替代训练）。以下使用官方缓存 helper；runner 自身不会执行下载。下载超时可重新运行缓存准备命令，禁止在已提交 job 内补下载。

English: separately prepare pi0_base params and the official PaliGemma tokenizer. Released ContextFlow weights cannot replace retraining. These commands use the official cache helper; the runner does not download. Cache preparation can be retried before job submission.

```bash
timeout 600 "$CF_PY" - <<'PY' > reports/third-party/cache-download.log 2>&1
from openpi.shared.download import maybe_download
print(maybe_download('s3://openpi-assets/checkpoints/pi0_base/params'))
print(maybe_download('gs://big_vision/paligemma_tokenizer.model', gs={'token': 'anon'}))
PY
timeout 600 python3 - <<'PY' > reports/third-party/weights-verification.json
import json, os, pathlib, sys
sys.path.insert(0, 'tools')
from gates import digest
p = pathlib.Path(os.environ['OPENPI_DATA_HOME']) / 'openpi-assets/checkpoints/pi0_base/params'
files = sorted(f for f in p.rglob('*') if f.is_file())
assert files, 'missing params'
print(json.dumps({'path': str(p), 'fingerprint': digest(p), 'files': [
    {'path': f.relative_to(p).as_posix(), 'bytes': f.stat().st_size, 'sha256': digest(f)} for f in files
]}, indent=2))
PY
```

中文：记录权重来源、完整性与官方可读性验证，不要仅凭目录存在登记 verified。runner 每次另外保存全部 params 文件 SHA256。缓存 helper 会废弃旧缓存（pi0 路径 mtime ≤2025-02-03 UTC）；遇到此情况在提交前重新准备，runner 会拒绝过期缓存。

English: preserve source/completeness and official readability checks before marking weights verified; directory existence alone is insufficient evidence. The runner inventories every params file again. The official helper invalidates pi0 cache paths with mtime ≤2025-02-03 UTC; prepare a valid cache before submission, since the runner rejects expired entries.

## 4. 资源登记和预算 / Registry and budget

中文：独立包的 `configs/resources.json` 四组初始为空。添加下列 ID；若本机已有其他记录则保留它们。`environment_id=THIRD_PARTY_CONTEXTFLOW_PY311` 和 `resource_id=THIRD_PARTY_LOCAL_SINGLE_GPU` 是**有意的占位 ID**，必须替换为你的明确 ID，或在本机登记这些 ID，三个 job 与 research.json 同步。以下是 gates 要求的准确 JSON 结构示意，所有 placeholder 必须换成实测值。数据 version、split 必须逐字复制协议，不能缩写。

English: all four resource groups start empty in the export. Register these resources, preserving any unrelated local entries. The jobs' `THIRD_PARTY_CONTEXTFLOW_PY311` and `THIRD_PARTY_LOCAL_SINGLE_GPU` are **intentional placeholder IDs**: replace them consistently or explicitly register those IDs locally, updating all three jobs and research.json. This is the exact gate schema; replace placeholders with measured values. Copy data version and split verbatim from the protocol.

```json
{
  "data": [{
    "id": "libero-hf-a4336d58", "kind": "real", "status": "verified",
    "path": "<absolute LEROBOT_ROOT>/physical-intelligence/libero",
    "version": "a4336d589d589045d1c56423ffdf3b88a0e19b1f",
    "split": "<exact protocol.data.split>",
    "fingerprint": "4ea70de6b864de0ce221abda7b403225aaa5a3cd1b45532af16dc701cced4c56",
    "verification": {"evidence_file": "reports/third-party/data-verification.json"}
  }],
  "environments": [{
    "id": "THIRD_PARTY_CONTEXTFLOW_PY311", "kind": "real", "status": "verified",
    "path": "<absolute CF_REPO>/.venv/bin/python", "version": "<actual Python 3.11.x>",
    "verification": {"command": ["<absolute CF_REPO>/.venv/bin/python", "--version"],
                     "evidence_file": "reports/third-party/environment.log"}
  }],
  "compute": [{
    "id": "THIRD_PARTY_LOCAL_SINGLE_GPU", "kind": "real", "status": "verified",
    "backend": "local", "cpus": 1, "gpus": 1,
    "verification": {"evidence_file": "reports/third-party/compute.log"}
  }],
  "weights": [{
    "id": "pi0-base-params", "kind": "real", "status": "verified",
    "path": "<absolute OPENPI_DATA_HOME>/openpi-assets/checkpoints/pi0_base/params",
    "version": "official-pi0-base-recorded-sha256-inventory", "split": "initialization params only",
    "fingerprint": "<measured gates.digest(params directory)>",
    "verification": {"evidence_file": "reports/third-party/weights-verification.json"}
  }]
}
```

中文：环境 path 必须保留 `.venv/bin/python` 路径，不要 realpath 成系统 Python。compute backend 必须 local，因为本项目 launcher 在你的机器本地运行；不要填 remote。compute.cpus 可登记实际可分配数量，但 job.cpus 保持 1，这是 v2 预留预算所用的计费单位及 OMP_NUM_THREADS，**不是**限制官方 64 个 workers 的 OS 配额。job.gpus 始终 1，CUDA_VISIBLE_DEVICES 只暴露同一张 GPU。若实际需要不同 job CPU/GPU 预留，退回 architect 修订预算，不能直接增大 job 数字。

English: retain the venv interpreter path, not its resolved system-Python symlink target. Backend is local because the launcher runs on your machine. Compute registration can state actual available CPU capacity, but job.cpus stays 1: v2 uses it for wall-time reservation and OMP_NUM_THREADS; it is **not** an OS quota for the official 64 workers. Job.gpus stays 1; expose the same single device through CUDA_VISIBLE_DEVICES. Different job reservations require architect reconciliation before execution.

中文：设置 `configs/research.json` 的 `baseline.repo_path`、`data_id`、`environment_id`、`resource_id`，保持 baseline commit 不变。将 `baseline.validation_record` 指向基于模板 `templates/baseline-preflight.example.json` 的新真实记录：kind=real、精确 baseline_commit、data/environment/evaluation 各项 status=pass 和非空真实 evidence_file。evaluation 此处是客户端环境、CLI、任务协议准备检查，**不是**成功率；说明没有运行 rollout。未实际检查的项保持 pending，不复制旧 witness 冒充 pass。

English: set research.json's baseline.repo_path, data_id, environment_id and resource_id, retaining the pinned commit. Point baseline.validation_record to a new record based on the preflight template: real kind, exact commit, pass statuses and nonempty genuine evidence for data/environment/evaluation. Evaluation here certifies client/CLI/task-protocol readiness, **not** rollout performance. Keep unperformed checks pending; do not recycle historical witnesses as current passes.

中文：只有机器所有者批准真实计算后才在 `configs/budget.json` 开启 real_enabled。没有其他占用时，全局及 scopes.real 均至少为下列数值；已有 reservations 需计入全局额度，且不得超过协议上限。每次 60h × 1 GPU=60 GPU-h，6 次共 360；CPU 6 ×216000×1=1296000。estimated.gpu_hours=60 是每次含评测的保守计划额度（论文约40训练 GPU-h）；失败额度不返还，外部第三方机器费用不计项目美元支出。

English: enable real_enabled only after the machine owner authorizes compute. With no other reservations, use at least the following global and scopes.real allowances; account for existing reservations and never exceed the protocol cap. Six attempts reserve 360 GPU-hours and 1,296,000 CPU-seconds. The per-job estimate of 60 GPU-hours includes evaluation; paper-reported training is about 40. Failed reservations are not refunded. Third-party machine costs are outside this project's dollar ledger.

```json
{
  "max_cpu_seconds": 1296000, "max_gpu_hours": 360, "max_cost_usd": 0,
  "max_attempts": 6, "max_retries": 1, "real_enabled": true,
  "scopes": {
    "real": {"max_cpu_seconds": 1296000, "max_gpu_hours": 360, "max_cost_usd": 0,
             "max_attempts": 6, "max_retries": 1}
  }
}
```

中文：这是合并示例，不要删除其他 scope/历史预算。请勿把本指南的示例预算写回未授权的原机器。

English: merge this example without deleting other scopes/history. Do not enable compute budgets on the original unauthorized machine.

## 5. Dry-run、前检和评审 / Dry-run, preflight and review

```bash
timeout 600 env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
timeout 600 "$CF_PY" baseline/runner/contextflow_repro.py --seed 42 --dry-run \
  --job experiments/baseline-seed42.json --run-dir /absolute/path/new-contextflow-dry-run
timeout 600 "$CF_PY" tools/research.py baseline-preflight
```

中文：每次 dry-run 使用新目录；保存完整目录。只检查代码、数据/官方 split、缓存和解释器，打印归一化/训练/probe 服务/两个 pass（共四次客户端）评测命令，不执行这些命令。前检 PASS 仅说明准备完成。若任何条目不完整，停止并发回日志。

English: use a fresh dry-run directory and retain it. Dry-run checks checkout, data/official split, cache and interpreters, and prints normalization/training/probe-server and both passes (four client commands) without running them. Preflight PASS certifies preparation only. Stop and send logs if any required item remains incomplete.

中文：**冻结核验**：v1 和 v2 均已冻结；`context-pack --purpose code-review` 和 `run` 继续核验冻结登记。直接 verify 两个协议，不创建、修改或重新冻结任何协议，也不修改门禁。当前三个 job 均绑定 v2，v1 仅保留版本链；如需协议变更，退回负责人创建新版本。向我们索取可核实的 implementer identity 元数据并填三个 job.executor_identity；未知字段保持 null，不能猜模型名通过门禁。

English: **freeze verification**: both protocols are already frozen. Verify their existing registrations before code-review context-pack and run. Do not create, edit or re-freeze any protocol or change gates. All three jobs bind active v2; v1 is retained only for the version chain. Return needed protocol changes to the project owner as a new version. Obtain verifiable implementer identity metadata for all jobs; unknown fields stay null.

```bash
timeout 600 "$CF_PY" tools/research.py contract verify
timeout 600 "$CF_PY" tools/research.py context-pack --idea baseline --purpose code-review \
  --job experiments/baseline-seed42.json
```

中文：把命令返回的完整包（REQUEST、manifest、files、execution、result-template）发给项目负责人，另提供只读官方 checkout 的 commit 和相关原文文件以便评审直接核查。资源、环境变量清单、代码、配置须在评审前定稿，保持冻结协议不变。不得发送密钥、账号信息。负责人返回完整独立评审原文、实际 reviewer identity 证据和结果 JSON；先把引用证据放在双方约定的包内相对路径，再在本机导入：

English: send the complete exported review package to the project owner, plus access to the pinned official source files for direct inspection. Finalize resources, environment settings, code and config before review, retaining the frozen protocol unchanged. Exclude credentials. The owner returns the result JSON, complete raw review and actual reviewer identity evidence; place referenced evidence at the agreed package-relative locations before importing locally:

```bash
timeout 600 "$CF_PY" tools/research.py import-review --package <RETURNED_PACKAGE_PATH> --result <RETURNED_REVIEW_JSON>
```

中文：将返回的 accepted PASS receipt 路径填入 seed42 的 code_review_receipt。seed/命令不同会改变 execution binding，**不能把 seed42 receipt 复用给43/44**：对这两个 job 分别 context-pack、发回、import-review，填各自 receipt。只改 task_id/retry_of/receipt 不改变绑定；改路径资源、seed、代码或配置需重新评审。跨模型或明确独立人工评审才可 accepted；同 family/未知身份仅 provisional/blocked。

English: put the returned accepted PASS receipt path into seed42's code_review_receipt. Seeds/argv affect the execution binding: **seed42's receipt cannot cover seeds43/44**. Repeat package/export/import for each and attach its own receipt. Task ID/retry_of/receipt edits alone are unbound; resource paths, seed, code or config changes need a new review. Same-family or unknown reviewers cannot satisfy independent acceptance.

## 6. 提交、恢复、重试 / Submit, recover and retry

中文：按种子顺序串行运行，避免争用同一 GPU/端口。先确认同 ID 不存在 active/completed run，也没有同名 tmux session。下面命令仅在冻结、资源、身份、评审与预算全部通过后执行。tmux 启动命令自身在 600s 内返回；后台的项目 launcher 按绑定协议实施时限（原 v2 为 60h timeout/2h stall），不能给真正训练加 600s 截断。

English: execute seeds sequentially to avoid GPU/port contention. Check for existing active/completed runs and tmux sessions first. Submit only after freeze, resources, identity, review and budget gates pass. The tmux submission returns within 600 seconds; the detached launcher enforces the bound protocol's timeout/stall values (original v2: 60 hours/2 hours).

```bash
timeout 600 "$CF_PY" tools/research.py status
timeout 600 tmux list-sessions
# Create a separate idle operator session if it does not already exist.
timeout 600 tmux new-session -d -s cf-operator -c "$PROJECT_DIR"
for variable in OPENPI_DATA_HOME CONTEXTFLOW_CHECKPOINT_SCRATCH CONTEXTFLOW_LIBERO_PYTHON CUDA_VISIBLE_DEVICES CONTEXTFLOW_SERVER_PORT MUJOCO_GL WANDB_MODE PYTHONDONTWRITEBYTECODE; do
  timeout 600 tmux set-environment -g "$variable" "${!variable}"
done
timeout 600 tmux new-session -d -s cf-seed42 -c "$PROJECT_DIR" \
  "exec '$CF_PY' tools/research.py run --job experiments/baseline-seed42.json --foreground"
# Wait for seed42 to finish and inspect its complete evidence before seed43.
# No mid-run return is possible: follow section 8 (autonomous operation) and record measurements locally.
timeout 600 tmux new-session -d -s cf-seed43 -c "$PROJECT_DIR" \
  "exec '$CF_PY' tools/research.py run --job experiments/baseline-seed43.json --foreground"
# Wait for seed43 to finish before seed44.
timeout 600 tmux new-session -d -s cf-seed44 -c "$PROJECT_DIR" \
  "exec '$CF_PY' tools/research.py run --job experiments/baseline-seed44.json --foreground"
timeout 600 "$CF_PY" tools/research.py status
timeout 600 "$CF_PY" tools/research.py resume
```

中文：路径不要包含单引号，或改用经过正确 shell quoting 的本机启动脚本；所有环境变量须在创建 tmux 时传入，长期存在的 tmux server 可能保留旧环境，启动前检查并更新。**永不重提同一 task_id**。resume 只观察，不重启。不要因 PID 在其他机器不可见而认定失败。runner 会在 finally 关闭自己的 policy server；异常关机后先检查是否有遗留进程，不要误杀其他作业。

English: avoid single quotes in paths or use a correctly shell-quoted local launcher script. Ensure tmux receives the current exported environment; an existing tmux server can retain stale variables. **Never resubmit a task ID.** Resume only observes. Missing remote PID visibility does not prove failure. The runner shuts down its server in finally; after abrupt machine failure, inspect leftovers without killing another job.

中文：只有确认先前进程退出且状态为 failed/timeout/stalled/interrupted，才可复制该 seed job，换新的唯一 task_id，增加 retry_of 指向原 task_id；保持原 seed 和全部执行参数，每 seed 最多重试一次，总最多6次。新 job 用原 receipt 的前提是绑定完全不变。禁止 `--resume`/`--overwrite` 或复用旧 checkpoint 改成续训；新任务重新从 pi0_base 训练。第二次失败、预算耗尽、协议偏差或不完整评测即停止，保留缺失 seed 为 inconclusive，不替换种子。

English: retry only after confirmed process exit and a failed/timeout/stalled/interrupted state. Copy the same seed job, assign a new unique task_id and retry_of pointing to its original task. Preserve seed and all execution settings; one retry per seed, six attempts total. Reuse its receipt only if the execution binding is unchanged. Do not resume/overwrite old checkpoints: the new task starts from pi0_base. Stop after the second failure, exhausted budget, protocol deviation or incomplete evaluation; retain the missing seed as inconclusive.

## 7. 返回完整证据 / Return complete evidence

中文：返回每个尝试的完整 `runs/<task_id>/`，包括 manifest、contract/config/code snapshots、artifacts 索引、所有 stdout/stderr/worker/编号步骤日志、metrics/details、原始 client JSON、逐 trial 输出/视频、GPU CSV、pi0 SHA 清单、norm stats 和 `checkpoint/19999/{params,assets}`（经过字节校验的实际评测 checkpoint）；失败/中断也全部返回。不便传输大文件时先协商传输方式，不能删除或仅发送汇总替代。另附 configs/resources.json、research.json、budget.json、全部实际 job、冻结 registry、评审包/receipts/raw identity、reports/third-party 证据、dry-run 目录及环境/驱动/硬件/命令日志。先人工检查去除密钥；不发送 token、认证缓存、完整 HOME 或 uv/HF 私有缓存。

English: return the complete run directory for **every attempt**, including snapshots, artifact index, all logs, metrics/details, raw client JSON, trial output/videos, GPU CSV, pi0 hash inventory, normalization assets and the byte-verified evaluated `checkpoint/19999/{params,assets}`. Include failures/interruption evidence. Arrange transfer for large artifacts instead of deleting them or substituting summaries. Also return resources/research/budget configuration, actual jobs, freeze registry, review packages/receipts/raw identity evidence, reports/third-party and dry-run directories. Inspect for secrets before transfer; exclude tokens, auth caches, entire HOME and private uv/HF caches.

中文：v2 每 seed 共 600 trials：unseen pass 为四个任务各50次（200），all_tasks pass 为两个 suite 各10个任务各20次（400）。两套 JSON、视频、trial JSONL 分目录返回；all_tasks 中的 unseen 行单独保留，不得混进主指标。`eval/server-requests.jsonl` 与 details 中逐 trial 的请求 ID/延迟/demo indices 一起返回。

English: v2 evaluates 600 trials per seed: 200 unseen-pass trials and 400 all-task-pass trials. Return separate JSON/video/trial logs for both passes, plus server request JSONL and per-trial request/latency/demo evidence in details. Keep the second pass's unseen rows separate from primary metrics.

中文：传输限额不足时，先返回除大 checkpoint payload 外的完整 run 证据（保留原 artifacts 索引和 `checkpoint/checkpoint-sha256.json`），明确标记 checkpoint 尚未到齐；另用双方约定的大文件渠道发送每个 run 的 `checkpoint/19999/params/` 和 `assets/`，保留相对路径，不改字节。必须同时发送 runner 生成的每文件 size/SHA256 manifest；归档/分片再各附 SHA256。接收方在原 run 路径还原后逐文件核对 manifest，再核对 artifacts 索引；全部收到并校验前不视为完整交付。scratch 的其他步/optimizer 留在操作员机器，不用返回。

English: if transfer limits require a separate checkpoint shipment, first send the remaining complete run evidence with its original artifact index and `checkpoint/checkpoint-sha256.json`, explicitly marking weights as pending. Send each run's `checkpoint/19999/params/` and `assets/` through the agreed large-file channel, preserving paths and bytes, with the runner's per-file size/SHA256 manifest and additional SHA256 values for archives/chunks. Restore under the original run path and verify every manifest entry and artifact index before treating the return as complete. Other checkpoint steps and optimizer state remain on operator scratch.

中文：执行 completed 不等于科学接受。三 seed 的 across-seed mean/min/max、每任务 binomial SE 和全部 signal 判定须另做 analysis 与独立 result-review。本次交付仅验证 CPU fixture、门禁预算算术和本地 HEAD/clean；第三方下载完整性、环境、缓存、GPU、训练、评测、tmux、评审与跨机器传输均**未验证**。

English: completed execution is not scientific acceptance. Across-seed mean/min/max, per-task binomial SE and every protocol signal require subsequent analysis and independent result review. This delivery verifies only CPU fixtures, budget arithmetic and local checkout identity/cleanliness. Third-party downloads, environments, caches, GPU execution, training, evaluation, tmux, reviews and cross-machine transfer are **unverified**.

## 8. 自主运行手册（可交给 Codex 执行）/ Autonomous operation playbook (suitable for a Codex operator)

中文：项目负责人**无法接收中途数据**，只接收第一、二阶段全部结束后的最终返回。因此操作员（人或 Codex）必须自行完成下列判断，不得等待负责人答复。原冻结文件不得原地修改。负责人于 2026-10-31 授权唯一偏差：仅通过 tools/amend_limits.py 创建时限及其预算算术的后继协议，记录 OPERATOR_LOG.md 并重新批量代码评审；evaluation-params.json、种子及所有其他科研设置保持不可变。

1. **开跑前先测能力。** 记录 `nvidia-smi`（型号、显存）、CPU 核数、主机 RAM、磁盘余量，与本指南的底线比较（单卡≥48 GB 显存、16 CPU）。任一项不满足时不要启动训练；写 `reports/third-party/capacity-shortfall.md`（缺什么、实测值）并作为最终返回的一部分。
2. **按顺序、先小后大。** 先做环境/数据冒烟，再 seed42，其余 seed 随后依次；每个 job 跑完立刻在本机落一份 `measurements.json`（训练与评测耗时、GPU 显存峰值、主机 RAM 峰值、checkpoint 字节），不要等外部确认。
3. **失败只按协议处理。** 超时/停滞/非零退出：确认进程已退出，保留全部证据，按本指南的重试规则最多重试一次（新 task_id，retry_of）；第二次失败即停止该 seed 并标 inconclusive。若需调整 timeout/stall，**只可**走第 9 节已授权工具路线并重新批量代码评审；不得手改时限、预算，或改变步数、batch、评测次数、种子或重试次数。
4. **一个 seed 失败不阻断其余 seed。** 继续跑剩余 seed；最终返回包含全部成功与失败的完整 `runs/<task_id>/`。第二阶段仅在第一阶段全部完成、且负责人书面放行文件已在手时才开始；缺放行文件则只返回第一阶段。
5. **磁盘与内存不足时的处理。** 不清理任何 `runs/` 证据；仅按指南允许的方式处理 scratch。无法继续时停止，写明停止点与原因，不得降级配置或换成较小模型/数据。
6. **最终返回。** 一次性返回：全部 `runs/`、`measurements.json`、环境/硬件日志、命令日志、评审与资源登记证据、capacity-shortfall（如有）、以及一份 `OPERATOR_LOG.md`（按时间列出每个决定与理由）。

English: the owner **cannot receive mid-run data**; only the final return after phases one and two. The operator (human or Codex) must therefore decide autonomously within these rules and must not wait for an owner reply. Existing frozen files remain immutable. The owner authorized a disclosed limit deviation on 2026-10-31 ONLY through tools/amend_limits.py, OPERATOR_LOG.md disclosure and a fresh batch code-review round trip. Evaluation-params.json, seeds and all other scientific settings remain immutable.

1. **Measure capacity before starting.** Record GPU model/memory, CPU count, host RAM and free disk and compare with this guide's floor (one GPU ≥48 GB, 16 CPUs). If anything is short, do not start training: write `reports/third-party/capacity-shortfall.md` (what is missing, measured values) and include it in the final return.
2. **Small first.** Environment/data smoke, then seed42, then the other seeds sequentially. After every job write `measurements.json` locally (training vs. evaluation time, peak GPU memory, peak host RAM, checkpoint bytes); do not wait for outside confirmation.
3. **Failures follow the protocol only.** On timeout/stall/non-zero exit confirm exit, keep all evidence, and retry at most once under this guide's rules (new task_id, retry_of). After a second failure stop that seed as inconclusive. Change timeout/stall and their computed reservation caps ONLY through the owner-authorized tool route in section 9, then repeat batch code review. Never hand-edit limits/budgets or change steps, batch size, evaluation count, seeds or retry allowances.
4. **One failed seed does not block the others.** Continue with the remaining seeds; the final return contains every successful and failed `runs/<task_id>/`. Phase 2 starts only after all of phase 1 is complete and the owner's written release is in hand; without it, return phase 1 only.
5. **Disk or memory shortage.** Never delete anything under `runs/`; handle scratch only as the guide permits. If you cannot continue, stop, state the stopping point and reason; do not degrade the configuration or substitute a smaller model or dataset.
6. **Final return.** One delivery: all `runs/`, `measurements.json` files, environment/hardware/command logs, review and resource-registration evidence, capacity-shortfall if any, and an `OPERATOR_LOG.md` listing each decision and reason with timestamps.

## 9. 已授权时限后继版本 / Authorized limit successors

中文：负责人于 2026-10-31 授权此项**披露偏差**，授权文本及其 SHA256 引用见
`docs/operator-limit-authorization.md`。只允许改变 wall-clock timeout、stall，以及按
`原 max_attempts × timeout × 原 CPU/GPU 数` 重算的资源预算；美元额度按原
cost_per_hour 同样重算。不得改变 CPU/GPU 分配、尝试/重试次数、种子、训练步数、
batch、数据、模型、评测规则或 evaluation-params.json。降低任何时限/预算默认拒绝；
确需降低时显式传 `--allow-lower` 并说明原因。不得手改冻结文件或 registry。

English: the owner authorized this disclosed deviation on 2026-10-31. Only
`tools/amend_limits.py` may create successors; existing frozen bytes never change.
Reservation caps are recomputed using the original attempt count, CPUs, GPUs and
cost rate. This authorizes no additional attempt, seed or retry and changes no
scientific setting. A decrease requires explicit `--allow-lower` and disclosure.
All launch, resource, review and budget gates remain in force.

中文：工具分别从本阶段各原始协议的最新 limit-deviation 后继版复制科学内容：第一阶段
源头是 v2，第二阶段是 v3–v6。新版本号追加到全局线性链，因此 amendment.previous
是紧邻前一版本，amendment.original 则记录对应科学源版本和 SHA256，两者可能不同。
原科学字段按原始 JSON 值片段逐字节比较，不接受改值或改写科学值的表示方式。

English: each scientific lineage gets a successor (phase 1: v2; phase 2: v3–v6).
Version numbers append to the existing linear chain. `amendment.previous` names
the preceding chain version; `amendment.original` identifies the scientific
parent and its SHA256. The tool byte-compares all scientific subtrees outside
the explicit limits, version, amendment and permitted provenance fields.

中文：若 idea 尚无已观察运行，provenance 原样保留。已有运行时（包括 timeout、stalled、
running、失败或有部分日志的尝试），完全遵循 contracts.py：从 ledger 填充 observed_runs，
mode 改为 exploratory；hypothesis_basis_runs 保留。计划输出、amendment、报告和日志均标注
**post-hoc, exploratory; results are not preregistered**。这包括第二阶段之前已完成的第一阶段
baseline 运行；不把后继版追认为 preregistered，也不更改任何旧运行的原协议引用。

English: after ANY observed run of idea baseline, the unchanged provenance gate
requires observed-run disclosure and exploratory mode. The plan and retained
evidence explicitly say **post-hoc, exploratory; results are not preregistered**.
Before observed runs, provenance remains unchanged. Existing evidence and its
original protocol references are retained in both cases.

先设定实际请求的时限（秒）和理由，检查计划，再 apply。以下是操作模板，真实操作
**UNVERIFIED**；在操作员仓库执行，第二阶段把两处 `--phase 1` 换为 `--phase 2`。
Use the operator's repository; choose the requested seconds and record a genuine
reason. These commands are templates, not operations performed by this delivery:

```bash
: "${LIMIT_TIMEOUT_SECONDS:?set the requested positive integer timeout in seconds}"
: "${LIMIT_REASON:?set the reason for this disclosed deviation}"
timeout 600 python3 tools/amend_limits.py plan --phase 1 \
  --timeout-seconds "$LIMIT_TIMEOUT_SECONDS" --reason "$LIMIT_REASON"
# Review every proposed change. Optional: --stall-seconds N; --allow-lower.
timeout 600 python3 tools/amend_limits.py apply --phase 1 \
  --timeout-seconds "$LIMIT_TIMEOUT_SECONDS" --reason "$LIMIT_REASON"
timeout 600 python3 tools/research.py contract verify
# Replace <batch> with the batch field printed by apply. Use a fresh review output.
timeout 600 python3 tools/review_batch.py prepare --idea baseline \
  --jobs-glob 'experiments/limit-deviations/<batch>/jobs/*.json' \
  --out handoffs/limit-review-UNIQUE
# Complete the genuine independent batch review round trip, preserving raw evidence.
timeout 600 python3 tools/review_batch.py import --dir handoffs/limit-review-UNIQUE \
  --results handoffs/limit-review-UNIQUE/RESULTS.json
```

中文：plan 只读；apply 先在临时副本中用原 freeze 规则预检整条链，再追加新冻结版本。
原 jobs/configs/job-params.json 不变；新副本位于打印的
`experiments/limit-deviations/<batch>/{jobs,configs}/`，manifest 列出全部映射和 SHA256。
副本使用新的 task_id、contract/config 引用及预算估计；phase-2 的 --job 路径一并更新，
code_review_receipt 清空。只运行尚未启动、或仍有原定重试额度的对应任务；原任务失败时
先按既有规则设置 retry_of；已完成或重试耗尽的任务不得重跑。更长时限不返还已有 reservation。
configs/budget.json 的 global/real 额度仍需覆盖新 reservation 加既有占用；工具不自动授权计算。

English: the copied jobs need NEW per-package code reviews against the successor
binding. The batch tool is included in both export phases for this route. Fill
only each copied job's own accepted PASS receipt after the round trip; use the
copied job path with `research.py run --job ... --foreground` and, for phase-1
dry-run, explicitly pass `--job` to the baseline runner. Never reuse an old receipt,
restart a completed job or exceed the existing bounded retry allowance. If fresh
review cannot be obtained, stop. Original generated files still belong to the
original materializer; do not regenerate over or hand-edit the amended copies.

中文：apply 自动追加 OPERATOR_LOG.md 和 reports/third-party/limit-deviation.md，后者逐项记录
时限/预算、provenance、版本、job/config 路径与哈希绑定变化。检查并补充实际操作决定，
最终返回这两份文件、完整新旧协议/registry、manifest、副本、全部新旧评审原文/receipts 及
所有尝试的 runs/。若 apply 部分失败，保留现状和错误，不覆盖或删除已冻结内容。

English: verify the automatic disclosures and include them in the final return,
with the full old/new protocol chain, registry, generated manifest, copied
jobs/configs, fresh review evidence and every attempted run. Numeric prose in
the original protocol remains historical; effective structured successor limits
and the deviation report identify the amended values. This route grants neither
scientific acceptance nor the separate written phase-2 release.
