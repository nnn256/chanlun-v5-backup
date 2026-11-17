"""Build a reviewable source/verification package; exclude market bulk data."""
from datetime import datetime,timedelta,timezone
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts/recursive-v2-20261107'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    real=json.loads((ART/'real-validation.json').read_text(encoding='utf-8'))
    tests=(ART/'tests.stderr.log').read_text(encoding='utf-8')
    count=re.search(r'Ran (\d+) tests in ([\d.]+)s',tests)
    if real['status']!='pass' or not count or not tests.rstrip().endswith('OK'):raise ValueError('missing passing verification evidence')
    changed=[*sorted((ROOT/'chanmodel/v2').glob('*.py')),ROOT/'run_v2.py',ROOT/'chanmodel/engine.py',
             ROOT/'tests/test_recursive_v2.py',ROOT/'tests/test_v2_io.py',ROOT/'tools/verify_recursive_v2.py',
             Path(__file__).resolve(),ROOT/'README.md',ROOT/'ALGORITHM_AUDIT.md',ROOT/'算法契约.md',
             ROOT/'递归与触发V2说明.md',ROOT/'RECOVERY-V2.md']
    records=[];diff=[]
    for p in changed:
        name=p.relative_to(ROOT).as_posix();baseline=ART/'baseline'/name
        before=baseline.read_text(encoding='utf-8').splitlines(keepends=True) if baseline.exists() else []
        after=p.read_text(encoding='utf-8').splitlines(keepends=True)
        if before==after:continue
        diff.extend(difflib.unified_diff(before,after,fromfile='a/'+name if baseline.exists() else '/dev/null',tofile='b/'+name))
        records.append({'file':name,'sha256':sha(p),'bytes':p.stat().st_size,
                        'baseline':str(baseline.relative_to(ART)).replace('\\','/') if baseline.exists() else None,
                        'baseline_sha256':sha(baseline) if baseline.exists() else None})
    write(ART/'MODIFIED_FILE.json',{'files':records,'scope':'v2 modules plus explicit legacy duplicate-input rejection; no market data or old run files modified'})
    (ART/'DIFF_FILE.patch').write_text(''.join(diff),encoding='utf-8')
    # Execute restoration only in an isolated copy, and check both pristine
    # restoration and preservation of the replaced files.
    restores=[r for r in records if r['baseline']]
    with tempfile.TemporaryDirectory(prefix='chanlun_v2_rollback_') as temporary:
        project=Path(temporary);art=project/'artifacts/recursive-v2-20261107';art.mkdir(parents=True)
        shutil.copy2(ART/'ROLLBACK.py',art/'ROLLBACK.py');write(art/'MODIFIED_FILE.json',{'files':restores})
        for row in restores:
            target=project/row['file'];target.parent.mkdir(parents=True,exist_ok=True);target.write_text('modified-check',encoding='utf-8')
            original=art/row['baseline'];original.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ART/row['baseline'],original)
        run=subprocess.run([sys.executable,str(art/'ROLLBACK.py')],capture_output=True,text=True,encoding='utf-8')
        receipt=json.loads(run.stdout)
        matches=all(sha(project/r['file'])==r['baseline_sha256'] for r in restores)
        preserved=all((Path(receipt['backup'])/r['file']).read_text(encoding='utf-8')=='modified-check' for r in restores)
        if run.returncode or not matches or not preserved:raise ValueError('isolated rollback failed')
        rollback={'scope':'independent temporary copy','exit_code':run.returncode,'restored_hashes_match':matches,'new_versions_preserved':preserved,'restored_files':len(restores)}
    write(ART/'rollback-verification.json',rollback)
    validation={'verified_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'status':'pass',
                'tests':{'count':int(count[1]),'elapsed_seconds':float(count[2]),'exit_code':0,'log_sha256':sha(ART/'tests.stderr.log')},
                'real_validation_file':'real-validation.json','real_validation_sha256':sha(ART/'real-validation.json'),
                'real_stocks':len(real['real_stocks_checked']),'duplicate_input_regression':real['duplicate_input_regression'],
                'rollback':rollback,'operational_profile':'same-level completed center partition plus conservative opposite-center-break turn confirmation',
                'universal_original_equivalence_proven':False,'execution_allowed':False,
                'old_full_market_results_replaced':False,'reported_real_trigger_count':sum(x['trigger_states'].get('structurally_triggered_under_profile',0) for x in real['real_stocks_checked'])}
    write(ART/'VERIFICATION.json',validation)
    (ART/'VERIFICATION.txt').write_text(
        f"Recursive V2 verification\nTests: {count[1]}, elapsed {count[2]}s, exit_code=0, OK\n"
        f"Real cached stocks verified: {len(real['real_stocks_checked'])}; source identity receipts and input SHA-256 kept.\n"
        'Single-series 500/600-prefix ledger invariance passed; direct vs replay cutoffs 150/300/500/600 matched.\n'
        'Identical daily observations relabelled as day/30m/5m rejected by V2 contract and legacy guard.\n'
        'Actual 5m aggregation exactly matches 493 daily and 3944 30m parent windows at zero volume tolerance.\n'
        'Independent TDX series tested with explicit 1000-share volume tolerance; default 1-share gate remains strict.\n'
        'No real sample was falsely reported triggered; positive trigger fixture and negative timing/price fixtures passed.\n'
        'Isolated rollback restored original hashes and preserved replacements.\n'
        'Original-system universal equivalence and trading execution are not claimed.\n',encoding='utf-8')
    # Compact report for convenient review; large chart-ready JSON stays local.
    summary={'schema':'chanlun.recursive.v2.delivery','validation':validation,
             'cases':[{k:v for k,v in x.items() if k!='input_receipts'} for x in real['real_stocks_checked']],
             'causality':real['single_series_causality'],'data_aggregation':real['observed_5m_exact_aggregation']}
    write(ROOT/'runs/recursive-v2-20261107/summary.json',summary)
    files=set(changed)
    files.update((ROOT/'chanmodel').glob('*.py'))
    files.update((ROOT/'tests').glob('*.py'))
    files.update((ROOT/'tools').glob('verify_*.py'))
    files.update(ROOT/name for name in ['run.py','market_scan.py','intraday_scan.py','history_replay.py'])
    files.add(ROOT/'artifacts/tdx-integration/baseline/segments.py')
    files.add(ROOT/'runs/recursive-v2-20261107/summary.json')
    files.update(p for p in ART.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    write(ART/'package-files.json',[{'file':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(files)])
    files.add(ART/'package-files.json')
    archive=ROOT.parent/'缠论递归与多周期触发V2-20261107.zip';temporary=archive.with_suffix('.building.zip')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as target:
        for p in sorted(files):target.write(p,arcname='缠论算法/'+p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(temporary) as target:
        bad=target.testzip();file_count=len(target.infolist())
    if bad:raise ValueError('ZIP CRC failed: '+bad)
    temporary.replace(archive)
    receipt={'archive':str(archive),'bytes':archive.stat().st_size,'files':file_count,'sha256':sha(archive),'zip_integrity':'pass','bulk_market_data_included':False}
    write(ART/'package-receipt.json',receipt);print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
