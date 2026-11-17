"""Acquire verified workbench data and run the declared V5 recursive profile."""
from collections import Counter
from datetime import datetime
import gzip
import json
import os
from pathlib import Path
import time

from chanmodel.tdx_data import CN, TdxClient, atomic_bytes, cache_history, normalize_daily
from chanmodel.tdx_intraday import fetch_intraday, normalize_intraday, cache_intraday
from chanmodel.v2.io import load_cache_series
from chanmodel.v2.series import validate_multiframe
from chanmodel.release import APP_LABEL
from chanmodel.signal_chart import attach_chart_annotations
from chanmodel.kline_audit import repair_signal_anchors
from .store import ROOT, STATE

NAMES = {'first_buy':'一买候选','second_buy':'二买候选','third_buy':'三买候选',
         'first_sell':'一卖候选','second_sell':'二卖候选','third_sell':'三卖候选'}


def local(value):
    return datetime.fromisoformat(value).astimezone(CN).strftime('%Y-%m-%d %H:%M')


def contract_brief(contract):
    if not contract:
        return None
    return {'state': contract['state'], 'pairs': [
        {**{k:p.get(k) for k in ('parent_period','child_period','state','price_tolerance','volume_tolerance',
            'matched_parent_bars','mismatched_parent_bars','incomplete_parent_bars','matched_start','matched_end')},
         'max_volume_difference': max((abs(c.get('volume_difference') or 0) for c in p['comparisons']), default=0),
         'max_price_difference': max((abs(v) for c in p['comparisons'] for v in c.get('price_differences',{}).values()), default=0)}
        for p in contract['pairs']]}


def make_chart(record, inputs, reports, cutoff, combined=None, default_contract=None, *, include_forming=False):
    panels, period_summary = [], {}
    for period, report in reports.items():
        bars = inputs[period].bars if include_forming else inputs[period].prefix(cutoff).bars
        keep = {'day':180,'30m':280,'5m':420}[period]
        start = 0
        layer = report['hierarchy']['levels'][0]
        center = layer['centers'][-1] if layer['centers'] else None
        tail = report['base']['segments'][-1] if report['base']['segments'] else None
        points = [{'time':int(datetime.fromisoformat(b.closed_at).timestamp())+8*3600,
                   'source_index':b.pos,'closed_at':b.closed_at,'is_closed':b.closed, 'date_cn':local(b.closed_at), 'open':b.open,
                   'high':b.high,'low':b.low,'close':b.close,'volume':b.volume} for b in bars[start:]]
        candidates = []
        for s in sorted(report['signals'], key=lambda x:x['anchor'], reverse=True):
            if s['state'] in {'invalidated','needs_review'}:
                continue
            candidates.append({**{k:s[k] for k in ('id','class','rank','state','price','invalidation','zd','zg')},
                               'label':NAMES.get(s['class'],s['class']), 'anchor_time':local(bars[s['anchor']].closed_at),
                               'available_time':local(bars[s['available_at']].closed_at)})
        note = ('向上' if tail['direction']=='up' else '向下') + ('待确认' if tail['state']=='provisional' else '已确认') + f" · {tail['start_price']:.2f} → {tail['end_price']:.2f}" if tail else '尚未形成线段'
        panels.append({'period':period,'visible_start':start,'visible_bars':len(points),'input_bars':len(bars),'default_visible':keep,'history_complete_in_chart':True,
            'bars':points,'strokes':[s for s in report['base']['strokes'] if s['end']>=start],
            'segments':[s for s in report['base']['segments'] if s['end']>=start],
            'higher_segments':report['base'].get('higher_segments',[]),
            'centers':[c for c in layer['centers'] if c['end']>=start],
            'signals':[{**s,'label':NAMES.get(s['class'],s['class'])} for s in report['signals'] if s['rank']==1 and s['state']!='invalidated' and s['anchor']>=start],
            'note':note,'latest_center':center,
            'merged':report['base']['merged'],'fractals':report['base']['fractals'],
            'structure_layers':report['hierarchy']['levels'],
            'all_signals':report['signals'],'engine':report.get('profile'),
            'engine_provenance':report.get('engine_provenance'),'geometry_review':report.get('geometry_review'),
            'complete_evidence':{k:report.get(k,[]) for k in ['feature_sequences','center_evolution','center_monitors',
                                                          'construction_phases','divergence_comparisons']}})
        period_summary[period] = {'bars':len(bars),'first_close':local(bars[0].closed_at),
            'last_close':local(bars[-1].closed_at),'latest_center':{k:center[k] for k in ('zd','zg','state','rank')} if center else None,
            'last_segment':{k:tail[k] for k in ('direction','state','start_price','end_price')} if tail else None,
            'certificate_audit':report['certificate_audit'], 'active_candidates':candidates}
    daily = inputs['day'].bars if include_forming else inputs['day'].prefix(cutoff).bars
    last = daily[-1]; previous = daily[-2].close if len(daily)>1 else last.close
    states = dict(Counter(s['state'] for s in combined.get('signals',[]))) if combined else {}
    # Keep the per-period native candidates visible even when the strict
    # three-level link has no selected trigger. An empty selected_links list
    # means "no complete chain", not "no lower-level evidence exists".
    period_candidate_counts = {
        period: {
            'total': len(report.get('signals', [])),
            'active': sum(s.get('state') not in {'invalidated', 'withdrawn'} for s in report.get('signals', [])),
            'states': dict(Counter(s.get('state') for s in report.get('signals', []))),
            'classes': dict(Counter(s.get('class') for s in report.get('signals', []))),
        }
        for period, report in reports.items()
    }
    triggered = states.get('structurally_triggered_under_profile',0) if combined and combined['state']=='calculated' else None
    state = combined['state'] if combined else 'day_only'
    if combined is None:
        result = '尚未运行三周期校验'
    elif state == 'blocked_data_contract':
        result = '数据校验未通过，触发不成立'
    elif triggered:
        result = f'{triggered}个模型研究触发'
    else:
        lower = [period for period, value in period_candidate_counts.items() if value['active']]
        result = '暂无完整多周期触发'
        if lower:
            result += '；' + '、'.join(lower) + '存在本级候选，但尚未完成父级→下级→细级链路'
    summary = {**record,'price':last.close,'previous_close':previous,'change_pct':(last.close-previous)/previous*100,
               'last_date':local(last.closed_at)[:10], 'last_close_time':local(last.closed_at), 'as_of':cutoff,
               'mode':'multi' if combined else 'day','algorithm':APP_LABEL,'workbench_profile':reports['day'].get('workbench_profile'),
               'engine_profile':reports['day'].get('profile'),'state':state,'triggered':triggered,
               'active_candidates':len(period_summary['day']['active_candidates']), 'multiframe_states':states,
               'period_candidate_counts':period_candidate_counts,
               'default_contract':contract_brief(default_contract),
               'comparison_contract':contract_brief(combined['data_contract']) if combined else None,
               'periods':period_summary,'result_text':result,'execution_allowed':False,
               'definition_mode':reports['day']['definition_mode'],'strict_original_equivalence_proven':False}
    chart = {**{k:summary[k] for k in ('name','symbol','price','change_pct','last_close_time','result_text','execution_allowed','definition_mode')},
             'code':record['code'],'change':last.close-previous,'source':'TDX','adjustment':'不复权','panels':panels,
             'input_sha256':{p:s.input_sha256 for p,s in inputs.items()},'as_of':cutoff,
             'algorithm':APP_LABEL,'workbench_profile':reports['day'].get('workbench_profile'),
             'engine_profile':reports['day'].get('profile'),
             'display_engine':reports['day'].get('profile'),'engine_commit':reports['day'].get('engine_commit'),
             'approximation_loss':reports['day'].get('approximation_loss',reports['day'].get('remaining_scope',[])),'strict_original_equivalence_proven':False,
             'snapshot_semantics':'final-cutoff structure; anchors may precede availability'}
    if (not reports['day'].get('engine_provenance')
            and not reports['day'].get('workbench_profile')):
        repair_signal_anchors({'chart':chart,'evidence':{'reports':reports}})
    attach_chart_annotations(chart,combined)
    return chart, summary


