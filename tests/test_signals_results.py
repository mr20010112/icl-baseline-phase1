"""Signal and review regressions; isolated toy runs, no external reviewers."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import test_workflow as workflow
from test_workflow import dump
import contracts
import evidence
import results


class SignalResultTests(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow.WorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.protocol = self.fixture.protocol
        for category in ('success', 'failure', 'inconclusive'):
            self.protocol[category + '_signals'] = [{'id': category + '-v1', 'rule': 'Synthetic ' + category + ' criterion', 'metrics': ['mse', 'train_mse']}]
        dump(self.root / self.fixture.contract_path, self.protocol)
        self.fixture.freeze()
        self.fixture.run_job()
        self.analysis_ref = 'analysis/result.json'
        self.analysis = {'kind': 'toy', 'contract': self.fixture.contract_path, 'runs': ['toy-001'], 'outcome': 'success', 'decision': 'Synthetic engineering example', 'limitations': ['Not scientific evidence'], 'analyst_identity': {'provider': 'fixture', 'model': 'analyst', 'model_family': 'A', 'identity_source': 'synthetic test only'}, 'signal_results': [{'signal_id': category + '-v1', 'status': 'met' if category == 'success' else 'not_met', 'reason': 'Synthetic assessment for testing', 'evidence': [{'run_id': 'toy-001', 'metric': 'mse'}]} for category in ('success', 'failure', 'inconclusive')]}
        dump(self.root / self.analysis_ref, self.analysis)
        (self.root / 'baseline.md').write_text('Synthetic baseline document')
        dump(self.root / 'configs/research.json', {'baseline': {'paper_source': 'baseline.md'}})
        self.claim = {'id': 'fixture', 'type': 'empirical', 'kind': 'toy', 'hypothesis': self.protocol['hypothesis'], 'contract': self.fixture.contract_path, 'runs': ['toy-001'], 'metrics': ['mse'], 'analysis_file': self.analysis_ref, 'signal_ids': ['success-v1']}

    def review(self):
        package = evidence.context_pack(self.root, 'toy-linear', 'result-review', analysis_ref=self.analysis_ref)
        manifest = contracts.load(package / 'manifest.json')
        result = contracts.load(package / 'result-template.json')
        result.update({'completion': 'complete', 'verdict': 'PASS', 'fresh_context': True, 'actual_identity': {'actor_type': 'human', 'person': 'Synthetic reviewer', 'identity_source': 'test only'}, 'direct_reads': [x['path'] for x in manifest['files']], 'raw_response_file': 'response.txt', 'identity_evidence_file': 'identity.txt'})
        (package / 'response.txt').write_text('Fixture review of every signal; no real external review')
        (package / 'identity.txt').write_text('Synthetic human identity fixture')
        dump(package / 'result.json', result)
        path = evidence.import_review(self.root, package, package / 'result.json')
        self.claim['result_review_receipt'] = path.relative_to(self.root).as_posix()
        return path

    def audit(self):
        dump(self.root / 'paper/claims.json', [self.claim])
        return evidence.audit(self.root)

    def test_complete_signal_review_chain_passes(self):
        self.review()
        self.assertEqual(self.audit()['status'], 'PASS')

    def test_missing_and_unknown_signal_bindings_block(self):
        self.review()
        del self.claim['signal_ids']
        self.assertEqual(self.audit()['status'], 'FAIL')
        self.claim['signal_ids'] = ['does-not-exist']
        self.assertEqual(self.audit()['status'], 'FAIL')

    def test_analysis_must_cover_every_signal(self):
        self.analysis['signal_results'].pop()
        dump(self.root / self.analysis_ref, self.analysis)
        with self.assertRaises(contracts.ProjectError):
            results.check_analysis(self.root, self.analysis_ref)

    def test_result_review_required_and_analysis_changes_invalidate_it(self):
        self.assertEqual(self.audit()['status'], 'FAIL')
        self.review()
        self.analysis['decision'] = 'Changed after review'
        dump(self.root / self.analysis_ref, self.analysis)
        self.assertEqual(self.audit()['status'], 'FAIL')

    def test_unknown_metric_and_uncovered_run_block(self):
        self.analysis['signal_results'][0]['evidence'][0]['metric'] = 'invented'
        dump(self.root / self.analysis_ref, self.analysis)
        with self.assertRaises(contracts.ProjectError):
            results.check_analysis(self.root, self.analysis_ref)

    def test_signal_id_cannot_change_its_definition(self):
        changed = copy.deepcopy(self.protocol)
        changed['success_signals'][0]['rule'] = 'New threshold'
        with self.assertRaisesRegex(contracts.ProjectError, 'new signal ID'):
            results.validate_signals(changed, self.protocol)
        changed['success_signals'][0]['id'] = 'success-v2'
        results.validate_signals(changed, self.protocol)

    def test_claim_requires_every_run_metric_pair(self):
        # Both metrics exist in both raw files, but the chosen signal references
        # only one metric from each run. Projection-only checks lost this link.
        self.fixture.run_job(task_id='toy-002')
        self.analysis['runs'].append('toy-002')
        self.analysis['signal_results'][0]['evidence'].append({'run_id': 'toy-002', 'metric': 'train_mse'})
        dump(self.root / self.analysis_ref, self.analysis)
        self.review()
        self.claim['runs'] = ['toy-001', 'toy-002']
        self.claim['metrics'] = ['mse', 'train_mse']
        report = self.audit()
        self.assertEqual(report['status'], 'FAIL')
        self.assertIn('covered by its signals', report['errors'][0])

    def test_signal_category_cannot_override_its_list(self):
        changed = copy.deepcopy(self.protocol)
        changed['failure_signals'][0]['category'] = 'success'
        self.assertEqual(results.validate_signals(changed)['failure-v1']['category'], 'failure')

    def test_config_snapshot_change_blocks_analysis(self):
        (self.root / 'runs/toy-001/config.json').write_text('{}')
        with self.assertRaises(contracts.ProjectError):
            results.check_analysis(self.root, self.analysis_ref)

    def test_failed_run_can_support_failure_with_indexed_artifacts(self):
        self.fixture.run_job(task_id='failed-002', command=self.fixture.job['command'] + ['--fail'])
        self.analysis['runs'] = ['failed-002']
        self.analysis['outcome'] = 'failure'
        for item in self.analysis['signal_results']:
            item['status'] = 'met' if item['signal_id'] == 'failure-v1' else 'not_met'
            item['evidence'] = [{'run_id': 'failed-002', 'artifact': 'stdout.log'}]
        dump(self.root / self.analysis_ref, self.analysis)
        results.check_analysis(self.root, self.analysis_ref)
        (self.root / 'runs/failed-002/stdout.log').write_text('changed')
        with self.assertRaises(contracts.ProjectError):
            results.check_analysis(self.root, self.analysis_ref)

    def test_retired_signal_id_cannot_be_reused_with_new_rule(self):
        from datetime import datetime, timezone
        second = copy.deepcopy(self.protocol)
        second['version'] = 2
        second['success_signals'][0]['id'] = 'replacement-success'
        second['provenance'] = {'mode': 'exploratory', 'observed_runs': ['toy-001'],
                                'hypothesis_basis_runs': ['toy-001']}
        second['amendment'] = {'previous': self.fixture.contract_path, 'reason': 'Synthetic schema regression', 'created_at': datetime.now(timezone.utc).isoformat(), 'impact': 'Fixture only', 'seen_results': ['toy-001']}
        path2 = 'contracts/toy-linear/v2.yaml'
        dump(self.root / path2, second)
        contracts.freeze(self.root, path2)
        third = copy.deepcopy(second)
        third['version'] = 3
        third['success_signals'][0].update({'id': 'success-v1', 'rule': 'Changed after retirement'})
        third['amendment'].update({'previous': path2, 'created_at': datetime.now(timezone.utc).isoformat()})
        path3 = 'contracts/toy-linear/v3.yaml'
        dump(self.root / path3, third)
        with self.assertRaisesRegex(contracts.ProjectError, 'new signal ID'):
            contracts.freeze(self.root, path3)

    def test_duplicate_signal_ids_rejected(self):
        changed = copy.deepcopy(self.protocol)
        changed['failure_signals'][0]['id'] = 'success-v1'
        with self.assertRaises(contracts.ProjectError):
            results.validate_signals(changed)


if __name__ == '__main__':
    unittest.main()
