"""Run a local native-minute research monitor into a dedicated data directory.

Start only after the separate offline study has been reviewed. No upload,
broker connection or order execution is performed. Default is one silent
baseline; --watch continues inside CN exchange session windows.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols',nargs='+',required=True,help='explicit exchange-prefixed securities')
    parser.add_argument('--period',choices=('1m','5m'),default='5m')
    parser.add_argument('--data-root',type=Path,required=True,help='isolated local monitor state root, e.g. F:/ChanlunMonitor')
    parser.add_argument('--base-url',help='existing loopback TDX endpoint; does not start a second service')
    parser.add_argument('--warm-cache-root',type=Path,help='hash-verified native market_data folder for silent local prewarm')
    parser.add_argument('--offline-prewarm-only',action='store_true',help='prepare native/reference state from local cache and exit without network')
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--interval',type=int,default=60)
    parser.add_argument('--max-confirmation-delay-minutes',type=int,default=60)
    parser.add_argument('--max-pivot-distance-pct',type=float,default=2.0)
    args=parser.parse_args()
    if args.interval<15:parser.error('--interval must be >=15 seconds')
    args.data_root=args.data_root.expanduser().resolve()
    args.data_root.mkdir(parents=True,exist_ok=True)
    os.environ['CHANLUN_WORKBENCH_ROOT']=str(args.data_root)
    if args.base_url:
        from urllib.parse import urlsplit
        parsed=urlsplit(args.base_url)
        if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or not parsed.port:
            parser.error('--base-url must be an existing loopback HTTP endpoint with an explicit port')
        os.environ['CHANLUN_TDX_BASE_URL']=args.base_url
    if args.offline_prewarm_only and not args.warm_cache_root:parser.error('--offline-prewarm-only requires --warm-cache-root')
    sys.path.insert(0,str(ROOT))
    from chanmodel.tdx_data import atomic_json,now_iso,symbol
    from chanmodel.intraday_research import IntradayConfig
    from workbench import monitor,store
    config=IntradayConfig(max_confirmation_delay_minutes=args.max_confirmation_delay_minutes,
                          max_pivot_distance_pct=args.max_pivot_distance_pct)
    symbols=list(dict.fromkeys(symbol(value) for value in args.symbols))
    store.initialize()
    with store.connect() as db:
        db.executemany('INSERT OR IGNORE INTO universe(symbol,code,name,exchange,active) VALUES(?,?,?,?,1)',
                       [(value,value[2:],value,value[:2]) for value in symbols])
    settings=monitor.configure({'scope':'selected','symbols':symbols,'enabled':False,
              'structure_mode':'intraday','intraday_period':args.period,'workers':min(2,len(symbols)),
              'intraday_config':{'max_confirmation_delay_minutes':config.max_confirmation_delay_minutes,
                                 'max_pivot_distance_pct':config.max_pivot_distance_pct}})
    info={'symbols':symbols,'period':args.period,'interval':args.interval,'started_at':now_iso(),
          'config':settings,'watch':args.watch,'execution_allowed':False,'upload_performed':False,
          'semantics':'new closed-bar local-structure reversal research alerts; historical warm-up is silent'}
    atomic_json(args.data_root/'monitor-settings.json',info)
    if args.warm_cache_root:
        from workbench.intraday_monitor import warm_from_cache
        warm=[]
        for value in symbols:
            warm.append(warm_from_cache(value,args.period,args.warm_cache_root,config))
        atomic_json(args.data_root/'monitor-warmup.json',{'warmup':warm,'at':now_iso(),'execution_allowed':False})
        print(json.dumps({'state':'local_cache_warmed','symbols':len(warm),'bars':sum(p['bars'] for p in warm),
                          'network_requested':False,'notifications_sent':0},ensure_ascii=False),flush=True)
    if args.offline_prewarm_only:return
    first=True
    try:
        while True:
            state=monitor.session_state()
            if first or state['state']=='session_window':
                run=monitor.run_scan('structures',settings)
                overview=monitor.overview(limit=1000)
                atomic_json(args.data_root/'latest-monitor.json',overview)
                print(json.dumps({'at':now_iso(),'state':run.get('error','calculated'),
                                  'symbols_done':run['done'],'failed':run['failed'],'alerts':run['alerts'],
                                  'session':state['state'],'output':str(args.data_root/'latest-monitor.json')},
                                 ensure_ascii=False),flush=True)
                first=False
            else:
                atomic_json(args.data_root/'monitor-idle.json',{'at':now_iso(),'state':state,
                             'reason':'outside exchange session; historical bars are not a live alert'})
            if not args.watch:break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        monitor.STOP.set()
    finally:
        atomic_json(args.data_root/'monitor-stopped.json',{'at':now_iso(),'execution_allowed':False})


if __name__=='__main__':main()
