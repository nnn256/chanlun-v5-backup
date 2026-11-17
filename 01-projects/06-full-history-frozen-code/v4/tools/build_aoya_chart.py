"""Re-run the audited V2 on preserved Aoya inputs and emit a TV-chart dataset."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.v2.io import load_cache_series
from chanmodel.v2.engine import analyze,multiframe
from chanmodel.tdx_data import atomic_json,CN


def local_time(value):
    return datetime.fromisoformat(value).astimezone(CN)


def main():
    source=ROOT/'runs/aoya-v2-20261107';out=ROOT/'runs/aoya-v2-chart-20261107'
    config=json.loads((source/'settings.json').read_text(encoding='utf-8'));cutoff=config['cutoff']
    inputs={};panels=[];verification=[]
    for period,keep in [('day',180),('30m',280),('5m',420)]:
        series,receipt=load_cache_series(source/'cache','sz300949',period);inputs[period]=series
        report=analyze(series,cutoff)
        atomic_json(out/'analysis'/f'{period}.json',report)
        old=json.loads((source/f'{period}-analysis.json').read_text(encoding='utf-8'))
        assert report['hierarchy']==old['hierarchy'] and report['signals']==old['signals']
        assert report['certificate_audit']['state']=='passed'
        bars=series.bars;start=max(0,len(bars)-keep)
        points=[{'time':int(local_time(b.closed_at).timestamp())+8*3600,'source_index':b.pos,
                 'date_cn':local_time(b.closed_at).strftime('%Y-%m-%d %H:%M'),
                 'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume} for b in bars[start:]]
        centers=[c for layer in report['hierarchy']['levels'] if layer['rank']==1 for c in layer['centers'] if c['end']>=start]
        signals=[p for p in report['signals'] if p['rank']==1 and p['state']!='invalidated' and p['anchor']>=start]
        segments=[s for s in report['base']['segments'] if s['end']>=start]
        strokes=[s for s in report['base']['strokes'] if s['end']>=start]
        panels.append({'period':period,'visible_start':start,'input_bars':len(bars),'visible_bars':len(points),
                       'bars':points,'strokes':strokes,'segments':segments,'centers':centers,'signals':signals,
                       'latest_center':report['hierarchy']['levels'][0]['centers'][-1] if report['hierarchy']['levels'][0]['centers'] else None,
                       'last_segment':report['base']['segments'][-1],
                       'tail_candidates':[{'class':p['class'],'rank':p['rank'],'price':p['price'],
                                           'anchor':local_time(bars[p['anchor']].closed_at).strftime('%Y-%m-%d %H:%M'),
                                           'available':local_time(bars[p['available_at']].closed_at).strftime('%Y-%m-%d %H:%M')}
                                          for p in report['signals'] if p['state']!='invalidated']})
        verification.append({'period':period,'csv_sha256':receipt['csv_sha256'],'input_bars':len(bars),
                             'visible_bars':len(points),'rerun_matches_saved_v2':True,'certificate_audit':report['certificate_audit']})
    combined=multiframe(inputs,('day','30m','5m'),cutoff,volume_tolerance=100)
    assert combined['state']=='calculated'
    triggered=sum(p['state']=='structurally_triggered_under_profile' for p in combined['signals'])
    last=inputs['day'].bars[-1];previous=inputs['day'].bars[-2]
    data={'symbol':'SZSE:300949','name':'奥雅股份','cutoff':cutoff,'as_of_bar':local_time(last.closed_at).strftime('%Y-%m-%d %H:%M'),
          'source':'TDX','adjustment':'不复权','currency':'CNY','price':last.close,
          'change':last.close-previous.close,'change_pct':100*(last.close/previous.close-1),'triggered':triggered,
          'engine':'Chanlun V2','chart_engine':'TradingView Lightweight Charts 5.2.1','panels':panels,
          'timezone':'Asia/Shanghai','chart_time_encoding':'Unix seconds shifted +08:00 for local-date display; preserved timestamps in source receipts',
          'chart_snapshot_semantics':'final-cutoff geometry; endpoints may precede confirmation; not a historical first-seen chart'}
    atomic_json(out/'chart-data.json',data)
    (out/'chart-data.js').write_text('window.CHAN_CHART_DATA = '+json.dumps(data,ensure_ascii=False,allow_nan=False)+';\n',encoding='utf-8')
    atomic_json(out/'algorithm-verification.json',{'status':'pass','source_run':str(source),'all_periods_rerun':verification,
          'multi_period_price_tolerance':0.005,'multi_period_volume_tolerance_shares':100,'triggered':triggered,
          'engine_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'chanmodel/v2').glob('*.py'))},
          'execution_allowed':False,'full_original_equivalence_proven':False})
    print(json.dumps({'output':str(out),'periods':[(p['period'],p['input_bars'],p['visible_bars']) for p in panels],'rerun':'passed','triggered':triggered},ensure_ascii=False))


if __name__=='__main__':main()
