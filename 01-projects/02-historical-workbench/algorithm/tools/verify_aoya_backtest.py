"""Independent rule/fill/causality checks for the historical Aoya experiment."""
from collections import Counter
from dataclasses import replace
from datetime import datetime
import gzip,hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from chanmodel.model import load_csv,time_value
from chanmodel.tdx_data import CN,atomic_json
from chanmodel.causal_replay import source_rule_audit,PROFILE
from chanmodel.complete_study import analyze_complete
from chanmodel.causal_portfolio import charges,CostModel
from tools.run_aoya_confirmed_backtest import OUT,OLD,PERIODS,forward_adjust,ACTIONS


def main():
    sys.stdout.reconfigure(encoding='utf-8');errors=[];checks=[];allconf=[]
    for period in PERIODS:
        path=OLD/'csv'/f'{period}.csv';raw,_=load_csv(path);raw=[replace(b,closed_at=datetime.fromisoformat(b.closed_at).astimezone(CN).isoformat()) for b in raw if b.closed];adj=forward_adjust(raw)
        target=OUT/period;ledger=json.loads(gzip.decompress((target/'signal-ledger.json.gz').read_bytes()));pf=json.loads(gzip.decompress((target/'portfolio.json.gz').read_bytes()))
        if ledger['input_sha256']!=hashlib.sha256(path.read_bytes()).hexdigest():errors.append('Input hash changed '+period)
        if ledger['bars_replayed']!=len(raw) or not ledger['stream_stats']['each_closed_bar_processed']:errors.append('Incomplete per-bar replay '+period)
        previous=None;seen=set()
        for event in ledger['events']:
            if previous and event['observed_index']<previous:errors.append('Non-monotonic events '+period)
            previous=event['observed_index']
            if event['anchor']>event['observed_index']:errors.append('Future anchor '+period)
        for event in ledger['confirmations']:
            if event['signal_id'] in seen:errors.append('Duplicate confirmation '+period)
            seen.add(event['signal_id']);n=event['observed_index'];p=event['point'];prefix=adj[:n+1]
            # Independent full batch construction at the actual confirmed
            # timestamp; the final chart or later prices do not enter.
            batch=analyze_complete('sz300949',period,prefix,prefix[-1].closed_at,ledger['input_sha256']);batch['as_of_index']=n
            candidates={x['id']:x for x in batch['signals']}
            if p['id'] not in candidates:errors.append('No candidate in independent prefix '+period);continue
            start,end=p['terminal_range'];part=prefix[start:end+1]
            pivot=(min if p['side']=='buy' else max)(part,key=lambda b:b.low if p['side']=='buy' else b.high)
            price=pivot.low if p['side']=='buy' else pivot.high
            if p['anchor']!=pivot.pos or abs(p['price']-price)>1e-7:errors.append('Wrong original price extremum '+period)
            future_within_prefix=any(b.low<=p['invalidation'] if p['side']=='buy' else b.high>=p['invalidation'] for b in prefix[p['anchor']+1:])
            if future_within_prefix:errors.append('Already invalidated at confirmation '+period)
            audit=source_rule_audit(p,batch)
            if not audit['passed'] or audit['evidence_available_at']>n:errors.append('Original clause/boundary proof failed '+period)
            if time_value(event['confirmed_at'])!=time_value(prefix[-1].closed_at):errors.append('Confirmation time was backfilled '+period)
            allconf.append({'period':period,'signal_id':p['id'],'class':p['class'],'rank':p['rank'],
                            'event_time':adj[p['anchor']].closed_at,'confirmed_at':event['confirmed_at'],
                            'batch_recomputed_at_confirmation':True,'all_clause_gates_pass':audit['passed'],
                            'terminal_price_is_actual_extreme':True,'latency_bars':n-p['anchor']})
        confirmations={e['signal_id']:e for e in ledger['confirmations']};fills=[x for x in pf['orders'] if x['state']=='filled']
        for fill in fills:
            signal=confirmations.get(fill['signal_id'])
            if not signal:errors.append('Fill without genuine confirmation '+period)
            if fill['bar_index']<=signal['observed_index']:errors.append('Same/past bar fill '+period)
            if time_value(fill['time'])<time_value(fill['signal_time']):errors.append('Fill before decision '+period)
            fee=charges(fill['side'],fill['price']*fill['shares'],fill['time'][:10],CostModel())
            if abs(fee['total']-fill['fees']['total'])>1e-7:errors.append('Fee mismatch '+period)
        for t in pf['trades']:
            if t['exit_time'][:10]<=t['entry_time'][:10]:errors.append('T+1 breached '+period)
            if abs(t['net_profit']-(t['sale_proceeds']-t['entry_cost']))>1e-7:errors.append('Trade profit mismatch '+period)
        for eq in pf['equity']:
            if abs(eq['equity']-(eq['cash']+eq['shares']*eq['close']))>1e-6:errors.append('Equity mismatch '+period);break
            if eq['cash']<-1e-6 or eq['shares']<0:errors.append('Leverage or short position '+period);break
        # Holdings split is bookkeeping, and adjusted prices before the ex-date
        # retain their original values, so future distributions do not rewrite them.
        for a,b in zip(raw,adj):
            if a.closed_at[:10]<'2026-05-29' and [a.open,a.high,a.low,a.close]!=[b.open,b.high,b.low,b.close]:errors.append('Forward action contaminated earlier price '+period);break
        checks.append({'period':period,'bars_replayed':len(raw),'confirmed_count':len(ledger['confirmations']),'independent_prefix_checks':len(ledger['confirmations']),
                       'fills_checked':len(fills),'closed_trades':len(pf['trades']),'equity_points_checked':len(pf['equity']),
                       'final_open_position':pf['open_position'] is not None})
    tests=(OUT/'tests.stderr.txt').read_text(encoding='utf-8');m=re.search(r'Ran (\d+) tests',tests)
    if not m or not tests.rstrip().endswith('OK'):errors.append('Test suite not passed')
    result={'status':'pass' if not errors else 'fail','profile':PROFILE,'checked_at':datetime.now(CN).isoformat(),
            'tests':int(m[1]) if m else None,'periods':checks,'confirmed_events':allconf,'errors':errors,
            'original_rule_meaning':'every encoded original clause recomputed from original prefix objects; finite base/partition conventions remain explicit',
            'strict_original_equivalence_proven':False,'execution_allowed':False}
    atomic_json(OUT/'backtest-verification.json',result)
    print(json.dumps({'status':result['status'],'periods':len(checks),'bars':sum(x['bars_replayed'] for x in checks),'independent_confirmations_verified':len(allconf),'tests':result['tests'],'errors':errors},ensure_ascii=False,indent=2))
    return bool(errors)


if __name__=='__main__':raise SystemExit(main())
