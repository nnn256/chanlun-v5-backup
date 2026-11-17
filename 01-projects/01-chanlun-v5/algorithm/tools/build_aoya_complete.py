"""Aoya: independent full study layers and observed multi-timeframe evidence."""
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from chanmodel.model import Candle
from chanmodel.tdx_data import atomic_json,atomic_bytes,now_iso,CN
from chanmodel.complete_study import analyze_complete,trace_segment_revisions,PROFILE
from chanmodel.complete_multilevel import analyze_links
from chanmodel.v2.series import Series
from workbench.history import NATIVE,normalize,five_day,build_panel,LABELS

SOURCE=ROOT/'runs/aoya-full-history-20261108'
PREVIOUS=ROOT/'runs/aoya-independent-20261108'
OUT=ROOT/'runs/aoya-complete-layers-20261108'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def save_gzip(path,payload):
    atomic_bytes(path,gzip.compress(json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),compresslevel=3,mtime=0))


def save_panel(panel):
    atomic_json(OUT/'panels'/f'{panel["period"]}.json',panel)
    (OUT/'panels'/f'{panel["period"]}.js').write_text('window.PANEL='+json.dumps(panel,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')


def main():
    sys.stdout.reconfigure(encoding='utf-8');cutoff=now_iso()
    for sub in ['panels','analysis','png','assets','events']:(OUT/sub).mkdir(parents=True,exist_ok=True)
    source_files=sorted((ROOT/'chanmodel').rglob('*.py'))
    engine_hash=sha(b''.join(p.relative_to(ROOT).as_posix().encode()+p.read_bytes() for p in source_files))
    inputs={};bars_by_period={};reports={};panels={};summary=[];catalog=[]
    for period,raw_period in NATIVE.items():
        raw=gzip.decompress((SOURCE/'raw'/f'{raw_period}.json.gz').read_bytes())
        receipt=json.loads((SOURCE/'receipts'/f'{raw_period}.json').read_text(encoding='utf-8'))
        if sha(raw)!=receipt['response_sha256']:raise ValueError('Source hash mismatch')
        bars_by_period[period]=(normalize(json.loads(raw)['data'],period,cutoff),sha(raw),'TDX原生周期')
    bars=five_day(bars_by_period['day'][0]);bars_by_period['5d']=(bars,sha(json.dumps([[b.closed_at,b.open,b.high,b.low,b.close,b.volume] for b in bars]).encode()),'每5个交易日聚合，锚定2021-02-26')
    raw=(PREVIOUS/'auction-bars.json').read_bytes();auction=json.loads(raw)
    bars=tuple(Candle(i,b['open'],b['high'],b['low'],b['close'],b['closed_at'],b['volume']) for i,b in enumerate(auction))
    bars_by_period['auction']=(bars,sha(raw),'09:25实际撮合结果，65请求日缺记录；非竞价内虚拟撮合过程')
    order=['auction','day','5d','1m','5m','15m','30m','60m','week','month','quarter','year']
    for period in order:
        start=time.monotonic();bars,digest,origin=bars_by_period[period]
        report_path=OUT/'analysis'/f'{period}.json.gz'
        if report_path.exists():
            report=json.loads(gzip.decompress(report_path.read_bytes()))
            if report['input_sha256']!=digest:raise ValueError('New input requires a fresh run directory')
            if report.get('engine_sha256')!=engine_hash:
                report=analyze_complete('sz300949',period,bars,cutoff,digest);report['engine_sha256']=engine_hash;save_gzip(report_path,report)
        else:
            report=analyze_complete('sz300949',period,bars,cutoff,digest);report['engine_sha256']=engine_hash;save_gzip(report_path,report)
        reports[period]=report
        if period in {'day','1m','5m','15m','30m','60m'}:inputs[period]=Series('sz300949',period,'unadjusted',bars,'tdx',digest)
        panel=build_panel(period,bars,report,digest,origin)
        allcenters=[dict(c,view='operating') for layer in report['hierarchy']['levels'] for c in layer['centers']]
        partitioncenters=[dict(c,view='partition') for layer in report['hierarchy']['levels'] for c in layer['partition_centers']]
        panel.update(kind='candles',profile=PROFILE,label='历史竞价成交K线' if period=='auction' else LABELS[period],
                     all_centers=allcenters,partition_centers=partitioncenters,
                     merged=report['base']['merged'],fractals=report['base']['fractals'],
                     loose_strokes=report['loose_stroke_comparison'],features=report['feature_sequences'],
                     decompositions=report['decompositions'],center_evolution=report['center_evolution'],
                     monitors=report['center_monitors'],constructions=report['construction_phases'],
                     divergences=report['divergence_comparisons'],signals=report['signals'],
                     hierarchy_edges=report['hierarchy']['edges'],hierarchy=report['hierarchy'],
                     layer_catalog=report['layer_catalog'],definition_mode=report['definition_mode'],
                     as_of=cutoff,approximation_loss=report['approximation_loss'],
                     macd=[dict(time=int(datetime.fromisoformat(b.closed_at).timestamp())+8*3600,**h) for b,h in zip([b for b in bars if b.closed],report['macd'])],
                     default_visible=min(len(bars),520),execution_allowed=False,
                     no_new_event_is_a_valid_result=True)
        counts=dict(Counter(p['class'] for p in report['signals']))
        panel['signal_counts']={name:counts.get(name,0) for name in ['first_buy','second_buy','third_buy','first_sell','second_sell','third_sell']}
        panels[period]=panel
        summary.append({'period':period,'label':panel['label'],'kind':'candles','count':len(bars),
                        'first':bars[0].closed_at,'last':bars[-1].closed_at,'forming_excluded':sum(not b.closed for b in bars),
                        'ranks':len(report['hierarchy']['levels']),'layers':report['layer_catalog'],
                        'six_classes':panel['signal_counts'],'certificates':report['certificate_audit']})
        catalog.append({'period':period,'label':panel['label'],'kind':'candles'})
        print(json.dumps({'analyzed':period,'bars':len(bars),'ranks':len(report['hierarchy']['levels']),
                          'centers':len(allcenters),'divergence_comparisons':len(panel['divergences']),
                          'six_class_counts':panel['signal_counts'],'seconds':round(time.monotonic()-start,2)},ensure_ascii=False),flush=True)
    links=analyze_links(reports,inputs,cutoff,volume_tolerance=100)
    save_gzip(OUT/'multilevel-evidence.json.gz',links)
    compact={'pairs':[{k:v for k,v in p.items() if k not in {'comparisons','gaps','mismatches','default_one_share'}} for p in links['pairs'].values()],
             'signals':links['signals'],'interval_nesting':links['interval_nesting'],'small_to_large':links['small_to_large'],
             'small_to_large_audit':links['small_to_large_audit']}
    atomic_json(OUT/'multilevel-summary.json',compact)
    print(json.dumps({'multi_links':len(links['signals']),'nesting_attempts':len(links['interval_nesting']),
                      'nested_depth_gt1':sum(x['matched_depth']>1 for x in links['interval_nesting']),
                      'small_to_large':len(links['small_to_large'])}),flush=True)
    for period in order:
        bars=bars_by_period[period][0];closed=sum(b.closed for b in bars)
        # Daily/calendar captures all its closed bars; minute charts publish an
        # explicit recent window. Each evaluation sees the full preceding input.
        replay_start=0 if period in {'day','5d','week','month','quarter','year'} else max(0,closed-96)
        replay_path=OUT/'events'/f'{period}.json.gz'
        if replay_path.exists():replay=json.loads(gzip.decompress(replay_path.read_bytes()))
        else:
            replay=trace_segment_revisions(bars,replay_start);save_gzip(replay_path,replay)
        p=panels[period];p.update(revision_ledger=replay,
            multi_links=[x for x in links['signals'] if x['trade_period']==period],
            nesting=[x for x in links['interval_nesting'] if x['root_period']==period],
            small_to_large=[x for x in links['small_to_large'] if x['upper_period']==period],
            small_to_large_audit=[x for x in links['small_to_large_audit'] if x['upper_period']==period],
            pair_contracts=[x for x in compact['pairs'] if x['parent_period']==period])
        save_panel(p)
        print(json.dumps({'replayed':period,'prefixes':replay['prefixes_evaluated'],'events':len(replay['events']),
                          'cancel_recover':sum(x['event']=='candidate_cancelled_and_recovered' for x in replay['events'])}),flush=True)
    for period in ['timeshare','five_days','timeshare_first']:
        p=json.loads((PREVIOUS/'panels'/f'{period}.json').read_text(encoding='utf-8'));p['layer_catalog']=[]
        save_panel(p);catalog.append({'period':period,'label':p['label'],'kind':'line'})
    for name in ['lightweight-charts.standalone.production.js','LICENSE','NOTICE','library-source.json']:
        shutil.copy2(PREVIOUS/'assets'/name,OUT/'assets'/name)
    last=bars_by_period['day'][0][-1]
    result={'name':'奥雅股份','symbol':'sz300949','profile':PROFILE,'engine_sha256':engine_hash,'as_of':cutoff,'last_data_at':last.closed_at,'price':last.close,
            'periods':summary,'catalog':catalog,'multilevel':{'link_states':dict(Counter(x['state'] for x in links['signals'])),
                'interval_nesting':len(links['interval_nesting']),'nested_evidence':sum(x['matched_depth']>1 for x in links['interval_nesting']),
                'small_to_large':len(links['small_to_large'])},'strict_original_equivalence_proven':False,'execution_allowed':False}
    atomic_json(OUT/'run-summary.json',result)
    (OUT/'run-info.js').write_text('window.RUN='+json.dumps(result,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
    (OUT/'multilevel-summary.js').write_text('window.MULTI='+json.dumps(compact,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
    print(json.dumps({'ready':True,'periods':len(catalog),'multilevel':result['multilevel']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
