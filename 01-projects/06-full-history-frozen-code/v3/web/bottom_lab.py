"""Local research pipeline: immutable versions, chronological ablations, live tails."""
from __future__ import annotations

from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from fastapi import HTTPException
from chanmodel.bottom_research import (BOTTOM_VERSION,VARIANTS,BottomSession,eligible,
    evaluate_events,time_splits,split_outcomes,split_metrics,HORIZON,TARGET_RETURN,_bar)
from web import bottom_data as data
from web.compute_budget import budget,bounded
from chanmodel.local_compute import OrderedLocalMap

ROOT=Path(__file__).resolve().parents[1]
CN=timezone(timedelta(hours=8))
APP_VERSION='2026.11.17.phase.1'
RUN_VERSION='bottom_walkforward_ablation_v3'
pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='bottom-validation')
guard=threading.RLock();jobs={};sessions=OrderedDict();benchmark_cache=None
benchmark_cached_at=0.0
WATCH_HEARTBEAT_SECONDS=180


def root():return data.runtime_root()
def now():return datetime.now(CN).isoformat(timespec='seconds')
def dump(path,value):data._atomic_json(path,value)
def pack(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    content=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_bytes(gzip.compress(content,compresslevel=3,mtime=0));tmp.replace(path)
def unpack(path):return json.loads(gzip.decompress(Path(path).read_bytes()))


def _watch_status():
    """Read the local watcher heartbeat; configured does not mean currently running."""
    path=root()/'watch-status.json'
    if not path.is_file():
        return {'state':'not_running','configured':True,'heartbeat_at':None}
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        heartbeat=value.get('heartbeat_at')
        fresh=False
        if isinstance(heartbeat,str):
            stamp=datetime.fromisoformat(heartbeat)
            age=(datetime.now(CN)-stamp).total_seconds()
            fresh=stamp.tzinfo is not None and 0<=age<=WATCH_HEARTBEAT_SECONDS
        if value.get('state')=='running' and not fresh:value['state']='stale'
        value['configured']=True
        return value
    except (OSError,ValueError,TypeError):
        return {'state':'unreadable','configured':True,'heartbeat_at':None}


def source_manifest():
    paths=['chanmodel/bottom_research.py','chanmodel/market_phase.py','chanmodel/local_compute.py','chanmodel/local_gpu.py',
           'web/bottom_lab.py','web/bottom_data.py',
           'chanmodel/structure.py','chanmodel/segments.py','chanmodel/causal_replay.py',
           'frontend/src/research/BottomResearch.tsx','frontend/src/research/bottomResearchData.ts',
           'frontend/src/research/MarketPhasePanel.tsx','frontend/src/research/marketPhaseData.ts',
           'tests/test_bottom_accuracy_regressions.py']
    hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths if (ROOT/p).is_file()}
    return {'version':BOTTOM_VERSION,'run_version':RUN_VERSION,'app_version':APP_VERSION,'files':hashes,
        'sha256':hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),
        'parameters_frozen_before_evaluation':True,'variants':list(VARIANTS),
        'target_return':TARGET_RETURN,'horizon_sessions':HORIZON,
        'definition_mode':'bottom_structure_proxy_v1','strict_original_equivalence_proven':False}


def _benchmark(refresh=False):
    global benchmark_cache,benchmark_cached_at
    with guard:
        if benchmark_cache and not refresh and time.monotonic()-benchmark_cached_at<300:return benchmark_cache
    result=data.fetch_benchmark(refresh=True if benchmark_cache else refresh)
    values={b['closed_at'][:10]:b['close'] for b in result['bars'] if b['is_closed']}
    with guard:benchmark_cache=(values,result['metadata']);benchmark_cached_at=time.monotonic()
    return values,result['metadata']


def _emotion_archive():
    path=ROOT/'data/stock_data/sentiment_history.jsonl';result={}
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                value=json.loads(line);date=str(value['date']);date=date[:4]+'-'+date[4:6]+'-'+date[6:8] if len(date)==8 else date[:10]
                result[date]={**value,'known_at':now(),'historical_usable':False,'publication_time_verified':False,
                    'source':'repository daily emotion archive','reason':'historical publication timestamps unavailable'}
            except (ValueError,KeyError,TypeError):continue
    return result


