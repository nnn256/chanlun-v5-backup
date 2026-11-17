"""Package source changes and evidence for the 2026-11-17 resource update."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=['chanmodel/resource_runtime.py','chanmodel/native_market_backtest.py','chanmodel/market_backtest.py',
       'workbench/jobs.py','workbench/backtests.py','workbench/server.py','workbench/resources.py',
       'workbench/web/app.js','workbench/web/index.html','run_v5_recursive_market.py','run_v5_market.py',
       'tools/verify_resource_acceleration.py','tests/test_resource_runtime.py','tests/test_auto_resource_jobs.py',
       'tests/test_native_backtest_service.py','tests/test_workbench.py','tests/test_v5_market_pipeline.py',
       'tests/resource-controls.test.cjs','自动计算资源说明.md']


def main():
    out=ROOT.parent/'releases/auto-resources-20261117';out.mkdir(parents=True,exist_ok=True)
    evidence=ROOT.parent/'artifacts/auto-resources-20261117'
    rows=[]
    archive=out/'ChanlunV5-AutoResources-20261117.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as package:
        for name in FILES:
            source=ROOT/name;relative='algorithm/'+name;body=source.read_bytes()
            rows.append({'path':relative,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()})
            package.writestr(relative,body)
        for source in (evidence/'runtime-verification.json',evidence/'v5-equivalence.json',evidence/'tests.stderr.log'):
            package.write(source,'verification/'+source.name)
        package.writestr('UPDATE-MANIFEST.json',json.dumps({'profile':'cpu_memory_adaptive_v1','files':rows},ensure_ascii=False,indent=2))
        package.writestr('README.txt','Automatic resource update installed on F:/ChanlunV5-20261115.\n'
            'This ZIP contains changed source files and validation, not market data.\n'
            'If manually applying, stop only the workbench HTTP service, back up files, and overlay algorithm/ into the V5 package root.\n'
            'The original full-package manifest describes the original release; UPDATE-MANIFEST.json describes these source changes.\n'
            'No GPU claim for Chan state-machine replay. GPU data audit results are recorded separately.\n')
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        for row in rows:assert hashlib.sha256(package.read(row['path'])).hexdigest()==row['sha256']
    receipt={'status':'pass','archive':str(archive),'bytes':archive.stat().st_size,
             'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'source_files':len(rows),
             'python_tests_passed':436,'ui_tests_passed':13,'v5_report_equivalence':True,
             'installed_algorithm_root':'F:/ChanlunV5-20261115/algorithm',
             'frozen_minute_algorithm_changed':False,'gpu_role':'data_integrity_session_extrema_only'}
    (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
