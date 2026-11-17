"""Reprice preserved causal event ledgers without regenerating their history."""
from dataclasses import replace
from pathlib import Path
import csv,gzip,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from chanmodel.causal_portfolio import simulate,CostModel
from chanmodel.model import load_csv
from chanmodel.tdx_data import CN,atomic_json
from datetime import datetime
from tools.run_aoya_confirmed_backtest import OUT,OLD,PERIODS,ACTIONS,forward_adjust,savegz


def main():
    sys.stdout.reconfigure(encoding='utf-8');d,_=load_csv(OLD/'csv/day.csv')
    daily={datetime.fromisoformat(b.closed_at).astimezone(CN).date().isoformat():b.close for b in d};summaries=[]
    for period in PERIODS:
        target=OUT/period;history=json.loads(gzip.decompress((target/'signal-ledger.json.gz').read_bytes()));raw,_=load_csv(OLD/'csv'/f'{period}.csv')
        raw=[replace(b,closed_at=datetime.fromisoformat(b.closed_at).astimezone(CN).isoformat()) for b in raw if b.closed];adj=forward_adjust(raw);events=history['events']
        pf=simulate(raw,adj,events,daily,ACTIONS,period=period)
        delayed=[{**e,'observed_index':e['observed_index']+1,'observed_at':adj[e['observed_index']+1].closed_at} for e in events if e['observed_index']+1<len(adj)]
        sensitivity={'base':pf['metrics'],'one_bar_extra_latency':simulate(raw,adj,delayed,daily,ACTIONS,period=period)['metrics'],
                     'ten_bps_slippage':simulate(raw,adj,events,daily,ACTIONS,replace(CostModel(),slippage_bps=10),period=period)['metrics']}
        savegz(target/'portfolio.json.gz',pf);atomic_json(target/'sensitivity.json',sensitivity)
        panel=json.loads((OUT/'panels'/f'{period}.json').read_text(encoding='utf-8'));panel.update(portfolio_metrics=pf['metrics'],portfolio_trades=pf['trades'],portfolio_equity=pf['equity'])
        atomic_json(OUT/'panels'/f'{period}.json',panel)
        (OUT/'panels'/f'{period}.js').write_text('window.PANEL='+json.dumps(panel,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
        for name,rows in [('trades',pf['trades']),('equity',pf['equity'])]:
            (target/f'{name}.jsonl.gz').write_bytes(gzip.compress(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows).encode(),mtime=0))
        with (target/'trades.csv').open('w',newline='',encoding='utf-8-sig') as f:
            fields=['signal_id','class','rank','signal_time','entry_time','entry_price','initial_shares','entry_fees','exit_time','exit_price','exit_fees','exit_reason','net_profit','net_return','holding_sessions']
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(pf['trades'])
        summary=json.loads((target/'summary.json').read_text(encoding='utf-8'));summary.update(metrics=pf['metrics'],sensitivities=sensitivity)
        atomic_json(target/'summary.json',summary);summaries.append(summary)
    atomic_json(OUT/'backtest-summary.json',summaries)
    print(json.dumps({'periods':len(summaries),'preserved_causal_ledgers':True,'confirmed':sum(s['confirmed'] for s in summaries),'closed_trades':sum(s['metrics']['completed_trades'] for s in summaries)},ensure_ascii=False))


if __name__=='__main__':main()
