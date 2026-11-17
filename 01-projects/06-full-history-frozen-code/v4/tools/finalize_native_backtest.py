from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='Create a portable, path-scrubbed full-market result summary')
    parser.add_argument('run_dir',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    run_dir=args.run_dir.resolve();summary=json.loads((run_dir/'summary.json').read_text(encoding='utf-8'))
    rows=[]
    with (run_dir/'stocks.csv').open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            rows.append({key:row.get(key) for key in ('symbol','name','exchange','state','bars','candidate_count',
                'confirmation_count','withdrawal_count','invalidation_count','completed_trades','total_return',
                'win_rate','max_drawdown','total_fees')})
    failure_types=Counter()
    for failure in summary.get('failed_records',[]):
        error=failure.get('error','unknown error')
        failure_types[error.split(':',1)[0]]+=1
    public_summary={key:summary.get(key) for key in (
        'profile','algorithm_profile','engine_commit','total','completed','failed','remaining',
        'coverage_complete','all_securities_successful','bars','candidates','confirmations',
        'withdrawals','invalidations','confirmed_signals_by_rank_type_side','completed_trades',
        'zero_trade_securities','mean_independent_account_return','median_independent_account_return',
        'total_fees','worst_account_drawdown','performance_scope','execution_allowed','elapsed_seconds')}
    public_summary.update(cutoff=json.loads((run_dir/'manifest.json').read_text(encoding='utf-8')).get('cutoff'),
        failure_types=dict(sorted(failure_types.items())),
        limitations=['当前股票池快照存在幸存者偏差，不含完整历史退市成分。',
            '使用不复权日线；未普遍接入历史分红、送转、ST和上市制度快照。',
            '下一根开盘与声明的滑点/费用是假设成交，不是交易所队列回放。',
            '逐股独立10万元账户均值不是共享资金组合收益，也不保证未来表现。',
            '研究用结构回测，不连接交易，execution_allowed=false。'])
    output=args.output_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    (output/'summary.json').write_text(json.dumps(public_summary,ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'stocks.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields=list(rows[0]) if rows else ['symbol','name','exchange','state']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    readme=(
        "# V4.3.1 Native Full-Market Backtest\n\n"
        "This report contains the fixed-cutoff A-share universe and per-security summary rows. "
        "It excludes workstation paths, raw market cache, task databases, and per-security runtime artifacts.\n\n"
        "Signal creation and confirmation are replayed from each closed daily candle. Orders are eligible no earlier "
        "than the following session open. Candidate points are counted but are not treated as fills. Confirmation "
        "withdrawal and strict native pivot invalidation are processed at their observed bar. The simulator records "
        "fees, T+1, price limits, volume constraints, and next-open fills.\n\n"
        "This is a research simulation, not a profitability guarantee or a live trading instruction. The current "
        "constituent snapshot has survivorship bias, histories are unadjusted, and complete point-in-time "
        "corporate-action, ST, and queue data are unavailable. Each security has a separate 100,000 CNY account; "
        "cross-security mean return is not a shared-capital portfolio return.\n"
    )
    (output/'README.md').write_text(readme,encoding='utf-8')
    print(json.dumps({'output_dir':str(output),'securities_in_csv':len(rows),
        'coverage_complete':public_summary['coverage_complete'],'failed':public_summary['failed'],
        'failure_types':public_summary['failure_types']},ensure_ascii=False))


if __name__=='__main__':main()
