"""Shared execution and immutable run evidence bindings."""
from __future__ import annotations
import math
import sys
from pathlib import Path
from contracts import ProjectError, load, sha, project_path, verify

# These references are attached after review; none changes the executed program.
UNBOUND_JOB_FIELDS = {'task_id', 'retry_of', 'code_review_receipt', 'idea_review_receipt',
                      'result_review_receipt', 'decision_record', 'novelty_record', 'selection_record'}


def execution_binding(root: Path, job: dict) -> dict:
    root = root.resolve()
    cmd = job.get('command', [])
    if not isinstance(cmd, list) or len(cmd) < 2 or any(not isinstance(x, str) for x in cmd):
        raise ProjectError('Execution requires a Python script command')
    if cmd[0] not in ('{python}', sys.executable) or cmd[1].startswith('-'):
        raise ProjectError('Execution entrypoint must be a reviewed Python script; -c/-m/options are forbidden')
    entry = project_path(root, cmd[1].replace('{root}', str(root)))
    if entry.suffix != '.py' or not entry.is_file():
        raise ProjectError('Execution entrypoint must be an existing project Python script')
    files = {}
    for ref in job.get('code_paths', []):
        p = project_path(root, ref)
        members = [p] if p.is_file() else sorted(x for x in p.rglob('*') if x.is_file() and '__pycache__' not in x.parts and '.git' not in x.parts)
        for item in members:
            resolved = project_path(root, item)
            files[resolved.relative_to(root).as_posix()] = sha(resolved)
    relative = entry.relative_to(root).as_posix()
    if relative not in files:
        raise ProjectError('Execution entrypoint is outside reviewed code_paths')
    payload = {k: v for k, v in job.items() if k not in UNBOUND_JOB_FIELDS}
    payload = dict(payload)
    payload['command'] = ['{python}', relative, *cmd[2:]]
    for key in ('contract', 'config'):
        payload[key] = project_path(root, job[key]).relative_to(root).as_posix()
    payload['code_paths'] = sorted(project_path(root, p).relative_to(root).as_posix() for p in job['code_paths'])
    resources = {}
    if job.get('dataset_id'):
        registry = load(root / 'configs/resources.json')
        for group, key in (('data','dataset_id'), ('environments','environment_id'), ('compute','resource_id')):
            matches = [x for x in registry.get(group, []) if x.get('id') == job.get(key)]
            if len(matches) != 1:
                raise ProjectError('Execution resource binding missing: ' + group)
            resources[group] = matches[0]
        resources['weights'] = [x for x in registry.get('weights', []) if x.get('id') in job.get('weight_ids', [])]
        from gates import digest, resolve
        for item in [resources['data'], *resources['weights']]:
            if digest(resolve(root, item.get('path'), file=False)) != item.get('fingerprint'):
                raise ProjectError('Execution data/weight content differs from registered fingerprint')
    decisions = {}
    for key in ('selection_record', 'decision_record', 'novelty_record'):
        if job.get(key):
            path = project_path(root, job[key])
            decisions[key] = {'path':path.relative_to(root).as_posix(), 'sha256':sha(path)}
    return {'schema_version': 1, 'job': payload, 'entrypoint': relative,
            'resources': resources, 'decisions': decisions,
            'contract_sha256': sha(project_path(root, job['contract'])),
            'config_sha256': sha(project_path(root, job['config'])), 'code': dict(sorted(files.items()))}


def execution_command(root: Path, out: Path, binding: dict, python: str) -> list[str]:
    cmd = list(binding['job']['command'])
    substitutions = {'{python}': python, '{root}': str(root), '{run_dir}': str(out), '{config}': str(out / 'config.json')}
    for key, value in substitutions.items():
        cmd = [x.replace(key, value) for x in cmd]
    cmd[1] = str(out / 'code' / binding['entrypoint'])
    return cmd


