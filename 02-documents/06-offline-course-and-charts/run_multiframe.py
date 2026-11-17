#!/usr/bin/env python3
"""Run explicit, reconciled CN A-share sampling periods through V2 structures.

This entry point joins witnessed lower movement reversal and a new finer
confirmed stroke. A coincident same-side candidate is never a substitute.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'engine'))

from chanmodel.model import Candle, Config  # noqa: E402
from chanmodel.v2.io import load_series  # noqa: E402
from chanmodel.v2.series import Series, derive_series, session_closes, validate_multiframe  # noqa: E402
from chanmodel.unified import analyze_all  # noqa: E402


def rule_config() -> Config:
    return Config(stroke_mode='strict', second_policy='conservative',
                  third_boundary='strict_outside', max_depth=3)


def period_csv(value: str) -> tuple[str, Path]:
    if '=' not in value:
        raise argparse.ArgumentTypeError('use PERIOD=CSV, e.g. 30m=bars_30m.csv')
    period, path = value.split('=', 1)
    if period not in {'1m','5m','15m','30m','60m','day'} or not path:
        raise argparse.ArgumentTypeError('supported PERIOD: 1m/5m/15m/30m/60m/day')
    return period, Path(path)


def write_csv(series: Series, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['closed_at','open','high','low','close','volume','symbol','period','is_closed'])
        for bar in series.bars:
            writer.writerow([bar.closed_at,bar.open,bar.high,bar.low,bar.close,bar.volume,
                             series.symbol,series.period,'true' if bar.closed else 'false'])


def make_demo_series(days: int = 8, symbol: str = 'sz000001') -> dict[str, Series]:
    """Fabricated prices on exchange-session clocks, not market observations."""
    if not 2 <= days <= 20:
        raise ValueError('demo days must be between 2 and 20')
    current = date(2026, 1, 5)
    bars: list[Candle] = []
    trading_days = 0
    while trading_days < days:
        if current.weekday() < 5:
            for instant in session_closes(current, '1m'):
                i = len(bars)
                close = 100 + 12 * math.sin(i/240) + 6 * math.sin(i/58) + 2.1 * math.sin(i/13)
                prior = bars[-1].close if bars else close - .08
                open_ = prior + .025 * math.sin(i/.9)
                high = max(open_, close) + .14 + .025 * (1 + math.sin(i/4))
                low = min(open_, close) - .14 - .025 * (1 + math.cos(i/4))
                volume = 1000 + (i * 37) % 503
                bars.append(Candle(i,round(open_,6),round(high,6),round(low,6),round(close,6),
                                   instant.isoformat(),volume,True))
            trading_days += 1
        current += timedelta(days=1)
    fine = Series(symbol,'1m','unadjusted',tuple(bars),'synthetic_session_example')
    cut = fine.bars[-1].closed_at
    five = derive_series(fine,'5m',cut)
    thirty = derive_series(five,'30m',cut)
    return {'30m':thirty,'5m':five,'1m':fine}


def analyze_supplied(series: dict[str, Series], roles: tuple[str,str,str], cutoff: str,
                     max_rank: int = 3, price_tolerance: float = .005,
                     volume_tolerance: float = 0.0) -> dict:
    if price_tolerance != .005:
        raise ValueError('this fixed structural-link profile uses price tolerance .005; another tolerance needs a separate profile')
    contract = validate_multiframe(series, roles, cutoff,
                                   price_tolerance=price_tolerance, volume_tolerance=volume_tolerance)
    if contract['state'] == 'verified':
        full = analyze_all(series, cutoff, rule_config(), max_rank, roles, volume_tolerance)
        result = {'schema':'chanlun.multiframe.complete.v1','as_of':cutoff,'state':'calculated',
                  'data_contract':contract,'levels':full['reports'],
                  'signals':full['links']['selected_signals'],'study_links':full['links'],
                  'six_class_coverage':full['six_class_coverage'],
                  'profile':'course_feature_sequence_recursive_v2',
                  'trigger_semantics':'witnessed lower opposite-center-break plus a new finer confirmed stroke; not timestamp label matching'}
    else:
        result = {'schema':'chanlun.multiframe.complete.v1','as_of':cutoff,'state':'blocked_data_contract',
                  'data_contract':contract,'signals':[],'levels':{},
                  'study_links':{'state':'blocked_data_contract','interval_nesting':[],
                                 'small_to_large':[],'small_to_large_audit':[],
                                 'execution_allowed':False}}
    result['configuration'] = asdict(rule_config())
    result['price_match_tolerance'] = price_tolerance
    result['volume_reconciliation_tolerance'] = volume_tolerance
    result['sampling_period_roles'] = {'trade':roles[0],'confirm':roles[1],'trigger':roles[2]}
    result['structural_rank_is_not_timeframe_ratio'] = True
    result['strict_original_equivalence_proven'] = False
    result['execution_allowed'] = False
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trade', type=period_csv, metavar='PERIOD=CSV')
    parser.add_argument('--confirm', type=period_csv, metavar='PERIOD=CSV')
    parser.add_argument('--trigger', type=period_csv, metavar='PERIOD=CSV')
    parser.add_argument('--symbol', default='sz000001', help='explicit exchange + six digit symbol')
    parser.add_argument('--adjustment', choices=['unadjusted','qfq','hfq'], default='unadjusted')
    parser.add_argument('--cutoff', help='ISO-8601 closing time with an explicit timezone')
    parser.add_argument('--source', default='user_csv', help='caller-declared source label')
    parser.add_argument('--price-tolerance', type=float, default=.005)
    parser.add_argument('--volume-tolerance', type=float, default=0)
    parser.add_argument('--max-rank', type=int, choices=range(1,5), default=3)
    parser.add_argument('--demo', action='store_true', help='generate clearly synthetic 1m/5m/30m examples')
    parser.add_argument('--demo-days', type=int, default=8)
    parser.add_argument('--output', type=Path, default=HERE/'multiframe_report.json')
    args = parser.parse_args(argv)
    try:
        receipts = {}
        if args.demo:
            if args.trade or args.confirm or args.trigger:
                raise ValueError('--demo cannot be combined with supplied CSV levels')
            series = make_demo_series(args.demo_days, args.symbol)
            roles = ('30m','5m','1m')
            for period, item in series.items():
                path = HERE/'multiframe_examples'/f'synthetic_{period}.csv'
                write_csv(item,path)
                receipts[period] = {'file':str(path.resolve()),'rows':len(item.bars),
                                    'csv_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                    'synthetic':True,'data_provenance':'fabricated OHLCV; exact aggregation of the finest supplied session sample'}
            cutoff = args.cutoff or series['1m'].bars[-1].closed_at
        else:
            if not all([args.trade,args.confirm,args.trigger,args.cutoff]):
                raise ValueError('provide --trade, --confirm, --trigger and --cutoff, or use --demo')
            roles = tuple(spec[0] for spec in (args.trade,args.confirm,args.trigger))
            if len(set(roles)) != 3:
                raise ValueError('three distinct sampling periods are required')
            series = {}
            for period,path in (args.trade,args.confirm,args.trigger):
                if args.output.resolve() == path.resolve():
                    raise ValueError('output must not overwrite an input CSV')
                series[period],receipts[period] = load_series(path,args.symbol,period,args.adjustment,args.source)
            cutoff = args.cutoff
        report = analyze_supplied(series,roles,cutoff,args.max_rank,args.price_tolerance,args.volume_tolerance)
        report['input_receipts'] = receipts
        report['data_origin'] = 'synthetic_session_example' if args.demo else 'caller_supplied_timestamped_OHLCV'
        report['synthetic'] = bool(args.demo)
        report['limitations'] = [
            'fixed documented decomposition/confirmation profile; not a theorem of original-system uniqueness',
            'CN_A exchange sessions only; calendar holidays must be supplied by the data provider',
            'no execution authorization, cost model or guarantee of predictive performance',
        ]
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'output':str(args.output.resolve()),'state':report['state'],
                          'data_contract':report['data_contract']['state'],'roles':list(roles),
                          'parent_candidates':len(report['signals']),
                          'triggered':sum(s['state']=='structurally_triggered_under_profile' for s in report['signals']),
                          'interval_nesting':len(report['study_links']['interval_nesting']),
                          'small_to_large':len(report['study_links']['small_to_large'])},ensure_ascii=False))
        return 0
    except (ValueError,KeyError,OSError) as exc:
        print(f'error: {type(exc).__name__}: {exc}',file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
