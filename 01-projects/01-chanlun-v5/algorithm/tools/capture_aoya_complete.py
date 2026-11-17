"""Capture all full-layer TradingView sheets, full histories and actual examples."""
from collections import Counter
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/aoya-complete-layers-20261108'
SESSION='aoya-full-layers-4cb45af50456'
CLI=shutil.which('agent-browser')
if CLI and CLI.lower().endswith(('.cmd','.bat')):
    CLI=str(Path(CLI).parent/'node_modules/agent-browser/bin/agent-browser-win32-x64.exe')


def call(*args):
    p=subprocess.run([CLI,'--session',SESSION,*map(str,args)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=70)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    return p.stdout


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--topics-only',action='store_true');args=parser.parse_args()
    run=json.loads((OUT/'run-summary.json').read_text(encoding='utf-8'))
    items=[]
    for p in run['catalog']:
        items.append(dict(period=p['period'],name=p['label']+'_全部图层',query={}))
        if p['kind']=='candles':items.append(dict(period=p['period'],name=p['label']+'_完整历史',query={'range':'all'}))
    panel=json.loads((OUT/'panels/5m.json').read_text(encoding='utf-8'))
    for key,name in [('first_buy','一买'),('second_buy','二买'),('third_buy','三买'),('first_sell','一卖'),('second_sell','二卖'),('third_sell','三卖')]:
        point=next(s for s in panel['signals'] if s['class']==key)
        begin=point['terminal_range'][0];end=max(point['available_at'],point['anchor'])
        span=max(360,(end-point['anchor']+35)/.3,(point['anchor']-begin+35)/.7)
        items.append(dict(period='5m',name='专题_'+name+'_历史证据与确认',query={'anchor':point['anchor'],'span':span},required_class=key))
    for path,name in [('feature_no_gap','特征序列_第一种无缺口'),('feature_gap','特征序列_第二种有缺口')]:
        ix=next(i for i,f in enumerate(panel['features']) if f['confirmation'] and f['confirmation']['path']==path)
        f=panel['features'][ix];items.append(dict(period='5m',name='专题_'+name,query={'feature':ix,'anchor':f['end'],'span':max(360,f['end']-f['start']+160)}))
    revisions=[x for x in panel['revision_ledger']['events'] if x['event']=='candidate_cancelled_and_recovered']
    if revisions:
        items.append(dict(period='5m',name='专题_候选取消与回收',query={'anchor':revisions[-1]['observed_index'],'span':300}))
    links=json.loads((OUT/'multilevel-summary.json').read_text(encoding='utf-8'))
    nests=[n for n in links['interval_nesting'] if n['matched_depth']>1]
    for i,n in enumerate(nests,1):
        for depth,node in enumerate(n['nodes']):
            begin,end=node['range'];items.append(dict(period=node['period'],name=f'区间套{i}_{depth+1}_{node["period"]}_同转折证据',
                query={'anchor':end,'span':max(300,end-begin+180),'comp':node['comparison_id']},nest_id=n['id'],nest_depth=depth))
    call('set','viewport','2400','2200');records=[]
    if args.topics_only and (OUT/'browser-verification.json').exists():
        records=json.loads((OUT/'browser-verification.json').read_text(encoding='utf-8'))
    for index,item in enumerate(items,1):
        if args.topics_only and index<=27:continue
        query={'period':item['period'],'capture':1,**item['query']}
        url=(OUT/'index.html').as_uri()+'?'+urlencode(query)
        call('open',url);call('wait','--fn','window.chartReady === true')
        raw=call('eval','JSON.stringify({ready:window.chartReady,errors:window.chartErrors,proof:window.chartProof,height:document.documentElement.scrollHeight})')
        result=json.loads(raw)
        if isinstance(result,str):result=json.loads(result)
        if not result['ready'] or result['errors'] or result['proof']['plotWidth']<1700:raise ValueError('Render evidence failed '+str(result))
        path=OUT/'png'/f'{index:02d}_奥雅股份_{item["name"]}.png'
        call('screenshot',path,'--full')
        record={**item,'file':path.relative_to(OUT).as_posix(),'browser':result}
        records=[r for r in records if r['file']!=record['file']]+[record];records.sort(key=lambda r:r['file'])
        (OUT/'browser-verification.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'png':path.name,'rendered':result['proof']['rendered']},ensure_ascii=False),flush=True)
    (OUT/'capture-plan.json').write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'png_count':len(records),'zero_browser_errors':True,'nest_examples':len(nests)},ensure_ascii=False))


if __name__=='__main__':main()
