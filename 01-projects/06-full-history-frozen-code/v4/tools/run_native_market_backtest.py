from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chanmodel.native_market_backtest import run_market


def main():
    parser = argparse.ArgumentParser(description='因果回放 V4 固定原生缠论引擎全市场日线')
    parser.add_argument('--cache-dir', type=Path, default=ROOT / 'market_data')
    parser.add_argument('--universe', type=Path,
        default=ROOT / 'runs/tdx-all-a-20261106/universe.json')
    parser.add_argument('--output-dir', type=Path,
        default=ROOT / 'runs/native-v4.3.1-full-market-20261113')
    parser.add_argument('--cutoff', default=None,
        help='统一截止时间，例如 2026-11-12T15:00:00+08:00；留空使用每股缓存中实际存在的最后闭合K线')
    parser.add_argument('--workers', default='auto',help='auto or a positive CPU process cap; available RAM still limits admission')
    args = parser.parse_args()
    if args.workers!='auto':
        try:args.workers=int(args.workers)
        except ValueError:parser.error('--workers must be auto or a positive integer')
        if not 1<=args.workers<=32:parser.error('--workers must be auto or between 1 and 32')
    universe = json.loads(args.universe.read_text(encoding='utf-8'))
    records = universe.get('records') if isinstance(universe, dict) else universe
    if not isinstance(records, list) or not records:
        raise ValueError('universe file has no security records')
    started = time.monotonic()

    def progress(value):
        print(json.dumps({'completed': value['completed'], 'total': value['total'],
                          'failed': value['failed'],
        'confirmations': value['confirmations'], 'invalidations': value['invalidations'],
                          'trades': value['completed_trades'],
                          'elapsed_seconds': round(time.monotonic() - started, 1)}, ensure_ascii=False), flush=True)

    summary = run_market(records, args.cache_dir, args.cutoff, args.output_dir,
                         workers=args.workers, progress=progress,
                         stop_file=args.output_dir / 'STOP')
    print(json.dumps({'status': 'complete' if summary['coverage_complete'] else 'partial',
        'output_dir': str(args.output_dir.resolve()), **summary}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
