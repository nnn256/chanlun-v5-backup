"""Compact progress snapshot for the three authorized all-market pipelines."""
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs-dir',type=Path,default=ROOT/'runs')
    parser.add_argument('--date',default='20261106')
    args=parser.parse_args()
    rows=[]
    index_path=args.runs_dir/'latest_completed_runs.json'
    latest=json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() and args.date=='20261106' else {}
    for kind,name in [('daily',f'tdx-all-a-{args.date}'),('intraday',f'tdx-intraday-all-a-{args.date}'),('history',f'history-all-a-fullspan-{args.date}')]:
        name=latest.get(kind,name)
        path=args.runs_dir/name/'summary.json'
        if not path.exists():
            rows.append({'pipeline':kind,'status':'not_started','file':str(path)})
            continue
        data=json.loads(path.read_text(encoding='utf-8'))
        rows.append({'pipeline':kind,'processed':data.get('processed'),'universe':data.get('universe_count'),
                     'success':data.get('success'),'failed_or_empty':data.get('failed_or_empty',data.get('failed')),
                     'source_unavailable':data.get('unavailable_count'),
                     'pending':data.get('pending'),'updated_at':data.get('updated_at'),
                     'coverage':data.get('total_bars',data.get('total_history_bars',data.get('visited_daily_prefixes'))),
                     'signals':data.get('candidate_first_seen_count'),'file':str(path.resolve())})
    print(json.dumps(rows,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
