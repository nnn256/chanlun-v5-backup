"""Check real cached full spans through both unchanged daily engines."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    root=a.root.resolve();sys.path.insert(0,str(root/'code/v4'))
    from workbench.backtest_cache import resolve_sources
    from chanmodel.native_market_backtest import run_market
    universe=root/'inputs/smoke-universe.json'
    records=json.loads(universe.read_text(encoding='utf-8-sig'))['records']
    selected=resolve_sources(root/'code/v4',records,explicit_cache=root/'smoke/acquisition/cache')
    source=root/'smoke/sources.json';source.write_text(json.dumps(selected,ensure_ascii=False),encoding='utf-8')
    result=run_market(records,root/'smoke/acquisition/cache',None,root/'smoke/v4',workers=1,
        cache_sources=selected['sources'],source_hashes={k:d['declared_csv_sha256'] for k,d in selected['source_details'].items()})
    if result['completed']!=len(records) or result['failed']:raise RuntimeError('V4 smoke failed')
    command=[sys.executable,str(root/'code/v3/scripts/run_full_daily_replay.py'),
        '--universe',str(universe),'--source-manifest',str(source),'--output',str(root/'smoke/v3'),
        '--min-free-memory-mb','512']
    subprocess.run(command,check=True,cwd=root)
    summary=json.loads((root/'smoke/v3/summary.json').read_text(encoding='utf-8'))
    if not summary['successful_coverage_complete']:raise RuntimeError('v3 smoke failed')
    (root/'smoke/verification.json').write_text(json.dumps({'passed':True,
        'securities':len(records),'v4_bars':result['bars'],'v3_bars':summary['bars'],
        'fresh_acquisition':json.loads((root/'smoke/acquisition/summary.json').read_text(encoding='utf-8'))},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'bars':summary['bars'],'securities':len(records)}))


if __name__=='__main__':main()
