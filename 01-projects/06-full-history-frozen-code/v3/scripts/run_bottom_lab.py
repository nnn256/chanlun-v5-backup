"""Run or watch the local frozen-rule research pipeline; never edits source code."""
from pathlib import Path
import argparse
import json
import sys
import time
from datetime import datetime,timedelta,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from web import bottom_lab as lab


def heartbeat(state, **fields):
    path=lab.root()/'watch-status.json'
    value={'state':state,'heartbeat_at':datetime.now(lab.CN).isoformat(timespec='seconds'),
           'pid':__import__('os').getpid(),**fields}
    lab.dump(path,value)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sample-size',type=int,default=120)
    parser.add_argument('--seed',type=int,default=20261113)
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--interval-minutes',type=int,default=60)
    args=parser.parse_args();last_signature=None;last_date=None
    if args.watch:
        latest=lab.root()/'runs/latest.json'
        try:
            saved=json.loads(latest.read_text(encoding='utf-8'))
            current_signature=lab.source_manifest()['sha256']
            if saved.get('source_manifest',{}).get('sha256')==current_signature and saved.get('state') in {'completed','partial'}:
                # The final run already covers this source revision. A watcher
                # started afterwards waits for the next source/date change.
                last_signature=current_signature
                last_date=datetime.now(lab.CN).date().isoformat()
        except (OSError,ValueError,TypeError):
            pass
    heartbeat('running',sample_size=args.sample_size,interval_minutes=args.interval_minutes)
    try:
      while True:
        current=datetime.now(lab.CN);signature=lab.source_manifest()['sha256']
        heartbeat('running',sample_size=args.sample_size,interval_minutes=args.interval_minutes,
                  source_manifest=signature,last_check_at=current.isoformat(timespec='seconds'))
        due=(last_signature is None or signature!=last_signature or
             (current.weekday()<5 and current.hour>=16 and current.date().isoformat()!=last_date))
        if due:
            job=lab.start(args.sample_size,args.seed,args.refresh or args.watch)
            heartbeat('running',sample_size=args.sample_size,interval_minutes=args.interval_minutes,
                      source_manifest=signature,last_run_id=job['id'],last_run_state='running')
            print(json.dumps({'event':'started','id':job['id'],'version':job['version'],'source_manifest':job['source_manifest']['sha256']},ensure_ascii=False),flush=True)
            completed=-1
            while True:
                result=lab.status(job['id'])
                if result['completed']!=completed:
                    print(json.dumps({k:result.get(k) for k in ('id','state','stage','completed','total','bars','failed','last_symbol')},ensure_ascii=False),flush=True)
                    completed=result['completed']
                if result['state'] in {'completed','partial','failed'}:
                    print(json.dumps({'event':'finished','id':result['id'],'state':result['state'],'summary':result.get('summary'),'versions':result.get('versions'),'promotion':result.get('promotion')},ensure_ascii=False),flush=True)
                    heartbeat('running',sample_size=args.sample_size,interval_minutes=args.interval_minutes,
                              source_manifest=signature,last_run_id=result['id'],last_run_state=result['state'],
                              last_finished_at=result.get('finished_at'))
                    break
                time.sleep(1)
            last_signature=signature;last_date=current.date().isoformat()
        if not args.watch:
            heartbeat('stopped',sample_size=args.sample_size,last_run_id=job['id'] if due else None)
            return
        # Short waits preserve interruptibility; source changes are checked each minute.
        for _ in range(max(1,args.interval_minutes)):
            time.sleep(60)
            if lab.source_manifest()['sha256']!=last_signature:break
    finally:
      heartbeat('stopped',sample_size=args.sample_size)


if __name__=='__main__':main()
