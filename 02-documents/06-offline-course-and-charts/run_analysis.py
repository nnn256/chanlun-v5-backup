#!/usr/bin/env python3
"""Analyze a timestamped OHLC CSV using the bundled declared complete profile."""
import argparse
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'engine'))
from chanmodel.model import Config
from chanmodel.v2.io import load_series
from chanmodel.unified import analyze_all


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv',type=Path,default=HERE/'demo_ohlc.csv')
    parser.add_argument('--period',choices=['1m','5m','15m','30m','60m','day'],default='5m')
    parser.add_argument('--symbol',default='sz000001')
    parser.add_argument('--cutoff',help='timezone-aware ISO-8601 cutoff; default last supplied close')
    parser.add_argument('--source',default=None)
    parser.add_argument('--adjustment',choices=['unadjusted','qfq','hfq'],default='unadjusted')
    parser.add_argument('--max-rank',type=int,default=3)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.resolve()==args.csv.resolve():parser.error('output must not overwrite source CSV')
    if not 1<=args.max_rank<=8:parser.error('--max-rank must be1..8')
    synthetic=args.csv.resolve()==(HERE/'demo_ohlc.csv').resolve()
    source=args.source or ('synthetic_teaching' if synthetic else 'user_csv')
    series,receipt=load_series(args.csv,args.symbol,args.period,args.adjustment,source)
    cutoff=args.cutoff or series.bars[-1].closed_at
    config=Config(stroke_mode='strict',second_policy='conservative',max_depth=3)
    report=analyze_all({args.period:series},cutoff,config,max_rank=args.max_rank)
    report['source_receipts']={args.period:receipt}
    report['synthetic']=synthetic
    report['fixed_profile']='course_feature_sequence_recursive_v2'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output.resolve()),'schema':report['schema'],
                      'rank_count':len(report['reports'][args.period]['hierarchy']['levels']),
                      'signals':len(report['reports'][args.period]['signals']),
                      'execution_allowed':False},ensure_ascii=False))


if __name__=='__main__':main()