def overview():
    latest=root()/'runs/latest.json'
    latest_run=json.loads(latest.read_text(encoding='utf-8')) if latest.is_file() else None
    with guard:active=next((dict(x) for x in jobs.values() if x['state'] in {'queued','running'}),None)
    watcher=_watch_status()
    return {'version':APP_VERSION,'engine_version':BOTTOM_VERSION,'run_version':RUN_VERSION,
        'latest_run':latest_run,'active_run':active,'source_manifest':source_manifest(),
        'available_symbols':latest_run.get('symbols',[]) if latest_run else [],
        'automation':{'enabled':watcher.get('state')=='running','configured':True,'state':watcher.get('state'),
            'heartbeat_at':watcher.get('heartbeat_at'),'last_run_id':watcher.get('last_run_id'),
            'mode':'explicit local script schedule; no source-code self-modification',
            'command':'py -3.14 scripts/run_bottom_lab.py --watch --sample-size 120',
            'realtime':'active chart requests tail every 15 seconds; forming OHLC never changes confirmed events'},
        'limitations':['current listed-stock sample has survivorship bias',
            'raw OHLC corporate actions are not universally certified; events crossing large gaps are excluded',
            'money-flow and sentiment history without publication evidence is excluded from historical filters',
            'chip inputs model traded-volume locations; shareholder holdings are not observed',
            'candidate state does not guarantee departure or profit'],
        'execution_allowed':False,'received_at':now()}


def start(sample_size=120,seed=20261113,refresh=False,symbols=None):
    if type(sample_size) is not int or not 4<=sample_size<=240:raise ValueError('sample_size must be 4..240')
    if type(seed) is not int or not 0<=seed<=2**32-1:raise ValueError('seed must be an unsigned 32-bit integer')
    if type(refresh) is not bool:raise ValueError('refresh must be a boolean')
    if symbols is not None and (not isinstance(symbols,list) or not symbols or len(symbols)>240 or any(not isinstance(value,str) for value in symbols)):
        raise ValueError('symbols must be a nonempty list of 1..240 strings')
    selection=data.sample_symbols(sample_size,seed) if not symbols else {'symbols':[{'symbol':data._code(x),'name':data._name(x)} for x in dict.fromkeys(symbols)],'seed':seed,'count':len(set(symbols)),'universe_semantics':'explicit local research selection'}
    if not 1<=len(selection['symbols'])<=240:raise ValueError('choose 1..240 distinct symbols')
    with guard:
        existing=next((dict(x) for x in jobs.values() if x['state'] in {'queued','running'}),None)
        if existing:return existing
        ident=datetime.now(CN).strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:6]
        job={'id':ident,'state':'queued','stage':'queued','version':BOTTOM_VERSION,'created_at':now(),
            'total':len(selection['symbols']),'completed':0,'failed':0,'bars':0,
            'selection':selection,'refresh':bool(refresh),'source_manifest':source_manifest(),'execution_allowed':False}
        jobs[ident]=job;dump(root()/f'runs/{ident}/status.json',job)
    pool.submit(_run,ident)
    return copy.deepcopy(job)


def status(ident):
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{6}',ident):raise HTTPException(422,'无效研究任务编号')
    with guard:
        if ident in jobs:return copy.deepcopy(jobs[ident])
    path=root()/f'runs/{ident}/status.json'
    if not path.is_file():raise HTTPException(404,'底部研究结果不存在')
    return json.loads(path.read_text(encoding='utf-8'))


def _update(ident,**fields):
    with guard:
        jobs[ident].update(fields);jobs[ident]['updated_at']=now();value=copy.deepcopy(jobs[ident])
    dump(root()/f'runs/{ident}/status.json',value)