def check_snapshots(root: Path, manifest: dict) -> None:
    root = root.resolve()
    out = project_path(root, 'runs/' + manifest['task_id'])
    binding = manifest.get('execution_binding')
    if not isinstance(binding, dict):
        raise ProjectError('Run lacks execution binding; legacy evidence requires a new reviewed run')
    contract = manifest['contract']
    frozen = verify(root, contract['path'])
    if frozen['sha256'] != contract['sha256'] or sha(project_path(out, contract['snapshot'])) != contract['sha256']:
        raise ProjectError('Run protocol snapshot modified')
    config = manifest['config']
    if sha(project_path(out, config['snapshot'])) != config['sha256']:
        raise ProjectError('Run configuration snapshot modified')
    if binding.get('contract_sha256') != contract['sha256'] or binding.get('config_sha256') != config['sha256']:
        raise ProjectError('Execution binding differs from protocol/config snapshots')
    code = manifest.get('code', [])
    if not code or {x['path']: x['sha256'] for x in code} != binding.get('code'):
        raise ProjectError('Execution code scope differs from snapshots')
    for entry in code:
        if sha(project_path(out, entry['snapshot'])) != entry['sha256']:
            raise ProjectError('Run implementation snapshot modified')
    job = manifest['job']
    expected = {k: v for k, v in job.items() if k not in UNBOUND_JOB_FIELDS}
    expected['command'] = ['{python}', binding['entrypoint'], *job['command'][2:]]
    for key in ('contract', 'config'):
        expected[key] = project_path(root, job[key]).relative_to(root).as_posix()
    expected['code_paths'] = sorted(project_path(root, p).relative_to(root).as_posix() for p in job['code_paths'])
    if expected != binding['job']:
        raise ProjectError('Run job differs from reviewed execution binding')
    entry = project_path(root, job['command'][1].replace('{root}', str(root))).relative_to(root).as_posix()
    if entry != binding['entrypoint'] or entry not in binding['code']:
        raise ProjectError('Run entrypoint differs from execution binding')
    if manifest['command'] != execution_command(root, out, binding, manifest['environment']['executable']):
        raise ProjectError('Run command differs from execution binding')
    for key in ('kind', 'stage', 'idea_id', 'seed', 'dataset_id', 'environment_id', 'resource_id'):
        if manifest.get(key) != job.get(key):
            raise ProjectError('Run manifest/job binding differs: ' + key)
    protocol = load(project_path(out, contract['snapshot']))
    if binding.get('resources') != manifest.get('resources'):
        raise ProjectError('Run resource snapshot differs from execution binding')
    data = manifest.get('resources', {}).get('data', {})
    if data.get('id') != job['dataset_id'] or protocol['data'].get('dataset_id', protocol['data'].get('id')) != job['dataset_id']:
        raise ProjectError('Run dataset binding differs')
    for key in ('version', 'split'):
        if protocol['data'].get(key) != data.get(key):
            raise ProjectError('Run data snapshot differs: ' + key)
    if job['kind'] == 'real' and protocol['data'].get('fingerprint') != data.get('fingerprint'):
        raise ProjectError('Run data fingerprint differs from frozen protocol')


def check_run_evidence(root: Path, manifest: dict, *, require_completed: bool = True) -> dict:
    root = root.resolve()
    out = project_path(root, 'runs/' + manifest['task_id'])
    if require_completed and manifest.get('status') != 'completed':
        raise ProjectError('Run is not completed')
    check_snapshots(root, manifest)
    index = load(out / 'artifacts.json').get('files', [])
    indexed = {x['path'] for x in index}
    required = {manifest['contract']['snapshot'], manifest['config']['snapshot']}
    required.update(x['snapshot'] for x in manifest['code'])
    if manifest.get('status') == 'completed':
        required.add(manifest.get('metrics', {}).get('path', 'metrics.json'))
    if len(indexed) != len(index) or not required.issubset(indexed):
        raise ProjectError('Artifact index does not cover run evidence')
    for entry in index:
        path = project_path(out, entry['path'])
        if not path.is_file() or sha(path) != entry['sha256'] or path.stat().st_size != entry['bytes']:
            raise ProjectError('Indexed run artifact missing or modified: ' + entry['path'])
    if manifest.get('status') != 'completed':
        return {}
    metrics = manifest.get('metrics', {})
    path = project_path(out, metrics.get('path', 'metrics.json'))
    values = load(path)
    if sha(path) != metrics.get('sha256') or values != metrics.get('values') or not values:
        raise ProjectError('Run raw metrics missing or changed')
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in values.values()):
        raise ProjectError('Run metrics must be finite numeric measurements')
    from runtime import metric_names
    protocol = load(project_path(out, manifest['contract']['snapshot']))
    names = metric_names(protocol['metrics']['primary']) | metric_names(protocol['metrics']['secondary'])
    if set(manifest['job']['required_metrics']) != names:
        raise ProjectError('Run required metrics differ from frozen protocol')
    if not set(manifest['job']['required_metrics']).issubset(values):
        raise ProjectError('Run required metrics missing')
    return values
