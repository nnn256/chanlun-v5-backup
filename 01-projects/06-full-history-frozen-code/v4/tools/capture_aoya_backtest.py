"""Capture all periods, both letter systems and each real confirmation event."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/aoya-backtest-abcd-20261108'
SESSION='aoya-backtest-abcd-4cb45af50456'
CLI=shutil.which('agent-browser')
if CLI.lower().endswith(('.cmd','.bat')):CLI=str(Path(CLI).parent/'node_modules/agent-browser/bin/agent-browser-win32-x64.exe')


def call(*args):
    p=subprocess.run([CLI,'--session',SESSION,*map(str,args)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=70)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    return p.stdout


def main():
    sys.stdout.reconfigure(encoding='utf-8');(OUT/'png').mkdir(exist_ok=True)
    run=json.loads((OUT/'run-summary.json').read_text(encoding='utf-8'));items=[]
    for item in run['catalog']:
        items.append({'period':item['period'],'name':item['label']+'_ABCD与回测','query':{}})
    for item in run['backtests']:
        period=item['period'];p=json.loads((OUT/'panels'/f'{period}.json').read_text(encoding='utf-8'))
        items.append({'period':period,'name':period+'_全历史确认回测','query':{'range':'all'}})
        for i,e in enumerate(p['confirmations'],1):
            first=min(e['anchor'],e['point']['terminal_range'][0]);last=e['observed_index']
            span=max(600,(last-first+80)/.85)
            # The base UI uses 70/30 allocation around anchor.
            anchor=first+span*.7-25
            original=[g for g in p['abcd'] if g['mode']=='a+A+b+B+c_then_d' and g['start']<=e['anchor']<=g['end']]
            candidate=min(original,key=lambda g:abs(g['end']-e['point']['terminal_range'][1])) if original else None
            query={'signal':e['signal_id'],'anchor':anchor,'span':span,'abcd_rank':max(0,e['rank']-1)}
            if candidate:query['pattern']=candidate['id']
            items.append({'period':period,'name':f'{period}_确认{i:02d}_{e["class"]}_L{e["rank"]}','query':query,
                          'confirmation_id':e['signal_id'],'expected_confirm_index':e['observed_index']})
        patterns=[g for g in p['abcd'] if g['mode']=='a+A+b+B+c_then_d' and not g['missing_labels']]
        if patterns:
            g=patterns[-1];span=max(400,(g['end']-g['start']+100)/.90);anchor=g['start']+span*.7-25
            items.append({'period':period,'name':period+'_原文a_A_b_B_c_d全段','query':{'pattern':g['id'],'anchor':anchor,'span':span,'abcd_rank':max(0,g['rank']-1)},'expect_original_labels':['a','A','b','B','c','d']})
    call('set','viewport','2400','2800');records=[]
    for i,item in enumerate(items,1):
        url=(OUT/'index.html').as_uri()+'?'+urlencode({'period':item['period'],'capture':1,**item['query']})
        call('open',url);call('wait','--fn','window.backtestReady === true')
        result=json.loads(call('eval','JSON.stringify({ready:window.backtestReady,errors:window.chartErrors,proof:window.chartProof,height:document.documentElement.scrollHeight})'))
        if isinstance(result,str):result=json.loads(result)
        if not result['ready'] or result['errors'] or result['proof']['plotWidth']<1700:raise ValueError('Browser render failed '+str(result))
        proof=result['proof']
        if item.get('confirmation_id') and (proof['abcd']['confirmedMarkers']<1 or not proof['visibleRange']['from']<=item['expected_confirm_index']<=proof['visibleRange']['to']):raise ValueError('Confirmation not visible')
        if item.get('expect_original_labels') and set(proof['abcd']['originalLabels'])!=set(item['expect_original_labels']):raise ValueError('Original letters not all visible '+str(proof['abcd']))
        path=OUT/'png'/f'{i:02d}_奥雅股份_{item["name"]}.png';call('screenshot',path,'--full')
        records.append({**item,'file':path.relative_to(OUT).as_posix(),'browser':result})
        (OUT/'browser-verification.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'image':path.name,'abcd':proof.get('abcd'),'confirmations':proof.get('confirmationCount')},ensure_ascii=False),flush=True)
    (OUT/'capture-plan.json').write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pngs':len(records),'browser_errors':0,'confirmed_event_topics':sum('confirmation_id' in x for x in items)},ensure_ascii=False))


if __name__=='__main__':main()