@bounded('bottom_historical_symbol',wait=True)
def _replay_bottom_symbol(task):
    """Replay one stock's closed candles in an isolated local worker."""
    ident,record,benchmark,emotion,splits,refresh=task
    code=record['symbol'];folder=root()/f'runs/{ident}'
    try:
        dataset=data.fetch_daily(code,refresh=refresh)
        if any(dataset['metadata'].get(key)!=record['metadata'].get(key) for key in ('input_sha256','raw_sha256')):
            raise ValueError('dataset changed after collection; immutable run rejected before replay')
        rows=[bar for bar in dataset['bars'] if bar['is_closed']]
        session=BottomSession(code,benchmark_by_date=benchmark,emotion_by_date=emotion)
        for row in rows:session.append(row)
        bars=session.bars;events=[event for event in session.events if event['state']=='base_formed']
        all_labels=evaluate_events(code,bars,events,benchmark_by_date=benchmark)
        events_by_id={event['id']:event for event in events};exclusions=Counter();audit_labels=[]
        for label in all_labels:
            start=label['available_at_index'];end=label.get('max_observed_index',start)
            gap_indices=[index for index in range(max(1,start-60),min(len(bars),end+1))
                         if abs(bars[index].open/bars[index-1].close-1)>.25]
            if gap_indices:
                label['exclusion']='unverified_large_price_discontinuity'
                label['excluded_gap_indices']=gap_indices;exclusions[label['exclusion']]+=1
            audit_labels.append(label)
        outcomes={variant:[] for variant in VARIANTS}
        for variant in VARIANTS:
            selected=[copy.deepcopy(label) for label in audit_labels
                      if not label.get('exclusion') and eligible(events_by_id[label['event_id']],variant)]
            split_outcomes(selected,splits);outcomes[variant]=selected
        panel=session.snapshot()
        panel.update(name=record['name'],period='day',source_kind='live_bottom_research',data_as_of=bars[-1].closed_at,
            factor_coverage={**panel['factor_coverage'],'emotion':{**panel['factor_coverage']['emotion'],
                'source':'benchmark proxy + archive coverage separately'}},
            provenance=record['metadata'],run_id=ident,version=BOTTOM_VERSION)
        panel['coverage'].update(source=record['metadata']['source'],forming_count=len(dataset['bars'])-len(rows),
            source_input_sha256=record['metadata']['input_sha256'],source_rows=record['metadata']['source_rows'])
        pack(folder/f'panels/{code}.json.gz',panel)
        pack(folder/f'events/{code}.json.gz',{'symbol':code,'events':session.events,
            'outcomes':audit_labels,'input_sha256':panel['coverage']['input_sha256']})
        return {'symbol':code,'name':record['name'],'state':'completed','bars':len(rows),
            'states':dict(Counter(event['state'] for event in session.events)),'events':len(events),
            'exclusions':dict(exclusions),'first':bars[0].closed_at,'last':bars[-1].closed_at,
            'outcomes':outcomes}
    except Exception as error:
        return {'symbol':code,'state':'failed','error':type(error).__name__+': '+str(error)[:260]}


