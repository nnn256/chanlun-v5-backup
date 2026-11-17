"""Compare frozen-filter and baseline proximity without fitting holdout results."""
import argparse
import gzip
import json
from pathlib import Path
import statistics


def load(root,symbol,period):
    path=Path(root)/symbol/period/'intraday-research.json.gz'
    return json.loads(gzip.decompress(path.read_bytes()))


def summarize(rows,side,horizons):
    selected=[r for r in rows if r['side']==side]
    scored=[r for r in selected if r.get('daily_extreme_gap_bps') is not None]
    gaps=[r['daily_extreme_gap_bps'] for r in scored]
    result={'alerts':len(selected),'next_open_scored':len(scored),
            'median_gap_to_session_extreme_bps':statistics.median(gaps) if gaps else None,
            'within_50bps':sum(v<=50 for v in gaps),'within_100bps':sum(v<=100 for v in gaps)}
    for h in horizons:
        values=[r['future_labels'][str(h)]['directional_close_return'] for r in selected
                if r.get('future_labels',{}).get(str(h),{}).get('state')=='observed']
        result[f'forward_{h}_bars']={'observed':len(values),
                                    'positive_fraction':sum(v>0 for v in values)/len(values) if values else None,
                                    'mean_directional_return':statistics.fmean(values) if values else None}
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--filtered',type=Path,required=True)
    p.add_argument('--symbol',default='sz300949')
    p.add_argument('--period',choices=('1m','5m'),required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    baseline,filtered=(load(r,a.symbol,a.period) for r in (a.baseline,a.filtered))
    keys=('input_data_sha256','evaluation_sessions','as_of')
    if any(baseline[k]!=filtered[k] for k in keys):raise ValueError('profile comparison requires identical frozen input and evaluation window')
    br=baseline['evaluation']['rows'];fr=filtered['evaluation']['rows']
    ids={(r['signal_id'],r['available_at']) for r in br}
    if any((r['signal_id'],r['available_at']) not in ids for r in fr):raise ValueError('filtered alert is absent from unfiltered baseline')
    result={'symbol':a.symbol,'period':a.period,'input_data_sha256':baseline['input_data_sha256'],
            'as_of':baseline['as_of'],'evaluation_sessions':baseline['evaluation_sessions'],
            'baseline_config':baseline['config'],'filtered_config':filtered['config'],
            'thresholds_fitted_to_holdout':False,'execution_allowed':False,
            'comparison':{side:{'baseline':summarize(br,side,(3,6,12)),
                                'filtered':summarize(fr,side,(3,6,12))} for side in ('buy','sell')},
            'conclusions_scope':['Proximity to session high/low is an ex-post descriptive label, not a forecast probability.',
                                 'Fewer filtered alerts can reduce coverage; improved geometry or proximity is not guaranteed.',
                                 'Directional forward labels are not portfolio win rates and omit queue/slippage uncertainty beyond the declared hypothesis.',
                                 'This single-stock comparison does not establish out-of-sample market-wide improvement.']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['comparison'],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
