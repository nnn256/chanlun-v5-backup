"""Acquire the current TDX universe, then run V5 recursive structures on it."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from chanmodel.resource_runtime import worker_request,plan_workers

ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_URL = 'http://127.0.0.1:18080'


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument('--run-dir', type=Path)
    value.add_argument('--cache-dir', type=Path, default=ROOT.parent/'data'/'market_data')
    value.add_argument('--base-url', default=DEFAULT_BASE_URL)
    value.add_argument('--workers', default='auto')
    value.add_argument('--source', choices=('tdx', 'ths'), default='tdx')
    value.add_argument('--resume', action='store_true')
    value.add_argument('--smoke', action='store_true', help='scan and recurse over the first 20 provider-listed securities')
    return value


def load_universe(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    records = data.get('records') if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise ValueError(f'invalid provider universe: {path}')
    symbols = [record.get('symbol') for record in records]
    if any(not isinstance(item, str) for item in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError('provider universe has invalid or duplicate symbols')
    return symbols


def validate_cache_symbols(symbols: list[str], cache: Path) -> None:
    daily = cache/'tdx'/'day'/'ohlcv'
    metadata = cache/'tdx'/'day'/'metadata'
    missing = [symbol for symbol in symbols
               if not (daily/f'{symbol}.csv').is_file()
               or not (metadata/f'{symbol}.json').is_file()]
    if missing:
        raise RuntimeError(
            f'{len(missing)} acquired securities have no normalized TDX daily cache; '
            f'first missing: {", ".join(missing[:8])}'
        )


def run(args, *, ensure_provider=None, command_runner=subprocess.run):
    if args.source != 'tdx':
        raise ValueError('V5 recursive analysis requires normalized TDX source receipts; source=ths is not supported')
    requested_workers=worker_request(args.workers)
    # Acquisition uses the compatibility fetcher, whose parser is numeric.
    # Its CPU budget is bounded here; structural analysis remains dynamic.
    plan=plan_workers(requested_workers,memory_per_worker_mb=256)
    if not plan['target_workers']:
        raise ValueError('可用内存不足，暂不启动新的行情采集；等待已有计算完成后重试')
    acquisition_workers=plan['target_workers']
    if ensure_provider is None:
        os.environ['CHANLUN_TDX_BASE_URL'] = args.base_url
        from workbench.services import ensure_tdx
        ensure_provider = ensure_tdx
    os.environ['CHANLUN_TDX_BASE_URL'] = args.base_url
    provider = ensure_provider()
    cache = args.cache_dir.resolve()
    root = args.run_dir.resolve() if args.run_dir else ROOT.parent/'runs'/f'v5-all-a-{__import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")}'
    root.mkdir(parents=True, exist_ok=True)
    acquisition_args = [
        sys.executable, str(ROOT/'market_scan.py'), '--run-dir', str(root),
        '--cache-dir', str(cache), '--workers', str(acquisition_workers), '--source', 'tdx',
        '--base-url', args.base_url,
    ]
    if args.resume:
        acquisition_args.append('--resume')
    if args.smoke:
        acquisition_args.extend(['--limit', '20'])
    acquisition = command_runner(acquisition_args, cwd=ROOT, check=False)
    universe_file = root/'universe.json'
    summary_file = root/'summary.json'
    if not universe_file.is_file() or not summary_file.is_file():
        raise RuntimeError('TDX acquisition did not produce universe.json and summary.json')
    acquired = load_universe(universe_file)
    acquisition_summary = json.loads(summary_file.read_text(encoding='utf-8-sig'))
    if not acquired:
        raise RuntimeError('TDX provider returned an empty universe')
    if acquisition_summary.get('pending') != 0 or not acquisition_summary.get('all_symbols_finished'):
        raise RuntimeError(
            f"TDX acquisition is incomplete: processed={acquisition_summary.get('processed')} "
            f"universe={acquisition_summary.get('universe_count')} pending={acquisition_summary.get('pending')}"
        )
    validate_cache_symbols(acquired, cache)

    recursive_dir = root/'v5-recursive-l8'
    symbols_file = root/'v5-symbols.json'
    symbols_file.write_text(json.dumps({'symbols': acquired}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    recursive_args = [
        sys.executable, str(ROOT/'run_v5_recursive_market.py'), '--run-dir', str(recursive_dir),
        '--cache-dir', str(cache), '--workers', str(args.workers), '--max-rank', '8',
        '--cutoff', acquisition_summary['as_of'], '--symbols-file', str(symbols_file),
    ]
    if args.resume:
        recursive_args.append('--resume')
    recursive = command_runner(recursive_args, cwd=ROOT, check=False)
    recursive_summary_file = recursive_dir/'summary.json'
    if not recursive_summary_file.is_file():
        raise RuntimeError('V5 recursive run did not write summary.json')
    recursive_summary = json.loads(recursive_summary_file.read_text(encoding='utf-8-sig'))
    receipt = {
        'algorithm': '缠论V5', 'acquisition': str(summary_file),
        'acquisition_exit_code': acquisition.returncode,
        'acquisition_completed': len(acquired), 'source': 'tdx', 'source_receipt': provider,
        'recursive': str(recursive_summary_file),
        'recursive_exit_code': recursive.returncode,
        'recursive_success': recursive_summary.get('success'),
        'recursive_failed': recursive_summary.get('failed'),
        'profile': recursive_summary.get('profile'), 'max_rank': recursive_summary.get('max_rank'),
        'cutoff': recursive_summary.get('cutoff'),
        'execution_allowed': False,
    }
    (root/'v5-pipeline.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if recursive.returncode or recursive_summary.get('pending'):
        raise RuntimeError(f'V5 recursive run incomplete: {receipt}')
    return receipt


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = run(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'V5 market pipeline failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
