"""Signal-level evidence and independent result acceptance checks."""
from pathlib import Path
import re
from contracts import ProjectError, load, sha, project_path, verify


def metric_names(value):
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set().union(*(metric_names(x) for x in value)) if value else set()
    if isinstance(value, dict):
        return {value['name']} if isinstance(value.get('name'), str) else set(value)
    raise ProjectError('Invalid frozen metric definitions')


def validate_signals(protocol, previous=None):
    names = metric_names(protocol['metrics']['primary']) | metric_names(protocol['metrics']['secondary'])
    signals = {}
    for category in ('success', 'failure', 'inconclusive'):
        entries = protocol.get(category + '_signals')
        if not isinstance(entries, list) or not entries:
            raise ProjectError(f'{category}_signals must be a nonempty list with stable IDs')
        for entry in entries:
            if not isinstance(entry, dict):
                raise ProjectError('Each signal must contain id, rule and metrics')
            sid = entry.get('id')
            if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', sid) or sid in signals:
                raise ProjectError('Signal IDs must be safe and globally unique within the protocol')
            metrics = entry.get('metrics')
            if not isinstance(entry.get('rule'), str) or not entry['rule'].strip():
                raise ProjectError(f'Signal {sid} needs a rule')
            if not isinstance(metrics, list) or not metrics or any(not isinstance(x, str) for x in metrics) or len(set(metrics)) != len(metrics) or not set(metrics) <= names:
                raise ProjectError(f'Signal {sid} metrics must reference frozen metric names')
            signals[sid] = {**entry, 'category': category}
    if previous:
        # Legacy frozen versions remain readable; their unidentified signals
        # cannot silently acquire an identity retroactively.
        for category in ('success', 'failure', 'inconclusive'):
            for old in previous.get(category + '_signals', []):
                if not isinstance(old, dict) or old.get('id') not in signals:
                    continue
                new = signals[old['id']]
                if (category, old.get('rule'), set(old.get('metrics', []))) != (new['category'], new['rule'], set(new['metrics'])):
                    raise ProjectError('Changing a signal definition requires a new signal ID')
    return signals


def _ids(value, field):
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', x) for x in value) or len(set(value)) != len(value):
        raise ProjectError(f'{field} must contain unique nonempty IDs')
    return value