def _run(ident):
    try:
        request=status(ident);folder=root()/f'runs/{ident}'
        _update(ident,state='running',stage='data_collection',started_at=now())
        benchmark,benchmark_receipt=_benchmark(refresh=request['refresh'])
        emotion=_emotion_archive();raw=[];failures=[]
        for index,record in enumerate(request['selection']['symbols']):
            try:
                dataset=data.fetch_daily(record['symbol'],refresh=request['refresh'])
                raw.append({'symbol':record['symbol'],'name':dataset['name'],'metadata':dataset['metadata'],
                    'date_sequence':[b['closed_at'][:10] for b in dataset['bars'] if b['is_closed']]})
            except Exception as error:failures.append({'symbol':record['symbol'],'stage':'collection','error':str(error)[:240]})
            _update(ident,downloaded=index+1,failed=len(failures),last_symbol=record['symbol'])
        if not raw:raise ValueError('没有真实日K数据可用于底部研究')
        splits=time_splits([x['date_sequence'] for x in raw]);outcomes={v:[] for v in VARIANTS};stock_results=[];replay_failures=[]
        _update(ident,stage='causal_replay',split_dates=splits,data_receipts=[{k:x[k] for k in ('symbol','name','metadata')} for x in raw],
            benchmark_receipt=benchmark_receipt,total=len(raw),selection_size=request['total'])
        local_only=os.environ.get('LIANGCE_HOSTING','local-research') in {'local','local-research'}
        requested_workers=os.environ.get('LIANGCE_LOCAL_COMPUTE_WORKERS','auto') if local_only else 1
        reserve=max(768,int(os.environ.get('LIANGCE_LOCAL_COMPUTE_RESERVE_MIB','1024'))) if local_only else 1024
        worker_memory=max(128,int(os.environ.get('LIANGCE_LOCAL_COMPUTE_WORKER_MIB','256')))
        compute=OrderedLocalMap(_replay_bottom_symbol,
            [(ident,record,benchmark,emotion,splits,False) for record in raw],
            workers=requested_workers,worker_mib=worker_memory,reserve_mib=reserve)
        _update(ident,stage='causal_replay',compute_plan=compute.plan)
        for index,result in enumerate(compute,1):
            code=result['symbol']
            if result['state']=='completed':
                outcomes_by_variant=result.pop('outcomes')
                for variant in VARIANTS:outcomes[variant].extend(outcomes_by_variant[variant])
                stock_results.append(result)
            else:
                replay_failures.append({'symbol':code,'stage':'replay','error':result.get('error','worker failed')})
            versions=[{'version':variant,**split_metrics(outcomes[variant])} for variant in VARIANTS]
            _update(ident,completed=index,failed=len(failures)+len(replay_failures),
                bars=sum(row['bars'] for row in stock_results),last_symbol=code,compute_execution=compute.stats,
                versions=versions,stock_results=stock_results,failures=failures+replay_failures)
        _update(ident,compute_execution=compute.stats)
        if source_manifest()['sha256']!=request['source_manifest']['sha256']:
            raise ValueError('source changed during replay; results rejected')
        versions=[{'version':variant,**split_metrics(outcomes[variant])} for variant in VARIANTS]
        baseline=versions[0]['validation'];choices=[v for v in versions[1:] if v['validation']['evaluated']>=50 and
            v['validation']['mean_excess_return'] is not None and baseline['mean_excess_return'] is not None and
            v['validation']['mean_excess_return']>baseline['mean_excess_return']]
        chosen=max(choices,key=lambda v:v['validation']['mean_excess_return']) if choices else versions[0]
        promotion={'selected_on':'validation_only','candidate':chosen['version'],
            'state':'research_candidate' if choices else 'baseline_retained',
            'reason':'fixed ablations compared on validation; test metrics shown separately; code is never rewritten from test feedback',
            'automatic_source_modification':False,'test_used_for_selection':False}
        complete=len(failures)+len(replay_failures)==0
        _update(ident,state='completed' if complete else 'partial',stage='finished',finished_at=now(),
            versions=versions,promotion=promotion,
            summary={'successful_stocks':len(stock_results),'failed_stocks':len(failures)+len(replay_failures),
                'bars':sum(row['bars'] for row in stock_results),'base_events':sum(x['events'] for x in stock_results),
                'state_counts':dict(sum((Counter(x['states']) for x in stock_results),Counter())),
                'exclusions':dict(sum((Counter(x['exclusions']) for x in stock_results),Counter()))},
            symbols=[{'symbol':x['symbol'],'name':x['name']} for x in stock_results],
            factor_coverage={'money_flow':'historical snapshot excluded without publication proof',
                'chips':'rolling traded-volume price distribution proxy','emotion':'prefix index-price regime proxy',
                'emotion_archive_records':len(emotion)},
            validation_protocol={'split':splits,'same_barrier_order':'stop_first','execution':'next_session_open; T+1 exit earliest following session',
                'estimated_round_trip_cost':0.002,'shared_portfolio':False,
                'statistics':'independent event simulations; no promise of account profit; same-stock labels may overlap',
                'large_gap_exclusion':'.25 absolute open/previous-close over feature+label window'},
            realtime_verified=False)
        pack(folder/'outcomes.json.gz',outcomes)
        result=status(ident);dump(root()/'runs/latest.json',result)
    except Exception as error:
        _update(ident,state='failed',stage='failed',finished_at=now(),error=type(error).__name__+': '+str(error)[:350])