def process_stock(record, settings, job_id):
    started = time.monotonic()
    code = record['symbol']; mode = settings['mode']; cutoff = settings['cutoff']
    folder = STATE / 'jobs' / job_id
    market_data=Path(os.environ.get('CHANLUN_MARKET_DATA_DIR',ROOT.parent/'data'/'market_data')).resolve()
    cache = folder / 'cache' if settings['refresh'] else market_data
    periods = ('day','30m','5m') if mode=='multi' else ('day',)
    inputs, receipts = {}, {}
    from .progress import reporter
    progress=reporter(job_id,code,record['name'])
    try:
        progress('starting','开始处理该股')
        if mode=='full':
            from .full_compute import process_full
            return process_full(record,settings,job_id)
        for period in periods:
            progress('kline',f'正在{"获取" if settings["refresh"] else "读取"}{period}全部历史')
            if settings['refresh']:
                client = TdxClient(timeout=60)
                raw_period = {'day':'day','30m':'minute30','5m':'minute5'}[period]
                data,receipt,raw=client.request_retry('/api/kline-all/tdx',{'code':code,'type':raw_period},
                    on_retry=lambda info:progress('retry',f'行情请求中断，正在重试{info["next_attempt"]}/{info["max_attempts"]}',**info))
                atomic_bytes(folder/'responses'/f'{code}-{period}.json.gz',gzip.compress(raw,mtime=0))
                bars, rows, quality = normalize_daily(data,datetime.fromisoformat(cutoff)) if period=='day' else normalize_intraday(data,datetime.fromisoformat(cutoff),raw_period)
                quality['cache_run_as_of'] = cutoff
                if not bars:
                    raise ValueError(f'{period}: provider returned no closed bars')
                if period=='day':
                    cache_history(cache,code,'tdx',rows,raw,receipt,quality)
                else:
                    cache_intraday(cache,code,raw_period,rows,raw,receipt,quality)
            inputs[period], receipts[period] = load_cache_series(cache,code,period)
        combined, default = None, None
        progress('analysis','行情读取完成，正在计算走势结构和数据校验')
        from .v5_engine import CONFIG as V5_CONFIG, MAX_RANK as V5_MAX_RANK, analyze_inputs
        replay_summary=None
        roles=('day','30m','5m')
        if mode=='multi':
            if not all(period in inputs for period in roles):
                raise ValueError('V5三周期结构需要完整日线、30分钟、5分钟行情')
            default = validate_multiframe(inputs,roles,cutoff)
            audit=validate_multiframe(inputs,roles,cutoff,volume_tolerance=settings['volume_tolerance'])
            analyzed=analyze_inputs({p:inputs[p] for p in roles},cutoff,roles=roles,
                                    volume_tolerance=settings['volume_tolerance'])
            reports=analyzed['reports']
            links=analyzed['links']
            selected=links.get('selected_signals',[])
            combined={'state':'calculated' if audit['state']=='verified' else 'blocked_data_contract',
                      'data_contract':audit,'levels':reports,
                      'signals':selected if audit['state']=='verified' else [],
                      'complete_links':{**links,'selected_signals':selected if audit['state']=='verified' else []},
                      'workbench_profile':analyzed['workbench_profile'],'execution_allowed':False}
        elif mode=='replay':
            if not settings.get('interactive'):
                raise ValueError('V5因果回放仅支持最多5只股票的选定范围，请缩小范围后重试')
            from chanmodel.unified import CompleteReplay,replay_schedule
            schedule,schedule_audit=replay_schedule(inputs,cutoff,tail_count=32)
            if not schedule:
                raise ValueError('V5因果回放没有可用的闭合K线时点')
            replay=CompleteReplay(inputs,config=V5_CONFIG,max_rank=V5_MAX_RANK,
                                  volume_tolerance=settings['volume_tolerance'])
            for observed_at in schedule:
                analyzed=replay.observe(observed_at)
            analyzed['workbench_profile']='course_feature_sequence_recursive_v2'
            for report in analyzed['reports'].values():
                report['workbench_profile']=analyzed['workbench_profile']
            events=replay.events
            for event in events:
                if event.get('observed_at')==schedule[0]:
                    event['sample_baseline']=True
            event_path=folder/'events'/f'{code}.jsonl.gz'
            atomic_bytes(event_path,gzip.compress(''.join(
                json.dumps(event,ensure_ascii=False,allow_nan=False)+'\n' for event in events
            ).encode(),mtime=0))
            replay_summary={'bars':len(schedule),
                            'context_bars':len(inputs['day'].prefix(cutoff).bars),
                            'observations':len(schedule),'events':len(events),
                            'first_observation':schedule_audit['first'],
                            'last_observation':schedule_audit['last'],
                            'observation_scope':'latest 32 closed daily bars; prior objects at the first observation are sample baselines, not their historical first-appearance times',
                            'future_data_reused':False,'causal':True,
                            'event_artifact':str(event_path.relative_to(STATE))}
            analyzed['config']={k:getattr(V5_CONFIG,k) for k in V5_CONFIG.__dataclass_fields__}
            reports=analyzed['reports']
        else:
            analyzed=analyze_inputs(inputs,cutoff,volume_tolerance=settings['volume_tolerance'])
            reports=analyzed['reports']
        for report in reports.values():
            report['workbench_profile']=analyzed['workbench_profile']
        chart, summary = make_chart(record,inputs,reports,cutoff,combined,default)
        summary.update(mode=mode,elapsed_seconds=round(time.monotonic()-started,3),volume_tolerance=settings['volume_tolerance'],
                       algorithm=APP_LABEL,workbench_profile=analyzed['workbench_profile'],
                       profile=analyzed['workbench_profile'],engine_profile=analyzed['profile'],
                       engine_config=analyzed['config'])
        if replay_summary:
            summary['replay']=replay_summary
        artifact = folder/'results'/f'{code}.json.gz'
        bundle = {'summary':summary,'chart':chart,'evidence':{'reports':reports,'default_contract':default,
                  'multiframe':{k:v for k,v in combined.items() if k!='levels'} if combined else None,
                  'profile':analyzed['workbench_profile'],'source_receipts':receipts}}
        atomic_bytes(artifact,gzip.compress(json.dumps(bundle,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode(),compresslevel=3,mtime=0))
        progress('finished','结果已保存，可以查看图表')
        return {'state':'success','summary':summary,'artifact':str(artifact.relative_to(STATE))}
    except Exception as exc:
        progress('failed',f'{type(exc).__name__}: {exc}')
        return {'state':'failed','error':f'{type(exc).__name__}: {exc}','elapsed_seconds':round(time.monotonic()-started,3)}
