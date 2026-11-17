"""Retry only the three failed native datasets under the original OS lock."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(r'F:/ChanlunAlgorithmTests/2026-11-15-all-market-intraday')
REPAIR = ROOT / 'source-repair-20261117'
sys.path.insert(0, str(ROOT / 'frozen-code'))
from tools.capture_market_intraday import capture_one, capture_output_lock, PERIODS
from chanmodel.tdx_data import atomic_json, now_iso
from chanmodel.v2.io import load_cache_series

TARGETS = [('sz000906', '5m'), ('sz002679', '1m'), ('sz300875', '1m')]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


def main():
    output = ROOT / 'acquisition'
    cache = output / 'market_data'
    profile = json.loads((output / 'acquisition-profile.json').read_text(encoding='utf-8'))
    assert profile['source'] == 'http://127.0.0.1:65004'
    assert profile['cutoff'] == '2026-11-13T15:00:00+08:00'
    assert profile['quarantine_zero_activity'] is True
    report = {'started_at': now_iso(), 'profile': profile, 'targets': [], 'execution_allowed': False, 'uploaded': False}
    baseline = {}
    files = [output / name for name in ('acquisition-results.json', 'acquisition-summary.json', 'summary.json')]
    with capture_output_lock(output):
        results = json.loads(files[0].read_text(encoding='utf-8'))
        summary = json.loads(files[2].read_text(encoding='utf-8'))
        assert results['profile'] == profile
        entries = results['entries']
        before = {(r['symbol'], r['period']): r.copy() for r in entries}
        assert len(before) == len(entries) == summary['requested'] == 11158
        requested_targets = set(TARGETS)
        assert {key for key, row in before.items() if row['state'] != 'complete'} == requested_targets
        backup = REPAIR / 'baseline'
        backup.mkdir(parents=True, exist_ok=False)
        for path in files:
            dest = backup / path.relative_to(output)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            baseline[str(path)] = {'backup': str(dest), 'sha256': digest(path)}
        for code, period in TARGETS:
            folder = cache / 'tdx' / PERIODS[period]
            for path in (cache / 'capture-status' / period / (code + '.json'), folder / 'metadata' / (code + '.json'), folder / 'raw' / (code + '.json.gz'), folder / 'ohlcv' / (code + '.csv.gz')):
                if path.is_file():
                    dest = backup / path.relative_to(output)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
                    baseline[str(path)] = {'backup': str(dest), 'sha256': digest(path)}
        atomic_json(REPAIR / 'BASELINE.json', {'files': baseline, 'failed_entries': [before[k] for k in TARGETS]})
        repair_began = time.monotonic()
        for code, period in TARGETS:
            if shutil.disk_usage(output).free < 10 * 1024 ** 3:
                raise RuntimeError('free disk below original 10 GiB threshold')
            emit({'action': 'capture_one', 'symbol': code, 'period': period})
            result = capture_one(code, period, cache, profile['cutoff'], profile['source'], resume=True,
                                 quarantine_zero_activity=True, timeout=60, attempts=3)
            if result['state'] == 'complete':
                series, receipt = load_cache_series(cache, code, period)
                assert len(series.bars) == result['bars']
                assert receipt['csv_sha256'] == result['csv_sha256']
                meta = json.loads(Path(result['metadata_file']).read_text(encoding='utf-8'))
                assert meta['capture_cutoff'] == profile['cutoff']
                assert meta['quarantine_zero_activity'] is True
            report['targets'].append(result)
            with (output / 'acquisition-events.jsonl').open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps({'observed_at': now_iso(), **result, 'repair': 'targeted_retry_20261117',
                                         'prior_state': before[(code, period)]['state']}, ensure_ascii=False, allow_nan=False,
                                        separators=(',', ':')) + '\n')
            emit(result)
        replacements = {(r['symbol'], r['period']): r for r in report['targets']}
        after_entries = [replacements.get((r['symbol'], r['period']), r) for r in entries]
        unchanged = [r for r in after_entries if (r['symbol'], r['period']) not in requested_targets]
        assert all(row == before[(row['symbol'], row['period'])] for row in unchanged)
        counts = Counter(r['state'] for r in after_entries)
        status_files_present = sum((cache / 'capture-status' / period / (code + '.json')).is_file() for code, period in before)
        summary.update(state='completed', processing_complete=True, done=len(after_entries),
                       complete=counts['complete'], failed=counts['failed'], unavailable=counts['unavailable'],
                       bars=sum(r.get('bars', 0) for r in after_entries), stored_bytes=sum(r.get('stored_bytes', 0) for r in after_entries),
                       updated_at=now_iso(), seconds=round(summary['seconds'] + time.monotonic() - repair_began, 3),
                       status_files_present=status_files_present, status_final_count_verified=status_files_present == len(before))
        atomic_json(files[0], {'profile': profile, 'entries': after_entries})
        atomic_json(files[1], summary)
        atomic_json(files[2], summary)
        assert json.loads(files[1].read_text(encoding='utf-8')) == json.loads(files[2].read_text(encoding='utf-8'))
        report.update(finished_at=now_iso(), summary=summary, unchanged_entries_verified=len(unchanged),
                      source_files_verified=[{'path': str(p), 'sha256': digest(p)} for p in files])
        atomic_json(REPAIR / 'VERIFICATION.json', report)
        atomic_json(REPAIR / 'DIFF.json', {'before': [before[k] for k in TARGETS], 'after': report['targets'],
                                          'summary_before': json.loads((backup / 'summary.json').read_text(encoding='utf-8')),
                                          'summary_after': summary})
        commands = ["$ErrorActionPreference='Stop'"]
        for path, value in baseline.items():
            commands.append("Copy-Item -LiteralPath '" + value['backup'].replace("'", "''") + "' -Destination '" + path.replace("'", "''") + "' -Force")
        commands.append("Write-Output 'Original bookkeeping and prior failed-status files restored; newly acquired cache evidence remains on disk.'")
        (REPAIR / 'ROLLBACK.ps1').write_text('\n'.join(commands) + '\n', encoding='utf-8')
        emit({'summary': summary, 'verification': str(REPAIR / 'VERIFICATION.json')})


if __name__ == '__main__':
    main()
