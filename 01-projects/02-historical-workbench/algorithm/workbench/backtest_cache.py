"""Select one complete local daily cache pair per symbol before backtesting.

This is a cheap metadata preflight, not a market-data fetch or a CSV integrity
claim.  The worker must still verify the selected CSV against its saved hash.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re


CN = timezone(timedelta(hours=8))
SYMBOL = re.compile(r'^(sh|sz|bj)\d{6}$')
SHA256 = re.compile(r'^[0-9a-fA-F]{64}$')
MAX_METADATA_BYTES = 1024 * 1024


def _cutoff_date(cutoff):
    if cutoff is None:
        return None
    if isinstance(cutoff, datetime):
        point = cutoff
    elif isinstance(cutoff, str):
        try:
            point = datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('backtest cutoff must be an ISO timestamp with timezone') from exc
    else:
        raise ValueError('backtest cutoff must be an ISO timestamp with timezone')
    if point.tzinfo is None or point.utcoffset() is None:
        raise ValueError('backtest cutoff requires timezone')
    return point.astimezone(CN).date()


def _date(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError(f'cache metadata {name} must be YYYY-MM-DD')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f'cache metadata {name} is invalid') from exc


def _capture_time(metadata):
    """An invalid declared capture clock is not a freshness tie-breaker."""
    value = metadata.get('received_at') or metadata.get('requested_at')
    if value is None:
        return 0.
    try:
        point = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if point.tzinfo is None or point.utcoffset() is None:
            return 0.
        return point.timestamp()
    except (ValueError, OverflowError, OSError):
        return 0.


def _candidate_roots(project_root, explicit_cache):
    if explicit_cache is not None:
        if not isinstance(explicit_cache, (str, Path)) or not str(explicit_cache).strip():
            raise ValueError('explicit history cache must name a cache root')
        return [Path(explicit_cache).expanduser().resolve()]
    root = Path(project_root).expanduser().resolve()
    candidates = [root / 'market_data']
    jobs = root / 'runtime' / 'workbench' / 'jobs'
    if jobs.is_dir():
        candidates.extend(folder / 'cache' for folder in sorted(jobs.iterdir()) if folder.is_dir())
    unique = {}
    for folder in candidates:
        resolved = folder.resolve()
        if not (resolved/'tdx/day/ohlcv').is_dir() or not (resolved/'tdx/day/metadata').is_dir():
            continue
        unique.setdefault(str(resolved).casefold(), resolved)
    return list(unique.values())


def _inspect_pair(cache, symbol, cutoff_date):
    csv_path = cache / 'tdx' / 'day' / 'ohlcv' / f'{symbol}.csv'
    metadata_path = cache / 'tdx' / 'day' / 'metadata' / f'{symbol}.json'
    if not csv_path.is_file() or not metadata_path.is_file():
        return None, None
    try:
        csv_stat = csv_path.stat()
        metadata_stat = metadata_path.stat()
        if csv_stat.st_size <= 0:
            raise ValueError('daily CSV is empty')
        if not 0 < metadata_stat.st_size <= MAX_METADATA_BYTES:
            raise ValueError('daily metadata size is invalid')
        raw = metadata_path.read_bytes()
        metadata = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(metadata, dict):
            raise ValueError('cache metadata must be an object')
        period = metadata.get('period', (metadata.get('provider_meta') or {}).get('type', 'day'))
        if metadata.get('symbol') != symbol or period != 'day':
            raise ValueError('cache metadata symbol or daily period does not match requested security')
        if metadata.get('source') != 'tdx' or metadata.get('adjustment') != 'unadjusted':
            raise ValueError('backtest requires TDX unadjusted daily cache metadata')
        checksum = metadata.get('csv_sha256')
        if not isinstance(checksum, str) or not SHA256.fullmatch(checksum):
            raise ValueError('cache metadata has no valid declared CSV SHA-256')
        first = _date(metadata.get('first_date'), 'first_date')
        last = _date(metadata.get('last_date'), 'last_date')
        if first > last:
            raise ValueError('cache metadata first_date is after last_date')
        if cutoff_date is not None and first > cutoff_date:
            raise ValueError('daily history begins after the backtest cutoff')
        effective = min(last, cutoff_date) if cutoff_date is not None else last
        closed_rows = metadata.get('closed_rows')
        if closed_rows is not None and (type(closed_rows) is not int or closed_rows <= 0):
            raise ValueError('cache metadata closed_rows must be a positive integer')
        detail = {
            'symbol': symbol, 'cache': str(cache), 'csv_path': str(csv_path),
            'metadata_path': str(metadata_path), 'declared_csv_sha256': checksum.lower(),
            'metadata_sha256': hashlib.sha256(raw).hexdigest(), 'first_date': first.isoformat(),
            'last_date': last.isoformat(), 'effective_last_date': effective.isoformat(),
            'closed_rows': closed_rows, 'received_at': metadata.get('received_at'),
            'csv_bytes': csv_stat.st_size, 'csv_mtime_ns': csv_stat.st_mtime_ns,
            'source': 'tdx', 'adjustment': 'unadjusted',
            'content_hash_verified': False,
            'selection_rank': (effective.toordinal(), last.toordinal(),
                               _capture_time(metadata), csv_stat.st_mtime_ns),
        }
        return detail, None
    except (OSError, ValueError, TypeError, AttributeError, OverflowError) as exc:
        return None, {'symbol': symbol, 'cache': str(cache),
                      'error': f'{type(exc).__name__}: {exc}'}


def resolve_sources(project_root, records, cutoff=None, explicit_cache=None):
    """Resolve immutable whole CSV/metadata pairs without opening any CSV body.

    With an explicit cache root, only that root is inspected.  Automatic mode
    inspects the project's market_data and its durable task caches.  A missing
    pair stays missing; no data is generated, copied, downloaded, or spliced.
    """
    symbols = []
    seen=set()
    for record in records:
        symbol = record.get('symbol') if isinstance(record, dict) else None
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            raise ValueError('backtest records require canonical sh/sz/bj security symbols')
        if symbol in seen:
            raise ValueError('backtest records contain duplicate security symbols')
        seen.add(symbol)
        symbols.append(symbol)
    point = _cutoff_date(cutoff)
    roots = _candidate_roots(project_root, explicit_cache)
    selected = {}
    details = {}
    invalid = []
    missing = []
    for symbol in symbols:
        choices = []
        for cache in roots:
            detail, error = _inspect_pair(cache, symbol, point)
            if error is not None:
                invalid.append(error)
            if detail is not None:
                choices.append(detail)
        if not choices:
            missing.append(symbol)
            continue
        # Root order is the final deterministic tie-breaker; whole source
        # identity survives so the worker validates exactly this capture.
        best = max(choices, key=lambda item: item['selection_rank'])
        best = {key: value for key, value in best.items() if key != 'selection_rank'}
        best['alternative_sources'] = len(choices) - 1
        selected[symbol] = best['cache']
        details[symbol] = best
    return {
        'schema': 'local_daily_backtest_sources_v1', 'sources': selected,
        'total': len(symbols), 'available': len(selected), 'missing': len(missing),
        'missing_symbols': missing, 'coverage_complete': not missing,
        'explicit_cache': explicit_cache is not None,
        'candidate_roots': [str(root) for root in roots], 'source_details': details,
        'invalid_sources': invalid, 'cutoff': cutoff.isoformat() if isinstance(cutoff, datetime) else cutoff,
        'preflight_semantics': 'metadata identity and CSV/metadata pair presence only; CSV SHA-256 is verified by each backtest worker before use',
        'source_selection': 'one whole cache per symbol; latest effective date then source date/capture/mtime; no history splicing',
        'network_used': False,
    }
