"""Freeze existing local intraday source receipts for an offline evaluation."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chanmodel.v2.io import load_cache_series
from chanmodel.v2.series import validate_series
from workbench.history import normalize


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--capture', type=Path, default=ROOT/'runs/aoya-full-history-20261108')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    symbols = ['sz300949', 'sz000001', 'sh600000', 'sh600519', 'bj920002', 'bj920010']
    result = {'schema': 1, 'network_requested': False,
              'sampling_rule': 'fixed mixed-exchange local sample, not selected by performance',
              'symbols': symbols, 'sources': [], 'execution_allowed': False}
    frozen = output/'market_data'
    for symbol in symbols:
        series, receipt = load_cache_series(args.cache, symbol, '5m')
        cutoff = series.bars[-1].closed_at
        audit = validate_series(series, cutoff)
        meta_path = args.cache/'tdx/minute5/metadata'/f'{symbol}.json'
        meta = json.loads(meta_path.read_text(encoding='utf-8-sig'))
        raw_path = args.cache/'tdx/minute5/raw'/f'{symbol}.json.gz'
        files = [('ohlcv', Path(receipt['file'])), ('metadata', meta_path)]
        if raw_path.is_file():
            if digest(raw_path) != meta['raw_storage_sha256']:
                raise ValueError(f'{symbol}: original compressed raw receipt changed')
            raw = gzip.decompress(raw_path.read_bytes())
            if hashlib.sha256(raw).hexdigest() != meta['response_sha256']:
                raise ValueError(f'{symbol}: original raw response hash differs')
            files.append(('raw', raw_path))
        for category, path in files:
            target = frozen/'tdx/minute5'/category/path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        result['sources'].append({'symbol': symbol, 'period': '5m', 'audit': audit,
                                  'source': str(Path(receipt['file'])),
                                  'csv_sha256': receipt['csv_sha256'],
                                  'raw_sha256': meta['response_sha256'],
                                  'provider_receipt_checked': True,
                                  'original_response_bytes_checked': raw_path.is_file(),
                                  'raw_source_state': 'matched' if raw_path.is_file() else 'not_packaged_with_local_cache'})

    capture = args.capture
    acquisition = json.loads((capture/'acquisition.json').read_text(encoding='utf-8'))
    if acquisition['symbol'] != 'sz300949':
        raise ValueError('minute capture security mismatch')
    receipt_path = capture/'receipts/minute1.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    raw_path = capture/'raw/minute1.json.gz'
    raw = gzip.decompress(raw_path.read_bytes())
    if hashlib.sha256(raw).hexdigest() != receipt['response_sha256']:
        raise ValueError('minute1 response receipt hash mismatch')
    value = json.loads(raw)
    bars = normalize(value['data'], '1m', receipt['requested_at'])
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(['closed_at', 'open', 'high', 'low', 'close', 'volume', 'is_closed'])
    for b in bars:
        writer.writerow([b.closed_at, b.open, b.high, b.low, b.close, b.volume, str(b.closed).lower()])
    csv_raw = stream.getvalue().encode('utf-8')
    stored = gzip.compress(csv_raw, mtime=0)
    folder = frozen/'tdx/minute1'
    for category in ['ohlcv', 'metadata', 'raw']:
        (folder/category).mkdir(parents=True)
    (folder/'ohlcv/sz300949.csv.gz').write_bytes(stored)
    shutil.copy2(raw_path, folder/'raw/sz300949.json.gz')
    meta = {**receipt, 'symbol': 'sz300949', 'period': 'minute1', 'source': 'tdx',
            'adjustment': 'unadjusted', 'csv_sha256': hashlib.sha256(csv_raw).hexdigest(),
            'csv_storage_sha256': hashlib.sha256(stored).hexdigest(),
            'raw_storage_sha256': digest(raw_path), 'normalization': 'history.normalize native minute1',
            'first_close': bars[0].closed_at, 'last_close': bars[-1].closed_at,
            'rows': len(bars), 'network_requested': False}
    (folder/'metadata/sz300949.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    one, checked = load_cache_series(frozen, 'sz300949', '1m')
    audit = validate_series(one, one.bars[-1].closed_at)
    result['sources'].append({'symbol': 'sz300949', 'period': '1m', 'audit': audit,
                              'source': str(raw_path.resolve()), 'csv_sha256': checked['csv_sha256'],
                              'raw_sha256': receipt['response_sha256'], 'provider_receipt_checked': True})
    result['frozen_files_sha256'] = {p.relative_to(output).as_posix(): digest(p)
                                     for p in sorted(frozen.rglob('*')) if p.is_file()}
    (output/'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output), 'datasets': len(result['sources']),
                      'source_bars': sum(s['audit']['bars_used'] for s in result['sources']),
                      'latest': max(s['audit']['last_close'] for s in result['sources']),
                      'network_requested': False}))


if __name__ == '__main__':
    main()
