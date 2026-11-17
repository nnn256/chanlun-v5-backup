import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from chanmodel.tdx_data import atomic_json,atomic_bytes,now_iso
from chanmodel.v2.engine import multiframe,replay
from workbench.history import load_capture,LABELS


def run(out,name):
    acquisition=json.loads((out/'acquisition.json').read_text(encoding='utf-8'));code=acquisition['symbol'];cutoff=now_iso()
    panels,reports,inputs,bars=load_capture(out,code,cutoff)
    for period,r in reports.items():
        if r:atomic_json(out/'analysis'/f'{period}.json',r)
    roles={p:inputs[p] for p in ('day','30m','5m')}
    strict=multiframe(roles,('day','30m','5m'),cutoff)
    combined=multiframe(roles,('day','30m','5m'),cutoff,volume_tolerance=100)
    atomic_json(out/'multiframe-default.json',strict);atomic_json(out/'multiframe-explicit-volume-tolerance.json',combined)
    last=bars['day'][-1];prev=bars['day'][-2]
    chart={'name':name,'symbol':code,'code':code[2:],'price':last.close,'change':last.close-prev.close,'change_pct':(last.close-prev.close)/prev.close*100,
        'as_of':cutoff,'as_of_bar':last.closed_at[:16].replace('T',' '),'last_close_time':last.closed_at[:16].replace('T',' '),
        'panels':panels,'source':'TDX','adjustment':'不复权','definition_mode':reports['day']['definition_mode'],
        'approximation_loss':reports['day']['remaining_scope'],'input_sha256':{p['period']:p['coverage']['input_sha256'] for p in panels},
        'execution_allowed':False,'strict_original_equivalence_proven':False,'snapshot_semantics':'full history; anchors can precede availability'}
    states=dict(Counter(s['state'] for s in combined['signals']));triggered=states.get('structurally_triggered_under_profile',0)
    chart['triggered']=triggered;chart['result_text']='数据校验未通过' if combined['state']!='calculated' else f'日线主周期研究触发：{triggered}个；100股容差对照'
    atomic_json(out/'chart-data.json',chart);(out/'chart-data.js').write_text('window.CHAN_CHART_DATA='+json.dumps(chart,ensure_ascii=False)+';',encoding='utf-8')
    template=ROOT/'runs/junsheng-v2-chart-20261107';shutil.copytree(template/'assets',out/'assets',dirs_exist_ok=True)
    html=(template/'index.html').read_text(encoding='utf-8').replace('均胜电子',name).replace('600699 · SSE',code[2:]+' · SZSE')
    html=html.replace("const TITLE={day:'日线', '30m':'30分钟','5m':'5分钟'};",'const TITLE='+json.dumps(LABELS,ensure_ascii=False)+';')
    html=html.replace('V2独立计算 · 日线 / 30分钟 / 5分钟','完整历史 · 11种K线周期 · 原生周期与聚合分列')
    html=html.replace('本次V2：日线主周期暂无有效多周期触发。',f"本次V2：{chart['result_text']}。")
    html=html.replace("const single=params.get('period');", "const single=params.get('period');const range=params.get('range');")
    html=html.replace("D.panels.filter(p=>!single||p.period===single)","D.panels.filter(p=>single?p.period===single:['day','30m','5m'].includes(p.period))")
    html=html.replace("p.visible_bars+'根可见'", "p.visible_bars+'根全部载入'")
    html=html.replace("chart.timeScale().setVisibleLogicalRange({from:-2,to:p.bars.length+10});", "chart.timeScale().setVisibleLogicalRange({from:range==='recent'?Math.max(0,p.bars.length-220):-2,to:p.bars.length+10});if(range==='2021'){const end=p.bars.findIndex(b=>b.date_cn>='2022-01-01');chart.timeScale().setVisibleLogicalRange({from:-2,to:end+2});}")
    html=html.replace("d.toISOString().slice(5,10)","d.toISOString().slice(0,7)")
    html=html.replace('body.single .chartbox{height:690px}','body.single .chartbox{height:850px}')
    html=html.replace('body.single{width:1800px}','body.single{width:2400px}')
    html=html.replace('timeScale:{borderColor','timeScale:{minBarSpacing:.001,borderColor')
    (out/'index.html').write_text(html,encoding='utf-8')
    atomic_json(out/'coverage.json',[p['coverage'] for p in panels])
    print(json.dumps({'chart_ready':True,'day_first':chart['panels'][0]['coverage']['first'],'periods':len(panels),'triggered':triggered},ensure_ascii=False),flush=True)
    final,events=replay(inputs['day'].prefix(cutoff));assert final['hierarchy']==reports['day']['hierarchy'] and final['signals']==reports['day']['signals']
    atomic_bytes(out/'day-events.jsonl.gz',gzip.compress(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events).encode(),mtime=0))
    summary={'symbol':code,'name':name,'as_of':cutoff,'last_close_time':chart['last_close_time'],'price':chart['price'],'change_pct':chart['change_pct'],
        'periods':{p['period']:p['coverage'] for p in panels},'daily_replay':{'bars':len(inputs['day'].bars),'events':len(events),'final_matches_snapshot':True},
        'multiframe_states':states,'triggered':triggered,'default_state':strict['state'],'comparison_state':combined['state'],'execution_allowed':False}
    atomic_json(out/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--name',required=True);a=p.parse_args();run(a.output.resolve(),a.name)
