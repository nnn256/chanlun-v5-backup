"""Preserve historical 09:25 executions; never infer indicative auction books."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'runs/aoya-full-history-20261108'
OUT = ROOT / 'runs/aoya-independent-20261108'


def one(date):
    path = OUT / 'auction-evidence' / f'{date}.json.gz'
    url = f'http://127.0.0.1:18080/api/minute-trade-all?code=sz300949&date={date}'
    result = {'date': date, 'url': url}
    try:
        if path.exists():
            raw = gzip.decompress(path.read_bytes())
        elif date == '20261106' and (OUT / 'trade-history-full-probe.json').exists():
            raw = (OUT / 'trade-history-full-probe.json').read_bytes()
        else:
            with urlopen(url, timeout=25) as response:
                raw = response.read()
                if response.status != 200:
                    raise ValueError('Non-200 transaction response')
        payload = json.loads(raw)
        if payload.get('code') != 0:
            raise ValueError('Provider returned unsuccessful envelope')
        rows = payload['data'].get('List', [])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(raw, compresslevel=3, mtime=0))
        result.update(raw_file=path.relative_to(OUT).as_posix(), raw_sha256=hashlib.sha256(raw).hexdigest(),
                      source_rows=len(rows))
        if any(r['Time'][:10].replace('-', '') != date for r in rows):
            raise ValueError('Response date differs from request')
        execution = [r for r in rows if r['Time'][11:16] == '09:25']
        if not execution:
            return {**result, 'status': 'no_0925_observation',
                    'reason': 'Provider history has no 09:25 record; no inference from regular-session open',
                    'first_observation': rows[0] if rows else None}
        if any(float(r['Price']) <= 0 or float(r['Volume']) < 0 for r in execution):
            raise ValueError('Invalid price/volume')
        prices = [r['Price'] / 1000 for r in execution]
        # A single witnessed price makes O=H=L=C a real one-print bar.
        bar = {'date': date, 'closed_at': execution[-1]['Time'], 'open': prices[0],
               'high': max(prices), 'low': min(prices), 'close': prices[-1],
               'volume': sum(r['Volume'] * 100 for r in execution),
               'records': len(execution), 'semantics': 'observed_0925_matching_executions_only'}
        result.update(status='ok', bar=bar, source_rows=len(rows),
                      raw_file=path.relative_to(OUT).as_posix(), raw_sha256=hashlib.sha256(raw).hexdigest())
    except Exception as exc:
        result.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    return result


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    acquisition = json.loads((SOURCE / 'acquisition.json').read_text(encoding='utf-8'))
    dates = [r['date'] for r in acquisition['time_share_history']['dates'] if r['status'] == 'received']
    manifest = OUT / 'auction-manifest.json'
    old = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
    results = {r['date']: r for r in old if r['status'] in {'ok', 'no_0925_observation'} and (OUT / r['raw_file']).exists()}
    for date in [dates[0], dates[len(dates) // 2], dates[-1]]:
        if date not in results:
            results[date] = one(date)
        print(json.dumps({'probe': results[date]}, ensure_ascii=False), flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(one, date) for date in dates if date not in results]
        for future in as_completed(futures):
            rec = future.result()
            results[rec['date']] = rec
            if len(results) % 100 == 0:
                manifest.write_text(json.dumps(sorted(results.values(), key=lambda r: r['date']), ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps({'done': len(results), 'total': len(dates), 'failed': sum(r['status'] != 'ok' for r in results.values())}), flush=True)
    ordered = sorted(results.values(), key=lambda r: r['date'])
    manifest.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding='utf-8')
    bars = [r['bar'] for r in ordered if r['status'] == 'ok']
    (OUT / 'auction-bars.json').write_text(json.dumps(bars, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'auction_dates': len(bars), 'failed': sum(r['status']=='failed' for r in ordered),
                      'missing_0925': sum(r['status']=='no_0925_observation' for r in ordered),
                      'semantics': '09:25 historical matching executions, not 09:15-09:25 indicative-order-book snapshots'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
