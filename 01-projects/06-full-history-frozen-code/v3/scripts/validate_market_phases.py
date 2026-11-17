"""Offline forward-outcome validation of causal price/volume phase observations.

The phase labels have no verified actor-intent ground truth. This tool measures
subsequent price paths and transitions, never classification accuracy, never
selects rules, and never downloads or modifies source data.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.bottom_research import _bar, split_outcomes
from scripts.validate_bottom_accuracy import choose_run, load_dataset, receipt_records
from chanmodel.local_compute import OrderedLocalMap
from chanmodel.local_gpu import OpenCLBootstrap, GPUUnavailable, probe_gpu, recommend_backend

HORIZON=20
TARGET=.10
COST=.002
SPLITS=('train','validation','test','all')
CN=timezone(timedelta(hours=8))
INVALIDATING_PHASES={'failed_launch','data_discontinuity','distribution_risk'}
PHASE_NAMES={
    'position_building_candidate':'建仓候选','absorption_candidate':'吸筹候选',
    'shakeout_candidate':'洗盘候选','supply_test_candidate':'试盘候选',
    'range_consolidation':'区间震荡','post_shakeout_consolidation':'洗盘后震荡',
    'post_test_consolidation':'试盘后震荡','launch_candidate':'启动候选',
    'launch_confirmed':'突破价格确认','failed_launch':'启动失效',
    'distribution_risk':'派发风险','no_setup':'未形成条件',
    'insufficient_data':'样本不足','data_discontinuity':'数据不连续',
}


def digest(raw):return hashlib.sha256(raw).hexdigest()


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(path)


def source_hashes():
    paths=('chanmodel/market_phase.py','chanmodel/model.py','chanmodel/bottom_research.py',
           'web/bottom_data.py','scripts/validate_bottom_accuracy.py','scripts/validate_market_phases.py',
           'chanmodel/local_compute.py','chanmodel/local_gpu.py')
    missing=[p for p in paths if not (ROOT/p).is_file()]
    if missing:raise ValueError('phase validation dependency missing: '+', '.join(missing))
    return {p:digest((ROOT/p).read_bytes()) for p in paths}


def number(value):
    if isinstance(value,bool):return None
    try:result=float(value)
    except (ValueError,TypeError):return None
    return result if math.isfinite(result) else None


def observation_split(stamp,splits):
    date=str(stamp or '')[:10]
    if not date:return 'censored'
    return 'train' if date<=splits['train_end'] else 'validation' if date<=splits['validation_end'] else 'test'


def validate_event(event,bars):
    if not isinstance(event,dict) or not isinstance(event.get('phase'),str):
        raise ValueError('phase event must declare phase')
    index=event.get('available_at_index')
    if type(index) is not int or not 0<=index<len(bars):
        raise ValueError('phase first-available index outside closed input')
    if event.get('available_time')!=bars[index].closed_at:
        raise ValueError('phase first-available timestamp differs from source candle')
    anchor=event.get('anchor_index',index)
    if type(anchor) is not int or not 0<=anchor<=index:
        raise ValueError('phase anchor outside observed prefix')


def evaluate_events(symbol,bars,events,splits):
    """Preserve every observed phase; outcomes begin only at the next open."""
    ordered=sorted(events,key=lambda e:e.get('available_at_index',-1))
    if events!=ordered:raise ValueError('phase events are not chronological')
    labels=[]
    for position,event in enumerate(events):
        validate_event(event,bars)
        available=event['available_at_index'];phase=event['phase']
        end=min(len(bars)-1,available+HORIZON)
        successors=[e for e in events[position+1:] if available<e['available_at_index']<=end]
        next_event=next((e for e in successors if e['phase']!=phase),None)
        failure=next((e for e in successors if e['phase'] in INVALIDATING_PHASES),None)
        label={'symbol':symbol,'event_id':event.get('id',f'{symbol}:{phase}:{available}:{position}'),
            'phase':phase,'label':event.get('label',PHASE_NAMES.get(phase,phase)),
            'phase_status':event.get('status'),'available_at_index':available,
            'available_time':event['available_time'],'anchor_index':event.get('anchor_index',available),
            'observation_split':observation_split(event['available_time'],splits),
            'invalidation':number(event.get('invalidation')),'support':number(event.get('support')),
            'resistance':number(event.get('resistance')),'basis':event.get('basis',[]),
            'next_phase':next_event['phase'] if next_event else None,
            'next_phase_delay':next_event['available_at_index']-available if next_event else None,
            'failure_phase_within_window':failure['phase'] if failure else None,
            'failure_delay':failure['available_at_index']-available if failure else None,
            'transition_window_complete':available+HORIZON<len(bars),
            'transition_max_observed_index':end,'actor_intent_verified':False,
            'intent_classification_accuracy_available':False,'execution_allowed':False,
            'horizon':HORIZON,'target':TARGET,'state':'pending_next_session',
            'outcome_complete':False,'return':None,'entry_time':None,
            'entry_price':None,'entry_index':None,'max_observed_index':available}
        if available+1>=len(bars):
            label['split']='censored';labels.append(label);continue
        entry_index=available+1;entry=bars[entry_index].open
        end=min(len(bars)-1,entry_index+HORIZON-1)
        stop=label['invalidation'];target=entry*(1+TARGET)
        label.update(entry_index=entry_index,entry_time=bars[entry_index].closed_at,
            entry_price=entry,support_stop=stop,target_price=target,
            horizon_complete=end==entry_index+HORIZON-1,label_end_time=bars[end].closed_at,
            label_end_index=end,max_observed_index=end)
        if stop is None or stop<=0:
            label['state']='invalidation_missing'
        elif entry<=stop:
            label['state']='invalidated_before_entry'
        else:
            exit_index=end;exit_price=bars[end].close
            outcome='horizon_close' if label['horizon_complete'] else 'right_censored'
            for index in range(entry_index+1,end+1):
                bar=bars[index]
                # T+1 forbids entry-session exits; both barriers resolve adversely.
                if bar.low<=stop:
                    outcome='stop';exit_index=index;exit_price=min(bar.open,stop);break
                if bar.high>=target:
                    outcome='target';exit_index=index;exit_price=max(bar.open,target);break
            complete=outcome in {'stop','target','horizon_close'}
            label.update(state=outcome,exit_index=exit_index,exit_time=bars[exit_index].closed_at,
                exit_price=exit_price,gross_return=exit_price/entry-1,
                **{'return':exit_price/entry-1-COST},outcome_complete=complete,
                signal_to_exit_sessions=exit_index-available)
        gaps=[i for i in range(max(1,available-60),end+1) if abs(bars[i].open/bars[i-1].close-1)>.25]
        if gaps:label.update(exclusion='unverified_large_price_discontinuity',excluded_gap_indices=gaps)
        labels.append(label)
    split_outcomes(labels,splits)
    return labels


def metrics(rows,total_symbols):
    eligible=[x for x in rows if not x.get('exclusion')]
    complete=[x for x in eligible if x.get('outcome_complete') and number(x.get('return')) is not None]
    returns=[x['return'] for x in complete]
    mature=[x for x in eligible if x['transition_window_complete']]
    return {'observations':len(rows),'eligible_after_gap_exclusion':len(eligible),
        'gap_exclusions':len(rows)-len(eligible),'evaluated':len(complete),
        'missing_invalidation':sum(x['state']=='invalidation_missing' for x in eligible),
        'invalidated_before_entry':sum(x['state']=='invalidated_before_entry' for x in eligible),
        'right_censored_or_unfilled':len(eligible)-len(complete),
        'symbols_with_observation':len({x['symbol'] for x in rows}),
        'symbol_coverage':len({x['symbol'] for x in rows})/total_symbols if total_symbols else None,
        'target_hits':sum(x['state']=='target' for x in complete),
        'target_touch_rate':sum(x['state']=='target' for x in complete)/len(complete) if complete else None,
        'positive_return_rate':sum(v>0 for v in returns)/len(returns) if returns else None,
        'mean_return':statistics.fmean(returns) if returns else None,
        'median_return':statistics.median(returns) if returns else None,
        'stops':sum(x['state']=='stop' for x in complete),
        'median_signal_to_target_sessions':statistics.median([x['signal_to_exit_sessions'] for x in complete if x['state']=='target']) if any(x['state']=='target' for x in complete) else None,
        'next_phase_counts':dict(Counter(x['next_phase'] or 'none_within_window' for x in eligible)),
        'transition_mature':len(mature),'transition_right_censored':len(eligible)-len(mature),
        'failure_phase_counts_mature':dict(Counter(x['failure_phase_within_window'] for x in mature if x['failure_phase_within_window'])),
        'failure_transition_rate_mature':sum(bool(x['failure_phase_within_window']) for x in mature)/len(mature) if mature else None,
        'outcomes':dict(Counter(x['state'] for x in eligible)),
        'classification_accuracy':None,'actor_intent_ground_truth_available':False}


def cluster_intervals(rows,symbols,draws=2000,seed=20261117):
    counts={symbol:[0,0,0] for symbol in symbols}
    for row in rows:
        if row.get('exclusion') or not row.get('outcome_complete') or number(row.get('return')) is None:continue
        c=counts[row['symbol']];c[0]+=1;c[1]+=row['state']=='target';c[2]+=row['return']>0
    rng=random.Random(seed);targets=[];positive=[]
    for _ in range(draws):
        chosen=[counts[rng.choice(symbols)] for _ in symbols]
        count=sum(x[0] for x in chosen)
        if count:
            targets.append(sum(x[1] for x in chosen)/count);positive.append(sum(x[2] for x in chosen)/count)
    def interval(values):
        values.sort()
        return [values[int(.025*len(values))],values[min(len(values)-1,int(.975*len(values)))]] if values else None
    return {'method':'symbol-cluster bootstrap; price outcomes only, not intent-label accuracy',
        'draws':draws,'seed':seed,'target_touch_rate_95pct_ci':interval(targets),
        'positive_return_rate_95pct_ci':interval(positive)}


def bootstrap_totals_cpu(counts,selections):
    """Exact integer reference for all phase/split/count columns in one batch."""
    if not counts or not selections:return []
    metrics=len(counts[0]);totals=[[0]*metrics for _ in selections]
    for rep,selected in enumerate(selections):
        result=totals[rep]
        for symbol in selected:
            source=counts[symbol]
            for metric,value in enumerate(source):result[metric]+=value
    return totals


def prepare_bootstrap_columns(labels,symbols,phases,splits,draws=2000,seed=20261117,*,gpu_mode='auto',profile_path=None):
    """Pack 14 phases x 4 splits x (n,target,positive) into one deterministic table."""
    columns=[];counts=[[0]*(len(phases)*len(splits)*3) for _ in symbols]
    symbol_index={symbol:index for index,symbol in enumerate(symbols)}
    for split in splits:
        for phase in phases:
            col=len(columns);columns.append((split,phase))
            subset=[row for row in labels if row['phase']==phase and (split=='all' or row.get('split')==split)
                    and not row.get('exclusion') and row.get('outcome_complete')
                    and number(row.get('return')) is not None]
            for row in subset:
                values=counts[symbol_index[row['symbol']]];base=col*3
                values[base]+=1;values[base+1]+=row['state']=='target';values[base+2]+=row['return']>0
    rng=random.Random(seed);selections=[[rng.randrange(len(symbols)) for _ in symbols] for _ in range(draws)]
    if gpu_mode not in ('auto','off','on'):raise ValueError('gpu must be auto, off or on')
    gpu_info=probe_gpu() if gpu_mode!='off' else {'supported':False,'reason':'explicit_cpu_reference'}
    profile=None;profile_key=digest(json.dumps({k:gpu_info.get(k) for k in ('name','vendor','driver_version')},sort_keys=True).encode()+
        (ROOT/'chanmodel/local_gpu.py').read_bytes())
    if profile_path and gpu_mode=='auto':
        try:
            prior=json.loads(Path(profile_path).read_text(encoding='utf-8'))
            if (isinstance(prior,dict) and prior.get('full_integer_equality_verified') is True
                and prior.get('key')==profile_key and prior.get('recommended_backend')=='opencl'
                and len(counts[0])>=prior.get('minimum_columns',168)
                and len(symbols)>=prior.get('calibration_symbols',80) and draws>=2000):profile=prior
        except (OSError,ValueError,TypeError):pass
    cpu=None;cpu_ms=None;gpu_ms=None;gpu=None;backend='cpu';gpu_reason=gpu_info.get('reason');equal=False
    if not profile:
        cpu_start=time.perf_counter();cpu=bootstrap_totals_cpu(counts,selections)
        cpu_ms=(time.perf_counter()-cpu_start)*1000
    if gpu_mode=='on' and not gpu_info.get('supported'):
        raise GPUUnavailable(gpu_info.get('reason','no supported GPU'))
    if gpu_info.get('supported'):
        try:
            gpu_start=time.perf_counter()
            with OpenCLBootstrap() as accelerator:gpu=accelerator.totals(counts,selections)
            gpu_ms=(time.perf_counter()-gpu_start)*1000
            if profile:
                sample_indices=sorted({0,len(selections)//2,len(selections)-1})
                reference=bootstrap_totals_cpu(counts,[selections[i] for i in sample_indices])
                equal=reference==[gpu[i] for i in sample_indices]
                backend='opencl';gpu_reason='previous_full_equality_calibration_and_current_sample_verification'
            else:
                equal=gpu==cpu;choice=recommend_backend(cpu_ms,gpu_ms,minimum_speedup=1.10)
                backend='opencl' if gpu_mode=='on' else choice['backend']
                gpu_reason='measured_end_to_end_benchmark_and_exact_integer_match'
            if not equal:raise ValueError('GPU integer totals differ from CPU reference')
            if profile_path and not profile:
                write_json(profile_path,{'key':profile_key,'recommended_backend':backend,
                    'minimum_columns':len(counts[0]),'calibration_symbols':len(symbols),
                    'cpu_wall_ms':cpu_ms,'gpu_wall_ms':gpu_ms,'full_integer_equality_verified':True})
        except Exception as error:
            if gpu_mode=='on':raise
            backend='cpu';equal=False
            gpu_reason='gpu_attempt_failed:'+type(error).__name__+': '+str(error)[:200]
    if backend=='cpu' and cpu is None:
        cpu_start=time.perf_counter();cpu=bootstrap_totals_cpu(counts,selections);cpu_ms=(time.perf_counter()-cpu_start)*1000
    totals_used=gpu if backend=='opencl' else cpu
    intervals={}
    for col,(split,phase) in enumerate(columns):
        estimates=[[],[]]
        for totals in totals_used:
            n,targets,positive=totals[col*3:col*3+3]
            if n:
                estimates[0].append(targets/n);estimates[1].append(positive/n)
        def ci(values):
            values.sort()
            return [values[int(.025*len(values))],values[min(len(values)-1,int(.975*len(values)))]] if values else None
        intervals[(split,phase)]={'target_touch_rate_95pct_ci':ci(estimates[0]),
            'positive_return_rate_95pct_ci':ci(estimates[1]),'resamples':draws,'seed':seed,
            'method':'paired symbol-cluster bootstrap; exact integer aggregate totals'}
    execution={'cpu_reference_wall_ms':round(cpu_ms,3) if cpu_ms is not None else None,'gpu_end_to_end_wall_ms':round(gpu_ms,3) if gpu_ms is not None else None,
        'recommended_backend':backend,'gpu_probe':gpu_info,'gpu_decision_reason':gpu_reason,
        'metrics_columns':len(columns)*3,'phase_split_columns':len(columns),'bootstrap_draws':draws,
        'combined_gpu_input_output_bytes':4*(len(symbols)*len(counts[0])+len(selections)*len(symbols)+len(selections)*len(counts[0])),
        'cpu_gpu_integer_totals_equal':equal,'current_equality_scope':'three_replicates' if profile else 'all_replicates',
        'calibration_reused':profile is not None,
        'bootstrap_result_source':backend,
        'classification_and_structure_compute_backend':'CPU only'}
    return intervals,execution


def markdown(report):
    pct=lambda x:'—' if x is None else f'{x:.2%}'
    lines=['# 量价阶段候选的历史后续走势复测','',
        '**建仓、吸筹、洗盘、试盘没有已验证的真实主力意图标签，本报告不提供阶段分类准确率。**',
        '只评价算法在首次可知时点给出的阶段候选后，真实价格路径如何变化；不调参、不选择最优阶段、不自动晋级。','',
        f'- 版本：`{report["version"]}`；范围：`{report["dataset_scope"]}`。',
        f'- 成功 {report["successful_symbols"]}/{report["requested_symbols"]} 支，{report["closed_bars"]:,} 根闭合日线；失败 {len(report["failures"])}。',
        '- 下一交易日开盘；T+1退出；20交易日内+10%目标/事件失效价，碰双边先按止损；估计往返成本0.2%。','',
        '|时段|阶段|观察|有效结果|目标先触达|正收益|缺失失效价|',
        '|---|---|---:|---:|---:|---:|---:|']
    for split in SPLITS:
        for phase,m in report['metrics'][split].items():
            lines.append(f'|{split}|{PHASE_NAMES.get(phase,phase)}|{m["observed_phase_transitions"]}|{m["evaluated"]}|{pct(m["target_touch_rate"])}|{pct(m["positive_return_rate"])}|{m["missing_invalidation"]}|')
    lines+=['','## 口径与边界','']+['- '+x for x in report['limitations']]
    lines+=['','输入原始/标准化SHA256见 input-manifest.json；逐次阶段和后续标签见 observations.json.gz。']
    return '\n'.join(lines)+'\n'


def analyze_symbol(task):
    """One immutable symbol per process; write large labels instead of pickling them."""
    record,splits,output=task;code=record['symbol']
    try:
        from chanmodel.market_phase import MarketPhaseSession
        rows,metadata=load_dataset(record);bars=[_bar(row,index) for index,row in enumerate(rows)]
        session=MarketPhaseSession(code);events=[]
        for bar in bars:
            changes=session.append(bar)
            if not isinstance(changes,list):raise ValueError('append must return a list of new events')
            events.extend(changes)
        checked=evaluate_events(code,bars,events,splits)
        packed=gzip.compress(json.dumps({'symbol':code,'events':events,'outcomes':checked},
            ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),mtime=0)
        path=Path(output)/'symbols'/(code+'.json.gz');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(packed)
        return {'receipt':{'symbol':code,'name':record.get('name',code),'bars':len(bars),
            'metadata':metadata,'events':len(events),'phase_counts':dict(Counter(x['phase'] for x in events))},
            'path':str(path),'payload_sha256':digest(packed)}
    except Exception as error:
        return {'failure':{'symbol':code,'error':type(error).__name__+': '+str(error)[:350]}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-run',default='20261114-051529-64851a')
    parser.add_argument('--symbols-manifest',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',default='auto',help='auto or process cap 1..32; limited by available RAM')
    parser.add_argument('--reserve-mib',type=int,default=1024,help='free RAM reserved for the desktop')
    parser.add_argument('--worker-mib',type=int,default=256,help='estimated peak RAM per spawned worker')
    parser.add_argument('--gpu',choices=('auto','off','on'),default='auto',help='exact bootstrap sums only; all structures stay on CPU')
    args=parser.parse_args(argv);output=args.output
    if (output/'report.json').exists():raise ValueError('choose a fresh output directory')
    module=importlib.import_module('chanmodel.market_phase')
    run,_=choose_run(args.baseline_run);records=receipt_records(args.symbols_manifest,run)
    splits=run.get('split_dates') or run['validation_protocol']['split']
    hashes=source_hashes();labels=[];receipts=[];failures=[];event_counts=Counter();started=time.perf_counter()
    tasks=OrderedLocalMap(analyze_symbol,[(record,splits,str(output)) for record in records],
        workers=args.workers,worker_mib=args.worker_mib,reserve_mib=args.reserve_mib)
    write_json(output/'compute-plan.json',tasks.plan)
    print(json.dumps({'compute_plan':tasks.plan}),flush=True)
    for number_,result in enumerate(tasks,1):
        code=records[number_-1]['symbol']
        if result.get('failure'):failures.append(result['failure'])
        else:
            packed=Path(result['path']).read_bytes()
            if digest(packed)!=result['payload_sha256']:raise ValueError('worker output hash changed')
            checked=json.loads(gzip.decompress(packed))['outcomes'];receipt=result['receipt']
            event_counts.update(receipt['phase_counts']);labels.extend(checked);receipts.append(receipt)
        progress={'completed':number_,'total':len(records),'successful':len(receipts),'failed':len(failures),
            'last_symbol':code,'seconds':round(time.perf_counter()-started,3)}
        write_json(output/'progress.json',progress);print(json.dumps(progress,ensure_ascii=False),flush=True)
    if source_hashes()!=hashes:raise ValueError('source changed during replay; report rejected')
    if not receipts:raise ValueError('no usable phase samples')
    symbols=[x['symbol'] for x in receipts];phases=sorted(set(event_counts)|set(PHASE_NAMES));summary={}
    for split in SPLITS:
        summary[split]={}
        for phase in phases:
            # Observation counts and path metrics retain separate split policies.
            observed=[x for x in labels if x['phase']==phase and (split=='all' or x['observation_split']==split)]
            evaluated=[x for x in labels if x['phase']==phase and (split=='all' or x.get('split')==split)]
            metric=metrics(evaluated,len(symbols));metric['observed_phase_transitions']=len(observed)
            metric['missing_invalidation']=sum(x['state']=='invalidation_missing' for x in observed if not x.get('exclusion'))
            metric['observations_invalidated_before_entry']=sum(x['state']=='invalidated_before_entry' for x in observed if not x.get('exclusion'))
            metric['transition_by_observation_split']=dict(Counter(x['next_phase'] or 'none_within_window' for x in observed))
            summary[split][phase]=metric
    phases_for_bootstrap=sorted(set(event_counts)|set(PHASE_NAMES))
    bootstrap_ci,gpu_execution=prepare_bootstrap_columns(labels,symbols,phases_for_bootstrap,SPLITS,
        gpu_mode=args.gpu,profile_path=ROOT/'.runtime/local-acceleration/bootstrap-profile.json')
    for split in SPLITS:
        for phase in phases_for_bootstrap:
            summary[split][phase]['cluster_bootstrap']=bootstrap_ci[(split,phase)]
    prior_symbols={x['symbol'] for x in run['data_receipts']};overlap=sorted(prior_symbols&set(symbols))
    scope='disjoint_symbol_forward_outcome_validation' if args.symbols_manifest and not overlap else 'retrospective_current_dictionary_sample'
    version=getattr(module,'PHASE_VERSION',getattr(module,'VERSION','module_hash_'+hashes['chanmodel/market_phase.py'][:12]))
    report={'report_version':'price_volume_phase_outcomes_v1','created_at':datetime.now(CN).isoformat(timespec='seconds'),
        'version':version,'state':'completed' if not failures else 'partial','dataset_scope':scope,
        'baseline_run':run['id'],'symbols_manifest':str(args.symbols_manifest) if args.symbols_manifest else None,
        'baseline_symbol_overlap':overlap,'requested_symbols':len(records),'successful_symbols':len(receipts),
        'closed_bars':sum(x['bars'] for x in receipts),'phase_counts':dict(event_counts),
        'compute':{'plan':tasks.plan,'execution':tasks.stats},
        'source_hashes':hashes,'source_unchanged_through_replay':True,
        'accelerator':gpu_execution,
        'evaluation':{'horizon':HORIZON,'target':TARGET,'round_trip_cost':COST,'entry':'next_session_open',
            'earliest_exit':'session_after_entry_T_plus_1','same_bar_order':'stop_first',
            'stop':'event_invalidation; missing/invalidated-before-entry excluded from result denominator',
            'classification_accuracy':None,'actor_intent_ground_truth_available':False,
            'test_period_previously_examined':True,'parameters_selected_from_results':False},
        'split_dates':{k:v for k,v in splits.items() if k!='trading_dates'},'metrics':summary,'failures':failures,
        'limitations':['阶段标签是因果量价代理，缺少真实主力建仓/吸筹/洗盘/试盘意图真值，不能声称识别准确率。',
            '价格突破确认只确认当时价格条件，不证明后续上涨或主力身份。',
            '历史test时段已被查看；新股票仅是符号不重叠，不是从未见过的市场时段。',
            '当前上市股票池有生存者偏差；未调价数据公司行动完整性未普遍认证。',
            '大跳空窗口按固定规则排除；缺失失效价不编造成交。',
            'all为全期描述统计，包括分割边界附近事件；严格分期结果按20期边界净化。',
            '观察阶段转移按首次观察日期分期；后续价格结果按净化后的交易结果分期，两者分母不同。',
            '事件可同股重叠；报告不是共享本金账户收益。'],'execution_allowed':False}
    write_json(output/'input-manifest.json',{'symbols':receipts,'source_hashes':hashes})
    compressed=gzip.compress(json.dumps(labels,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),mtime=0)
    (output/'observations.json.gz').write_bytes(compressed);report['observations_sha256']=digest(compressed)
    write_json(output/'report.json',report);(output/'report.md').write_text(markdown(report),encoding='utf-8')
    print(json.dumps({'state':report['state'],'report':str((output/'report.json').resolve()),'failed':len(failures)},ensure_ascii=False),flush=True)
    return 0 if not failures else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,TypeError,KeyError,OSError) as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr);raise SystemExit(1)