def live_panel(code,refresh=False):
    """Only new closed OHLC enter the incremental session; unfinished data is chart-only."""
    code=data._code(code);monotonic=time.monotonic();benchmark,_=_benchmark();emotion=_emotion_archive()
    with guard:
        item=sessions.get(code)
        if item and not refresh and monotonic-item['fetched_monotonic']<10:
            return copy.deepcopy(item['panel'])
    reason='cold_start';received=None;reused=bool(item);appended=0;tail_receipt=None
    if item:
        tail=data.fetch_tail(code,limit=10);received=tail['metadata']['received_at']
        tail_receipt={k:tail['metadata'].get(k) for k in ('requested_at','received_at','raw_sha256','raw_path','url','input_sha256','scope','source_rows')}
        # The all-history and recent-tail TDX endpoints can report volume with
        # different lot/share rounding. OHLC revisions and timestamp changes
        # are structural corrections; volume-only rounding must not replay the
        # entire immutable history.
        current={b.closed_at:(b.open,b.high,b.low,b.close) for b in item['session'].bars}
        closed=[x for x in tail['bars'] if x['is_closed']]
        overlap=any(x['closed_at'] in current for x in closed)
        revision=any(x['closed_at'] in current and current[x['closed_at']]!=tuple(x[k] for k in ('open','high','low','close')) for x in closed)
        if overlap and not revision:
            source_set={x['closed_at'] for x in closed}
            lower=closed[0]['closed_at'] if closed else ''
            upper=closed[-1]['closed_at'] if closed else ''
            saved_set={stamp for stamp in current if lower<=stamp<=min(upper,item['session'].bars[-1].closed_at)}
            source_overlap={stamp for stamp in source_set if stamp<=item['session'].bars[-1].closed_at}
            revision=source_overlap!=saved_set
        if overlap and not revision:
            session=item['session'];session.benchmark_by_date=benchmark;session._benchmark_dates=sorted(benchmark)
            rows=[x for x in closed if x['closed_at']>session.bars[-1].closed_at]
            for row in rows:session.append(row);appended+=1
            dataset={'name':item['panel']['name'],'bars':tail['bars'],'metadata':item['panel']['provenance']}
            reason='tail_append' if rows else 'unchanged_closed_prefix'
        else:
            item=None;reused=False;reason='provider_history_revision' if revision else 'tail_no_overlap'
    if not item:
        dataset=data.fetch_daily(code,refresh=True)
        received=dataset['metadata']['received_at'];session=BottomSession(code,benchmark_by_date=benchmark,emotion_by_date=emotion)
        for row in dataset['bars']:session.append(row);appended+=bool(row['is_closed'])
    panel=session.snapshot();forming=[x for x in dataset['bars'] if not x['is_closed']]
    # Intraday bars keep the full-provider normalized OHLC and stay out of confirmed features.
    if forming:
        row=forming[-1];panel['bars'].append({**row,'source_index':len(session.bars),'is_closed':False})
    context=data.probe_context(code)
    money_source=context.get('sources',{}).get('money_flow') or {}
    money_rows=money_source.get('rows') or []
    last_flow=money_rows[-1] if money_rows else None
    latest_date=session.bars[-1].closed_at[:10]
    money_observation=None
    if last_flow:
        lag=(datetime.fromisoformat(latest_date).date()-datetime.fromisoformat(last_flow['date']).date()).days
        money_observation={**last_flow,'state':'future_snapshot' if lag<0 else 'latest_snapshot' if lag<=3 else 'stale_snapshot',
            'known_at':money_source.get('received_at'),'historical_usable':False,
            'collection_time_verified':True,'historical_publication_time_verified':False,
            'lag_calendar_days':lag,'historical_usage':'excluded_until_publication_time_verified',
            'source':money_source.get('source')}
    panel['current']['money_flow_observation']=money_observation
    panel['current']['emotion_archive_snapshot']=emotion.get(latest_date)
    panel['factor_coverage']={**panel['factor_coverage'],
        'money_flow':{'state':money_observation['state'] if money_observation else money_source.get('state','unavailable'),
            'source':money_source.get('source'),'data_date':last_flow.get('date') if last_flow else None,
            'known_at':money_source.get('received_at'),'historical_usable':False,
            'rows':money_source.get('count',0),
            'note':'资金净流是分类订单流并记下本次抓取时间；逐日发布时间未核实，所以不用于过去信号回测'},
        'emotion_archive':{'records':len(emotion),'historical_usable':False,
            'latest_date':max(emotion) if emotion else None,
            'note':'历史情绪快照缺少可核对的逐日原始生成时刻；独立展示，不回填历史决策'}}
    panel.update(name=dataset['name'],period='day',label='日线底部研究',version=BOTTOM_VERSION,app_version=APP_VERSION,
        source_kind='live_bottom_research',fetched_at=received,received_at=now(),
        data_as_of=session.bars[-1].closed_at,provenance=dataset['metadata'],context_observations=context,
        refresh_after_seconds=15 if datetime.now(CN).weekday()<5 and 9<=datetime.now(CN).hour<15 else 300,
        realtime={'session_reused':reused,'appended_closed_bars':appended,'forming_count':len(forming),
            'reason':reason,'closed_prefix_sha256':session._last_revision,'source_received_at':received,
            'tail_receipt':tail_receipt,'initial_source_rows':dataset['metadata'].get('source_rows'),
            'current_closed_rows':len(session.bars),
            'forming_bars_used_for_structure':False,'old_history_replayed':not reused,
            'confirmed_through':session.bars[-1].closed_at},
        validation={'profile':BOTTOM_VERSION,'view':'current prefix; historical run is separate'},
        execution_allowed=False)
    panel['coverage'].update(count=len(panel['bars']),forming_count=len(forming),source=dataset['metadata']['source'])
    with guard:
        sessions[code]={'session':session,'fetched_monotonic':time.monotonic(),'panel':copy.deepcopy(panel)};sessions.move_to_end(code)
        while len(sessions)>2:sessions.popitem(last=False)
    return panel
