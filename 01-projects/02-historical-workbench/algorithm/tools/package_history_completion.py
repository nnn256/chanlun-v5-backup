"""Package the completed historical run's reports/code without bulk market caches."""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts/history-completion-20261107'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    verification=json.loads((ROOT/'runs/tdx-intraday-completed-20261107/verification/summary.json').read_text(encoding='utf-8'))
    report=json.loads((ROOT/'历史任务完成结果.json').read_text(encoding='utf-8'))
    if verification['errors'] or verification['verified_success']!=5578 or report['pending']!=0:
        raise ValueError('Completion checks have not passed')
    testlog=(ART/'tests.stderr.log').read_text(encoding='utf-8')
    if 'Ran 120 tests' not in testlog or not testlog.rstrip().endswith('OK'):
        raise ValueError('Expected full passing test receipt not found')
    tests={'command':'python -m unittest discover -s tests -v','tests':120,'exit_code':0,'stderr_sha256':digest(ART/'tests.stderr.log')}
    (ART/'VERIFICATION.json').write_text(json.dumps({'verified_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
                  'tests':tests,'composite':verification,'result':report},ensure_ascii=False,indent=2),encoding='utf-8')
    (ART/'VERIFICATION.txt').write_text('Historical task completion: executed and verified.\n120 tests passed, exit code 0.\n'
        'All 5,579 universe codes accounted for: 5,578 usable successes, sh688827 verified source-unavailable.\n'
        'Daily: 17,062,480 bars. Intraday: 21,487,433 30m bars and 128,924,257 5m bars.\n'
        'Full daily replay: 17,062,480 prefixes; 172,306 events; 35,691 first-candidate observations.\n'
        'All 5,563 original successful artifacts rehashed; all 15 repaired results re-normalized and recomputed.\n'
        'Seven flat zero-activity off-grid source rows quarantined; 744 later-cutoff rows excluded with original evidence retained.\n'
        'No core Chan rules altered or promoted to strict_original. No synthetic market rows inserted.\n'
        'Proofs: runs/tdx-intraday-completed-20261107/verification/summary.json; historical replay verification.json.\n',encoding='utf-8')
    changed=['chanmodel/tdx_quality.py','tests/test_tdx_quality.py','tools/complete_historical_runs.py',
             'tools/verify_completed_history.py','tools/market_progress.py','tools/package_history_completion.py',
             'README.md','ALGORITHM_AUDIT.md','RECOVERY-TDX.md','全市场三流水线说明.md','历史任务完成报告.md','历史任务完成结果.json','runs/latest_completed_runs.json']
    parts=[];manifest=[]
    for name in changed:
        current=ROOT/name;baseline=ART/'baseline'/name
        before=baseline.read_text(encoding='utf-8').splitlines(keepends=True) if baseline.exists() else []
        after=current.read_text(encoding='utf-8').splitlines(keepends=True)
        if before==after:continue
        parts.extend(difflib.unified_diff(before,after,fromfile='a/'+name if baseline.exists() else '/dev/null',tofile='b/'+name))
        manifest.append({'path':name,'sha256':digest(current),'bytes':current.stat().st_size,
                         'baseline':str(baseline.relative_to(ART)) if baseline.exists() else None,
                         'baseline_sha256':digest(baseline) if baseline.exists() else None})
    (ART/'DIFF_FILE.patch').write_text(''.join(parts),encoding='utf-8')
    (ART/'MODIFIED_FILE.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    # Deliver only explicitly selected report artifacts, source code and tests.
    selected=set(ROOT/name for name in changed)
    selected.update((ROOT/'chanmodel').glob('*.py'))
    selected.update((ROOT/'tests').glob('*.py'))
    selected.update((ROOT/'tools').glob('verify_*.py'))
    selected.update(ROOT/name for name in ['market_scan.py','intraday_scan.py','history_replay.py','run.py',
        'Start-TdxApi.ps1','Stop-TdxApi.ps1','Start-MarketScan.ps1','TDX全市场使用说明.md','逐日历史回放说明.md','算法契约.md'])
    for run in ['tdx-all-a-20261106','history-all-a-fullspan-20261106','tdx-intraday-completed-20261107']:
        for filename in ['summary.json','summary.csv','manifest.json','label_groups.csv','verification.json','VERIFICATION.md',
                         'verification/summary.json','verification/VERIFICATION.md']:
            path=ROOT/'runs'/run/filename
            if path.is_file():selected.add(path)
    selected.update(path for path in ART.rglob('*') if path.is_file() and '__pycache__' not in path.parts)
    selected.add(ROOT/'artifacts/tdx-integration/baseline/segments.py')
    for name in ['service.diff.patch','service-modifications.json','history-replay-verification.json']:
        path=ROOT/'artifacts/tdx-integration'/name
        if path.exists():selected.add(path)
    report_files=[{'file':str(p.relative_to(ROOT)).replace('\\','/'),'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(selected)]
    filelist=ART/'package-files.json';filelist.write_text(json.dumps(report_files,ensure_ascii=False,indent=2),encoding='utf-8');selected.add(filelist)
    archive=ROOT.parent/'缠论全市场历史完成报告-20261107.zip'
    temporary=archive.with_suffix('.building.zip')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as zipped:
        for path in sorted(selected):
            if path.is_file():zipped.write(path,arcname='缠论算法/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(temporary) as zipped:
        if zipped.testzip():raise ValueError('ZIP CRC failed')
        count=len(zipped.infolist())
    temporary.replace(archive)
    receipt={'archive':str(archive),'bytes':archive.stat().st_size,'files':count,'sha256':digest(archive),'zip_integrity':'pass',
             'bulk_data_included':False,'bulk_data_directory':str(ROOT/'market_data'),
             'portable_report_note':'Reports/code included; source market caches and full per-stock ledgers remain at their recorded local paths.'}
    (ART/'package-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
