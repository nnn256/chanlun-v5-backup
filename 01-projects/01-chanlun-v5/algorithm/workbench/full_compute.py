"""All-provider-timeframe jobs and migration of prior clipped chart bundles."""
import gzip
import json
from pathlib import Path
import time

from chanmodel.tdx_data import atomic_bytes,atomic_json,now_iso
from chanmodel.release import APP_LABEL
from chanmodel.signal_chart import attach_chart_annotations
from chanmodel.v2.io import load_series
from .history import load_capture,build_panel,LABELS,NATIVE,timeshare_panel
from .store import ROOT,STATE,connect,publish_result


def capture_reference(folder):
    folder=Path(folder).resolve()
    for label,base in (('state',STATE),('project',ROOT)):
        base=base.resolve()
        if folder.is_relative_to(base):
            return {'history_root':folder.relative_to(base).as_posix(),'history_root_base':label}
    raise ValueError('capture history must be inside workbench state or project')


def resolve_history_root(bundle):
    name=bundle.get('history_root')
    if not isinstance(name,str) or not name:
        raise ValueError('invalid history root')
    location=bundle.get('history_root_base','project')
    if location not in {'state','project'}:
        raise ValueError('invalid history root base')
    base=(STATE if location=='state' else ROOT).resolve()
    root=(base/name).resolve()
    if not root.is_relative_to(base):
        raise ValueError('invalid history root')
    return root


def bundle_capture(record,folder,cutoff,tolerance=100,progress=None):
    from .compute import make_chart
    panels,reports,inputs,bars=load_capture(folder,record['symbol'],cutoff,progress=progress)
    roles={p:inputs[p] for p in ('day','30m','5m') if p in inputs}
    default=audit=None
    combined=None
    if 'day' not in inputs:
        raise ValueError('全周期行情缺少日线，无法生成工作台结果')
    if all(p in roles for p in ('day','30m','5m')):
        from chanmodel.v2.series import validate_multiframe
        from .v5_engine import analyze_inputs
        default=validate_multiframe(roles,('day','30m','5m'),cutoff)
        audit=validate_multiframe(roles,('day','30m','5m'),cutoff,volume_tolerance=tolerance)
        recursive=analyze_inputs(roles,cutoff,roles=('day','30m','5m'),volume_tolerance=tolerance)
        reports.update(recursive['reports'])
        selected=recursive['links'].get('selected_signals',[])
        combined={'state':'calculated' if audit['state']=='verified' else 'blocked_data_contract',
                  'data_contract':audit,'levels':reports,
                  'signals':selected if audit['state']=='verified' else [],
                  'complete_links':{**recursive['links'],
                                    'selected_signals':selected if audit['state']=='verified' else []},
                  'workbench_profile':recursive['workbench_profile'],'execution_allowed':False}
    chart,summary=make_chart(record,roles,{p:reports[p] for p in roles},cutoff,combined,default)
    summary.update(algorithm=APP_LABEL,workbench_profile='course_feature_sequence_recursive_v2',
                   profile='course_feature_sequence_recursive_v2',engine_profile=reports['day'].get('profile'))
    chart.update(algorithm=APP_LABEL,workbench_profile='course_feature_sequence_recursive_v2',
                 profile='course_feature_sequence_recursive_v2',engine_profile=reports['day'].get('profile'))
    chart['panels']=panels;chart['input_sha256']={p['period']:p['coverage']['input_sha256'] for p in panels}
    for p in panels:
        c=p['coverage'];report=reports[p['period']]
        if p['period'] not in summary['periods']:
            summary['periods'][p['period']]={'bars':c['count'],'first_close':c['first'],'last_close':c['last'],'forming_count':c['forming_count'],
                'certificate_audit':report['certificate_audit'] if report else None,'active_candidates':[],
                'latest_center':p['latest_center'],'last_segment':p['last_segment']}
    acquisition=json.loads((folder/'acquisition.json').read_text(encoding='utf-8'))
    coverage=[p['coverage'] for p in panels]
    history=acquisition.get('time_share_history',{})
    dates=[x['date'] for x in history.get('dates',[]) if x['status']=='received']
    for key in ('timeshare','five_days'):
        coverage.append({'period':key,'label':LABELS[key],'status':'available' if dates else 'unavailable','count':len(dates)*240 if key=='timeshare' else min(len(dates),5)*240,
                         'first':dates[0 if key=='timeshare' else max(0,len(dates)-5)] if dates else None,'last':dates[-1] if dates else None,'days':len(dates),'source':'TDX按交易日取历史分时；价格快照不是分钟OHLC',
                         'failed_dates':history.get('failed_dates',0),'empty_dates':history.get('empty_dates',0)})
    coverage.append({'period':'auction','label':'竞价历史','status':'unsupported','count':0,'reason':'TDX接口未提供历史竞价快照，未用开盘后分钟K线替代'})
    summary.update(mode='full',volume_tolerance=tolerance,data_received_at=acquisition.get('finished_at',acquisition['requested_at']),history_coverage=coverage)
    chart.update(history_coverage=coverage,history_complete_in_chart=True)
    attach_chart_annotations(chart,combined)
    return {'summary':summary,'chart':chart,**capture_reference(folder),
            'evidence':{'reports':reports,'default_contract':default,
                        'multiframe':{k:v for k,v in combined.items() if k!='levels'} if combined else None,
                        'profile':'course_feature_sequence_recursive_v2',
                        'source_receipts':acquisition['periods']}}


