import gzip
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from run_v5_recursive_market import latest_for_symbols, resumable_success
from import_v5_results_to_workbench import reusable_result


class V5ResumeContractTests(unittest.TestCase):
    cutoff='2026-11-13T15:00:00+08:00'

    def source_files(self, folder, symbol='sh600000'):
        cache=folder/'cache';csv=cache/'tdx/day/ohlcv'/f'{symbol}.csv'
        meta=cache/'tdx/day/metadata'/f'{symbol}.json'
        csv.parent.mkdir(parents=True);meta.parent.mkdir(parents=True)
        csv.write_text('closed_at,open,high,low,close,volume\n'
                       f'{self.cutoff},10,12,9,11,1000\n',encoding='utf-8')
        digest=hashlib.sha256(csv.read_bytes()).hexdigest()
        meta.write_text(json.dumps({'symbol':symbol,'period':'day','adjustment':'unadjusted',
            'source':'tdx','csv_sha256':digest}),encoding='utf-8')
        return csv,meta,digest

    def test_runner_reuses_only_matching_rank_cutoff_source_and_detail(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp);csv,meta,digest=self.source_files(folder)
            detail=folder/'run/details/sh600000.json.gz';detail.parent.mkdir(parents=True)
            report={'profile':'source_declared_complete_study_layers_v1','as_of':self.cutoff,
                    'max_rank':8,'input_sha256':digest,'config':{'stroke_mode':'strict',
                    'second_policy':'conservative','third_boundary':'strict_outside','max_depth':3}}
            detail.write_bytes(gzip.compress(json.dumps(report).encode()))
            row={'symbol':'sh600000','status':'success','max_rank':8,'as_of':self.cutoff,
                 'source_receipt':{'csv_sha256':digest}}
            self.assertTrue(resumable_success(row,'sh600000',csv,meta,detail,self.cutoff,8))
            self.assertFalse(resumable_success(row,'sh600000',csv,meta,detail,self.cutoff,3))
            self.assertFalse(resumable_success(row,'sh600000',csv,meta,detail,'2026-11-12T15:00:00+08:00',8))
            detail.unlink()
            self.assertFalse(resumable_success(row,'sh600000',csv,meta,detail,self.cutoff,8))

    def test_resume_ledger_is_scoped_to_selected_symbols(self):
        with TemporaryDirectory() as tmp:
            ledger=Path(tmp)/'status.jsonl'
            ledger.write_text('\n'.join(json.dumps({'symbol':symbol,'status':'success'})
                for symbol in ('sh600000','sz000001','sh600001'))+'\n',encoding='utf-8')
            self.assertEqual(set(latest_for_symbols(ledger,{'sz000001'})),{'sz000001'})

    def test_importer_reuses_only_matching_run_and_source_identity(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp);csv,meta,digest=self.source_files(folder)
            run=folder/'run';details=run/'details';details.mkdir(parents=True)
            report={'profile':'source_declared_complete_study_layers_v1','as_of':self.cutoff,
                    'max_rank':8,'input_sha256':digest,
                    'certificate_audit':{'state':'passed'}}
            detail=details/'sh600000.json.gz'
            detail.write_bytes(gzip.compress(json.dumps({'reports':{'day':report}}).encode()))
            (run/'summary.json').write_text(json.dumps({'profile':'course_feature_sequence_recursive_v2',
                'cutoff':self.cutoff,'max_rank':8}),encoding='utf-8')
            state=folder/'state';artifact=state/'imports-v5/sh600000.json.gz';artifact.parent.mkdir(parents=True)
            bundle={'summary':{'source_csv_sha256':digest},
                    'evidence':{'reports':{'day':{'input_sha256':digest}}}}
            artifact.write_bytes(gzip.compress(json.dumps(bundle).encode()))
            row={'summary':json.dumps({'workbench_profile':'course_feature_sequence_recursive_v2',
                                       'as_of':self.cutoff,'max_rank':8,'source_csv_sha256':digest}),
                 'artifact':'imports-v5/sh600000.json.gz'}
            self.assertTrue(reusable_result(row,'sh600000',detail,csv,meta,state,self.cutoff,8))
            self.assertFalse(reusable_result(row,'sh600000',detail,csv,meta,state,self.cutoff,3))
            csv.write_text(csv.read_text(encoding='utf-8')+'2026-11-14T15:00:00+08:00,10,13,9,12,1100\n',encoding='utf-8')
            self.assertFalse(reusable_result(row,'sh600000',detail,csv,meta,state,self.cutoff,8))


if __name__=='__main__':
    unittest.main()
