"""Run one TDX stock through V2 and prepare independent TradingView charts."""
import argparse
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.tdx_data import TdxClient,CN,atomic_bytes,atomic_json,cache_history,normalize_daily,normalized_quotes,symbol
from chanmodel.tdx_intraday import fetch_intraday,normalize_intraday,cache_intraday
from chanmodel.v2.io import load_cache_series
from chanmodel.v2.engine import analyze,multiframe,replay


NAMES={'first_buy':'一买候选','second_buy':'二买候选','third_buy':'三买候选',
       'first_sell':'一卖候选','second_sell':'二卖候选','third_sell':'三卖候选'}
PERIOD_NAMES={'day':'日线','30m':'30分钟','5m':'5分钟'}


def cn(value):return datetime.fromisoformat(value).astimezone(CN)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol',required=True);parser.add_argument('--name',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--volume-tolerance',type=float,default=100)
    args=parser.parse_args();code=symbol(args.symbol);out=args.output.resolve()
    if out.exists() and (out/'settings.json').exists():raise ValueError('Use a fresh output directory to preserve prior runs')
    out.mkdir(parents=True,exist_ok=True);cache=out/'cache';cut=datetime.now(CN).replace(microsecond=0)
    client=TdxClient(timeout=60);inputs={};reports={};sources={};panels=[]
    settings={'symbol':code,'name':args.name,'cutoff':cut.isoformat(),'source':'tdx','adjustment':'unadjusted',
              'roles':{'trade':'day','confirm':'30m','trigger':'5m'},'price_tolerance':0.005,'volume_tolerance':args.volume_tolerance,
              'engine_files':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'chanmodel/v2').glob('*.py'))}}
    atomic_json(out/'settings.json',settings)
    data,receipt,raw=client.quotes([code]);atomic_bytes(out/'quote-response.json',raw)
    quotes,missing,extra=normalized_quotes(data,[code],receipt)
    atomic_json(out/'quotes.json',{'receipt':receipt,'quotes':quotes,'missing':missing,'extra':extra})
    for raw_period,period,keep in [('day','day',180),('minute30','30m',280),('minute5','5m',420)]:
        data,receipt,raw=client.history(code) if period=='day' else fetch_intraday(client,code,raw_period)
        atomic_bytes(out/'raw'/f'{raw_period}.json.gz',gzip.compress(raw,compresslevel=6,mtime=0))
        bars,rows,quality=normalize_daily(data,cut) if period=='day' else normalize_intraday(data,cut,raw_period)
        quality['cache_run_as_of']=cut.isoformat()
        metadata=cache_history(cache,code,'tdx',rows,raw,receipt,quality) if period=='day' else cache_intraday(cache,code,raw_period,rows,raw,receipt,quality)
        series,verified=load_cache_series(cache,code,period);inputs[period]=series;sources[period]=metadata
        report=analyze(series,cut.isoformat());reports[period]=report;atomic_json(out/'analysis'/f'{period}.json',report)
        assert report['certificate_audit']['state']=='passed'
        start=max(0,len(bars)-keep)
        points=[{'time':int(cn(b.closed_at).timestamp())+8*3600,'source_index':b.pos,'date_cn':cn(b.closed_at).strftime('%Y-%m-%d %H:%M'),
                 'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume} for b in series.bars[start:]]
        layer=report['hierarchy']['levels'][0];latest_center=layer['centers'][-1] if layer['centers'] else None
        tail=report['base']['segments'][-1] if report['base']['segments'] else None
        note=('向上' if tail['direction']=='up' else '向下')+('候选线段' if tail['state']=='provisional' else '确认线段')+f" · {tail['start_price']:.2f} → {tail['end_price']:.2f}" if tail else '线段结构尚未形成'
        foot=(f"最近L1核心 {latest_center['zd']:.2f}–{latest_center['zg']:.2f}；" if latest_center else '暂无L1中枢；')+'虚线仍待确认。标注端点与最新行情不同，候选不等于当前新买卖点。'
        panels.append({'period':period,'visible_start':start,'input_bars':len(bars),'visible_bars':len(points),'bars':points,
                       'strokes':[s for s in report['base']['strokes'] if s['end']>=start],
                       'segments':[s for s in report['base']['segments'] if s['end']>=start],
                       'centers':[c for c in layer['centers'] if c['end']>=start],
                       'signals':[{**p,'label':NAMES.get(p['class'],p['class'])} for p in report['signals'] if p['rank']==1 and p['state']!='invalidated' and p['anchor']>=start],
                       'latest_center':latest_center,'last_segment':tail,'note':note,'foot':foot})
        print(json.dumps({'period':period,'bars':len(bars),'first':bars[0].closed_at,'last':bars[-1].closed_at,'close':bars[-1].close,'certificates':'passed'},ensure_ascii=False),flush=True)
    strict=multiframe(inputs,('day','30m','5m'),cut.isoformat());atomic_json(out/'multiframe-default.json',strict)
    combined=multiframe(inputs,('day','30m','5m'),cut.isoformat(),volume_tolerance=args.volume_tolerance)
    atomic_json(out/'multiframe-explicit-volume-tolerance.json',combined)
    atomic_json(out/'acquisition.json',sources)
    triggered=sum(p['state']=='structurally_triggered_under_profile' for p in combined['signals'])
    result_text='多周期数据校验未通过，触发结果暂不成立。' if combined['state']=='blocked_data_contract' else '日线主周期暂无有效多周期触发。' if triggered==0 else f'日线主周期有{triggered}个满足本模型条件的研究触发。'
    last,previous=inputs['day'].bars[-2:]
    # Explicit order: daily previous bar then latest close.
    previous,last=last,previous
    change=last.close-previous.close
    chart={'name':args.name,'code':code[2:],'symbol':('SZSE' if code.startswith('sz') else 'SSE' if code.startswith('sh') else 'BSE')+':'+code[2:],
           'cutoff':cut.isoformat(),'as_of_bar':cn(last.closed_at).strftime('%Y-%m-%d %H:%M'),'source':'TDX','adjustment':'不复权',
           'price':last.close,'change':change,'change_pct':100*change/previous.close,'triggered':triggered,'result_text':result_text,
           'engine':'Chanlun V2','chart_engine':'TradingView Lightweight Charts 5.2.1','panels':panels,
           'timezone':'Asia/Shanghai','chart_time_encoding':'source UTC instant shifted +8h only for local chart display',
           'chart_snapshot_semantics':'final-cutoff structure geometry; confirmation may be later than price anchor'}
    atomic_json(out/'chart-data.json',chart)
    (out/'chart-data.js').write_text('window.CHAN_CHART_DATA = '+json.dumps(chart,ensure_ascii=False,allow_nan=False)+';\n',encoding='utf-8')
    template=ROOT/'runs/aoya-v2-chart-20261107'
    assets=out/'assets';assets.mkdir(exist_ok=True)
    for filename in ['lightweight-charts.standalone.production.js','NOTICE','LICENSE','library-source.json']:
        shutil.copy2(template/'assets'/filename,assets/filename)
    html=(template/'index.html').read_text(encoding='utf-8')
    html=html.replace('奥雅股份',args.name).replace('300949 · SZSE',code[2:]+' · '+chart['symbol'].split(':')[0])
    html=html.replace('<b>本次V2：日线主周期暂无有效多周期触发。</b> 30分钟和5分钟尾部仍未确认结束。',f'<b>本次V2：{result_text}</b> 尾部状态以各周期图中标记为准。')
    old="document.querySelector('#price').innerHTML=D.price.toFixed(2)+'<span>+'+D.change.toFixed(2)+'　+'+D.change_pct.toFixed(2)+'%</span>';"
    html=html.replace(old,"document.querySelector('#price').innerHTML=D.price.toFixed(2)+'<span>'+(D.change>=0?'+':'')+D.change.toFixed(2)+'　'+(D.change_pct>=0?'+':'')+D.change_pct.toFixed(2)+'%</span>';document.querySelector('#price').style.color=D.change>=0?'#d84343':'#16947f';")
    html=re.sub(r'const NOTE=\{[^\n]+\};',"const NOTE=Object.fromEntries(D.panels.map(p=>[p.period,p.note]));",html)
    html=re.sub(r'const FOOT=\{[^\n]+\};',"const FOOT=Object.fromEntries(D.panels.map(p=>[p.period,p.foot]));",html)
    html=html.replace("'三买候选 '+s.price.toFixed(2)","s.label+' '+s.price.toFixed(2)")
    (out/'index.html').write_text(html,encoding='utf-8')
    summary={'symbol':code,'name':args.name,'as_of':cut.isoformat(),'last_close_time':chart['as_of_bar'],
             'price':last.close,'previous_close':previous.close,'change_pct':chart['change_pct'],
             'last_daily_ohlc':{k:getattr(last,k) for k in ['open','high','low','close','volume']},
             'multiframe_default_state':strict['state'],'multiframe_explicit_tolerance_state':combined['state'],
             'volume_tolerance_shares':args.volume_tolerance,'triggered_count':triggered,'result_text':result_text,
             'multiframe_states':dict(Counter(p['state'] for p in combined['signals'])),'periods':{},'execution_allowed':False}
    for period,report in reports.items():
        bars=inputs[period].bars
        current=[]
        for p in sorted(report['signals'],key=lambda p:p['anchor'],reverse=True):
            if p['state']=='invalidated':continue
            current.append({k:p[k] for k in ['id','class','rank','state','price','invalidation','zd','zg']})
            current[-1].update(anchor_time=cn(bars[p['anchor']].closed_at).strftime('%Y-%m-%d %H:%M'),available_time=cn(bars[p['available_at']].closed_at).strftime('%Y-%m-%d %H:%M'))
        summary['periods'][period]={'bars':len(bars),'first_close':cn(bars[0].closed_at).strftime('%Y-%m-%d %H:%M'),
           'last_close':cn(bars[-1].closed_at).strftime('%Y-%m-%d %H:%M'),'certificate_audit':report['certificate_audit'],
           'latest_center':next(p['latest_center'] for p in panels if p['period']==period),
           'last_segment':next(p['last_segment'] for p in panels if p['period']==period),
           'active_candidates':current}
    final,events=replay(inputs['day'].prefix(cut.isoformat()))
    assert final['hierarchy']==reports['day']['hierarchy'] and final['signals']==reports['day']['signals']
    atomic_bytes(out/'day-events.jsonl',''.join(json.dumps(e,ensure_ascii=False,allow_nan=False)+'\n' for e in events).encode())
    summary['daily_replay']={'bars':len(inputs['day'].bars),'events':len(events),'final_matches_snapshot':True}
    atomic_json(out/'summary.json',summary)
    atomic_json(out/'algorithm-verification.json',{'status':'pass','source':'TDX','symbol':code,
        'all_source_hashes_checked':True,'all_period_certificates_passed':True,'day_replay_final_matches_snapshot':True,
        'input_bars':{k:len(s.bars) for k,s in inputs.items()},'daily_events':len(events),
        'data_contract_state':combined['state'],'triggered':triggered,'execution_allowed':False})
    print(json.dumps({'output':str(out),'price':last.close,'change_pct':summary['change_pct'],'triggered':triggered,
                      'multiframe_state':combined['state'],'replay_events':len(events)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