def check_analysis(root, analysis_ref, *, contract_ref=None, runs=None):
    from gates import known_identity, check_run_metrics
    root = Path(root).resolve()
    if not isinstance(analysis_ref, str) or not analysis_ref:
        raise ProjectError("Analysis reference is required")
    analysis = load(project_path(root, analysis_ref))
    if not isinstance(analysis, dict):
        raise ProjectError("Analysis must be an object")
    reference = analysis.get('contract')
    if not isinstance(reference, str):
        raise ProjectError('Analysis needs a frozen contract')
    binding = verify(root, reference)
    if contract_ref is not None and project_path(root, reference) != project_path(root, contract_ref):
        raise ProjectError('Analysis contract differs from requested protocol')
    protocol = load(project_path(root, reference))
    signals = validate_signals(protocol)
    run_ids = _ids(analysis.get('runs'), 'analysis.runs')
    if runs is not None and set(run_ids) != set(runs):
        raise ProjectError('Analysis must cover the exact requested runs')
    if analysis.get('kind') != protocol['kind'] or analysis.get('outcome') not in ('success', 'failure', 'inconclusive'):
        raise ProjectError('Analysis kind/outcome invalid')
    if not isinstance(analysis.get('decision'), str) or not analysis['decision'].strip() or not isinstance(analysis.get('limitations'), list):
        raise ProjectError('Analysis needs decision and limitations')
    if not known_identity(analysis.get('analyst_identity', {})):
        raise ProjectError('Analysis needs an established analyst_identity')
    manifests = {}
    for task in run_ids:
        manifest = load(root / 'runs' / task / 'manifest.json')
        if manifest.get('task_id') != task or manifest.get('kind') != analysis['kind'] or manifest.get('status') not in ('completed', 'failed', 'timeout', 'stalled', 'interrupted'):
            raise ProjectError('Analysis cites a nonterminal or wrong-kind run')
        bound = manifest.get('contract', {})
        if project_path(root, bound.get('path', '')) != project_path(root, reference) or bound.get('sha256') != binding['sha256']:
            raise ProjectError('Analysis run has a different frozen protocol')
        if sha(project_path(root / 'runs' / task, bound.get('snapshot', 'contract.yaml'))) != binding['sha256']:
            raise ProjectError('Analysis protocol snapshot changed')
        from run_evidence import check_run_evidence
        check_run_evidence(root, manifest, require_completed=False)
        manifests[task] = manifest
    decisions = analysis.get('signal_results')
    if not isinstance(decisions, list) or len(decisions) != len(signals) or any(not isinstance(x, dict) for x in decisions):
        raise ProjectError('Analysis must assess every frozen signal exactly once')
    if any(not isinstance(x.get('signal_id'), str) for x in decisions) or {x.get('signal_id') for x in decisions} != set(signals):
        raise ProjectError('Analysis has missing, duplicate or unknown signal IDs')
    for result in decisions:
        signal = signals[result['signal_id']]
        if result.get('status') not in ('met', 'not_met', 'inconclusive') or not isinstance(result.get('reason'), str) or not result['reason'].strip():
            raise ProjectError('Each signal needs status and reason')
        evidence = result.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise ProjectError('Each signal needs raw run evidence')
        for entry in evidence:
            if not isinstance(entry, dict) or not isinstance(entry.get('run_id'), str) or entry.get('run_id') not in manifests or ('metric' in entry) == ('artifact' in entry):
                raise ProjectError('Signal evidence requires a cited run and exactly one metric or artifact')
            task = entry['run_id']
            if 'metric' in entry:
                if entry['metric'] not in signal['metrics'] or entry['metric'] not in check_run_metrics(root, manifests[task]):
                    raise ProjectError('Signal evidence metric is not frozen/measured')
            else:
                out = root / 'runs' / task
                artifact = project_path(out, entry['artifact'])
                index = load(out / 'artifacts.json').get('files', [])
                match = next((x for x in index if x.get('path') == artifact.relative_to(out).as_posix()), None)
                if not match or sha(artifact) != match.get('sha256') or artifact.stat().st_size != match.get('bytes'):
                    raise ProjectError('Signal artifact is missing or changed')
    if not any(signals[x['signal_id']]['category'] == analysis['outcome'] and x['status'] == 'met' for x in decisions):
        raise ProjectError('Analysis outcome needs a met signal in the corresponding category')
    if analysis['outcome'] == 'success' and any(signals[x['signal_id']]['category'] != 'success' and x['status'] != 'not_met' for x in decisions):
        raise ProjectError('Success cannot ignore failure or unresolved inconclusive signals')
    return analysis


def check_result_review(root, analysis_ref, analysis, receipt_ref):
    from gates import check_receipt, independence
    root = Path(root).resolve()
    protocol = load(project_path(root, analysis['contract']))
    receipt = check_receipt(root, receipt_ref, 'result-review', {'idea_id': protocol['idea_id'], 'contract': analysis['contract'], 'executor_identity': analysis['analyst_identity']})
    scope = receipt.get('scope', {})
    binding = scope.get('analysis', {})
    path = project_path(root, analysis_ref)
    if binding.get('path') != path.relative_to(root).as_posix() or binding.get('sha256') != sha(path):
        raise ProjectError('Result review does not bind this analysis version')
    if scope.get('contract') != analysis['contract'] or set(scope.get('runs', [])) != set(analysis['runs']):
        raise ProjectError('Result review has a different protocol/run scope')
    covered = {x['path'] for x in scope.get('files', [])}
    required = {path.relative_to(root).as_posix(), project_path(root, analysis['contract']).relative_to(root).as_posix()}
    reviewer = receipt['actual_identity']
    for task in analysis['runs']:
        out = root / 'runs' / task
        required.update(x.relative_to(root).as_posix() for x in out.rglob('*') if x.is_file())
        manifest = load(out / 'manifest.json')
        executor = manifest.get('job', {}).get('executor_identity', {})
        if analysis['kind'] == 'real' and independence(executor, reviewer) not in ('cross-family', 'human-review'):
            raise ProjectError('Result reviewer must be independent of run implementer')
    if not required <= covered:
        raise ProjectError('Result review did not cover analysis, protocol and complete run evidence')
    return receipt
