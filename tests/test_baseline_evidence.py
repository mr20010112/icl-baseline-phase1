"""Synthetic baseline manifests exercise deterministic gates; no training occurs."""
import copy
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import contracts, gates, runtime
from run_evidence import execution_binding, execution_command, check_run_evidence

class BaselineEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write('code.py', 'print("synthetic fixture, never executed")\n', raw=True)
        self.write('data.txt', 'synthetic\n', raw=True)
        self.write('paper.txt', 'Synthetic paper fixture: mean metric 0.5', raw=True)
        self.write('witness.txt', 'synthetic verification fixture', raw=True)
        self.data = {'id':'data','kind':'real','status':'verified','path':'data.txt','version':'fixture-v1','split':'test',
                     'fingerprint':gates.digest(self.root/'data.txt'),'verification':{'evidence_file':'witness.txt'}}
        self.resources = {'data':[self.data], 'environments':[{'id':'env'}], 'compute':[{'id':'cpu'}], 'weights':[]}
        self.write('configs/resources.json', self.resources)
        self.ref='contracts/baseline/v1.yaml'
        stats={'metric':'mse','aggregation':'mean','atol':0.01,'rtol':0,'statistical_rule':'fixture tolerance','hardware_scope':'fixture'}
        self.protocol={'idea_id':'baseline','version':1,'kind':'real','question':'fixture','hypothesis':'fixture',
            'method':{'description':'fixture','implementation':['code.py']},
            'metrics':{'primary':[{'name':'mse'}],'secondary':[]}, 'data':{'dataset_id':'data','version':'fixture-v1','split':'test','fingerprint':self.data['fingerprint']},
            'baseline':{'commit':'1'*40,'reported_metrics':[{'metric':'mse','value':0.5,'source':'paper.txt','source_sha256':contracts.sha(self.root/'paper.txt')}]},
            'hyperparameters':{'x':1},'seeds':([7,8] if self._testMethodName == 'test_missing_frozen_seed_is_rejected' else [7]), 'statistics':stats,
            'success_signals':[{'id':'fit','rule':'mse close','metrics':['mse']}],
            'failure_signals':[{'id':'bad','rule':'divergence','metrics':['mse']}],
            'inconclusive_signals':[{'id':'unknown','rule':'insufficient','metrics':['mse']}],
            'ablations':[{'name':'fixture'}], 'budget':{'max_attempts':2},'stopping':{'max_attempts':2},'provenance':{'mode':'preregistered','observed_runs':[],'hypothesis_basis_runs':[]}}
        self.write(self.ref,self.protocol); contracts.freeze(self.root,self.ref)
        self.write('config.json',{'hyperparameters':{'x':1},'seed':7,'dataset_id':'data','split':'test'})
        self.job={'task_id':'baseline-7','kind':'real','stage':'baseline','idea_id':'baseline','seed':7,'dataset_id':'data','environment_id':'env','resource_id':'cpu',
            'executor_identity':{'provider':'fixture','model':'implementer','model_family':'family-B','identity_source':'synthetic fixture'},
            'command':['{python}','code.py'],'code_paths':['code.py'],'config':'config.json','contract':self.ref,'required_metrics':['mse']}
        binding=execution_binding(self.root,self.job)
        out=self.root/'runs/baseline-7'; out.mkdir(parents=True)
        (out/'contract.yaml').write_bytes((self.root/self.ref).read_bytes()); (out/'config.json').write_bytes((self.root/'config.json').read_bytes())
        code=runtime.snapshot_code(self.root,out,['code.py'])
        self.write('runs/baseline-7/metrics.json',{'mse':0.5})
        self.manifest={**{k:self.job[k] for k in ('task_id','kind','stage','idea_id','seed','dataset_id','environment_id','resource_id')},
            'status':'completed','job':self.job,'execution_binding':binding,
            'command':execution_command(self.root,out,binding,sys.executable),'environment':{'executable':sys.executable},
            'contract':{'path':self.ref,'sha256':contracts.sha(out/'contract.yaml'),'snapshot':'contract.yaml'},
            'config':{'sha256':contracts.sha(out/'config.json'),'snapshot':'config.json'},'code':code,'resources':binding['resources'],
            'metrics':{'path':'metrics.json','sha256':contracts.sha(out/'metrics.json'),'values':{'mse':0.5}}}
        self.write('runs/baseline-7/manifest.json',self.manifest)
        self.write('runs/baseline-7/artifacts.json',{'files':runtime.artifact_index(out)})
        self.analysis={'kind':'real','decision':'pass','outcome':'success','tolerance':stats,
            'comparison':{'paper_reported':0.5,'reproduced':0.5,'paper_source':'paper.txt'}}
        self.write('validation.json',{'kind':'real','baseline_commit':'1'*40,
            'checks':{k:{'status':'pass','evidence_file':'witness.txt'} for k in ('data','environment','evaluation')},
            'reproduction':{'run_ids':['baseline-7'],'analysis_file':'analysis.json','result_review_receipt':'review.json'}})
        self.research={'data_id':'data','environment_id':'env','baseline':{'paper_source':'paper.txt','repo':'synthetic','repo_path':'.','commit':'1'*40,'validation_record':'validation.json'}}

    def write(self,path,value,raw=False):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value if raw else json.dumps(value))

    def baseline(self):
        # These tests isolate baseline evidence/aggregation; result-review tests cover the real receipt path.
        module=types.ModuleType('results');module.check_analysis=Mock(return_value=self.analysis);module.check_result_review=Mock(return_value={})
        with patch.dict(sys.modules,{'results':module}), patch.object(gates.subprocess,'run',return_value=types.SimpleNamespace(stdout='1'*40)):
            gates.check_baseline(self.root,self.research,reproduced=True)
        return module

    def test_complete_bound_fixture_passes_and_requires_result_review(self):
        self.assertEqual(check_run_evidence(self.root,self.manifest),{'mse':0.5})
        self.baseline().check_result_review.assert_called_once()

    def test_real_result_receipt_end_to_end(self):
        import evidence
        self.write('configs/research.json', self.research)
        self.write('configs/budget.json', {'real_enabled':False})
        self.write('configs/models.json', {'policy':{'max_review_rounds':2,'max_review_calls':24}})
        self.analysis.update({'contract':self.ref, 'runs':['baseline-7'], 'limitations':['Synthetic schema fixture only'],
            'analyst_identity':{'provider':'fixture','model':'analyst','model_family':'family-A','identity_source':'synthetic fixture'},
            'signal_results':[{'signal_id':sid,'status':status,'reason':'Synthetic reviewed fixture',
                               'evidence':[{'run_id':'baseline-7','metric':'mse'}]}
                              for sid,status in [('fit','met'),('bad','not_met'),('unknown','not_met')]]})
        self.write('analysis.json', self.analysis)
        package=evidence.context_pack(self.root,'baseline','result-review',analysis_ref='analysis.json')
        manifest=contracts.load(package/'manifest.json')
        result=contracts.load(package/'result-template.json')
        result.update({'completion':'complete','verdict':'PASS','fresh_context':True,
            'actual_identity':{'provider':'fixture','model':'reviewer','model_family':'family-C','identity_source':'synthetic fixture'},
            'direct_reads':[x['path'] for x in manifest['files']], 'raw_response_file':'response.txt','identity_evidence_file':'identity.txt'})
        (package/'response.txt').write_text('Synthetic independent result review, no real scientific result')
        (package/'identity.txt').write_text('Synthetic identity fixture')
        (package/'result.json').write_text(json.dumps(result))
        receipt=evidence.import_review(self.root,package,package/'result.json')
        validation=contracts.load(self.root/'validation.json')
        validation['reproduction']['result_review_receipt']=receipt.relative_to(self.root).as_posix()
        self.write('validation.json',validation)
        with patch.object(gates.subprocess,'run',return_value=types.SimpleNamespace(stdout='1'*40)):
            gates.check_baseline(self.root,self.research,reproduced=True)
            receipt.unlink()
            with self.assertRaises(contracts.ProjectError):
                gates.check_baseline(self.root,self.research,reproduced=True)

    def test_missing_frozen_seed_is_rejected(self):
        with self.assertRaisesRegex(contracts.ProjectError,'every frozen seed'): self.baseline()

    def test_changed_config_snapshot_is_rejected(self):
        self.write('runs/baseline-7/config.json',{'changed':True})
        with self.assertRaisesRegex(contracts.ProjectError,'configuration snapshot'): self.baseline()

    def test_changed_registered_data_is_rejected(self):
        self.write('data.txt','changed fixture',raw=True)
        self.resources['data'][0]['fingerprint']=gates.digest(self.root/'data.txt')
        self.write('configs/resources.json',self.resources)
        with self.assertRaisesRegex(contracts.ProjectError,'fingerprint'): self.baseline()

    def test_fabricated_reproduced_aggregate_is_rejected(self):
        self.analysis['comparison']['reproduced']=0.6
        with self.assertRaisesRegex(contracts.ProjectError,'aggregate'): self.baseline()

    def test_changed_paper_reported_value_is_rejected(self):
        self.analysis['comparison']['paper_reported']=0.6
        with self.assertRaisesRegex(contracts.ProjectError,'paper_reported'): self.baseline()

    def test_modified_manifest_command_is_rejected(self):
        self.manifest['command'][1]=str(self.root/'unreviewed.py')
        with self.assertRaisesRegex(contracts.ProjectError,'command'): check_run_evidence(self.root,self.manifest)

if __name__=='__main__': unittest.main()
