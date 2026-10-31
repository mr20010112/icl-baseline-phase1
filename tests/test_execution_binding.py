"""Execution binding regressions, using isolated synthetic fixtures."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from contracts import ProjectError
from run_evidence import execution_binding, execution_command

class ExecutionBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('reviewed.py', 'unreviewed.py'):
            (self.root / name).write_text('print("fixture")\n')
        for name in ('config.json', 'contract.yaml'):
            (self.root / name).write_text('{}')
        self.job = {'task_id':'fixture', 'command':['{python}','reviewed.py','--config','{config}'],
                    'contract':'contract.yaml', 'config':'config.json', 'code_paths':['reviewed.py'], 'seed':7}

    def test_unreviewed_entry_and_inline_python_are_blocked(self):
        for command in (['{python}','unreviewed.py'], ['{python}','-c','print(1)'], ['{python}','-m','module']):
            with self.subTest(command=command), self.assertRaises(ProjectError):
                execution_binding(self.root, {**self.job, 'command':command})

    def test_command_and_config_changes_invalidate_binding(self):
        first = execution_binding(self.root, self.job)
        changed = copy.deepcopy(self.job)
        changed['command'] += ['--different']
        self.assertNotEqual(first, execution_binding(self.root, changed))
        (self.root / 'config.json').write_text('{"changed":true}')
        self.assertNotEqual(first, execution_binding(self.root, self.job))

    def test_receipt_backfill_and_retry_do_not_change_review(self):
        self.assertEqual(execution_binding(self.root, self.job), execution_binding(self.root,
            {**self.job, 'task_id':'retry', 'retry_of':'fixture', 'code_review_receipt':'receipt.json'}))

    def test_human_self_review_is_not_independent(self):
        from gates import independence
        actor={"actor_type":"human","person":"same person","identity_source":"fixture"}
        self.assertEqual(independence(actor,actor),"same-person")

    def test_launch_executes_snapshot_entry(self):
        binding = execution_binding(self.root, self.job)
        out = self.root / 'runs/fixture'
        command = execution_command(self.root, out, binding, sys.executable)
        self.assertEqual(command[1], str(out / 'code/reviewed.py'))
        self.assertEqual(command[-1], str(out / 'config.json'))

if __name__ == '__main__': unittest.main()