def process_full(record,settings,job_id):
    from tools.capture_full_stock import capture
    start=time.monotonic();folder=STATE/'jobs'/job_id/'history'/record['symbol']
    from .progress import reporter
    progress=reporter(job_id,record['symbol'],record['name'])
    capture(record['symbol'],folder,progress=progress)
    bundle=bundle_capture(record,folder,settings['cutoff'],settings['volume_tolerance'],progress=progress)
    bundle['summary']['elapsed_seconds']=round(time.monotonic()-start,3)
    artifact=STATE/'jobs'/job_id/'results'/f"{record['symbol']}.json.gz"
    atomic_bytes(artifact,gzip.compress(json.dumps(bundle,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode(),compresslevel=3,mtime=0))
    progress('finished','完整历史结果已保存，正在打开图表')
    return {'state':'success','summary':bundle['summary'],'artifact':str(artifact.relative_to(STATE))}


def expand_legacy(bundle):
    """Reconstruct the untruncated charts from hash-verified source receipts."""
    if all(len(p['bars'])==p['input_bars'] for p in bundle['chart']['panels']):return bundle
    from .server import load_import_evidence
    load_import_evidence(bundle)
    evidence=bundle.get('evidence',{});receipts=evidence.get('source_receipts',{});code=bundle['summary']['symbol']
    expanded=[]
    for old in bundle['chart']['panels']:
        period=old['period'];report=evidence.get('reports',{}).get(period);receipt=receipts.get(period,{})
        csv=receipt.get('file') or receipt.get('csv_path');meta=receipt.get('metadata_file')
        if csv and report:
            path=Path(csv).resolve()
            if not path.is_relative_to(ROOT.resolve()):raise ValueError('source receipt path outside workspace')
            series,checked=load_series(path,code,period,'unadjusted','tdx',meta)
            expected=receipt.get('csv_sha256')
            if expected and series.input_sha256!=expected:raise ValueError('source hash changed; rerun stock')
            cutoff=report['as_of'];bars=series.prefix(cutoff).bars
            panel=build_panel(period,bars,report,series.input_sha256);expanded.append(panel)
        else:
            old['history_warning']='旧结果缺少可核验原始回执，请重新计算；当前不是完整图表历史';expanded.append(old)
    bundle['chart']['panels']=expanded
    return bundle


def history_view(bundle,period,date=None):
    if period=='auction':return {'available':False,'reason':'当前TDX接口没有历史竞价快照，无法展示或回填。'}
    if period in ('timeshare','five_days'):
        if not bundle.get('history_root'):return {'available':False,'reason':'本任务未采集历史分时，请运行“全周期历史”任务。'}
        root=resolve_history_root(bundle)
        manifest=json.loads((root/'acquisition.json').read_text(encoding='utf-8'))
        dates=[x['date'] for x in manifest.get('time_share_history',{}).get('dates',[]) if x['status']=='received']
        cutoff=bundle['summary']['as_of'][:10].replace('-','')
        dates=[d for d in dates if d<=cutoff]
        chosen=date.replace('-','') if date else (dates[-1] if dates else None)
        if not chosen or chosen not in dates:return {'available':False,'reason':'所选日期没有已采集的分时数据。','dates':dates}
        chosen_dates=dates[max(0,dates.index(chosen)-4):dates.index(chosen)+1] if period=='five_days' else [chosen]
        points=[]
        for d in chosen_dates:
            payload=json.loads(gzip.decompress((root/'timeshare'/f'{d}.json.gz').read_bytes()))['data']
            points+=timeshare_panel(payload,d)['points']
        return {'available':True,'panel':{'kind':'line','period':period,'label':LABELS[period],'points':points,'dates':chosen_dates,
                'note':'连续竞价时段每分钟价格快照；不含分钟内OHLC；未伪造竞价记录'},'dates':dates}
    panel=next((p for p in bundle['chart']['panels'] if p['period']==period),None)
    if not panel:return {'available':False,'reason':'本任务未采集该周期，请运行“全周期历史”任务。'}
    return {'available':True,'panel':panel}
