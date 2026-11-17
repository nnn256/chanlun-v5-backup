"""Temporary fixtures only; never reads/writes the live batch cache or task DB."""
from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cuda_audit import cpu_oracle

SCRIPT = Path(__file__).with_name('run_gpu_market_audit.py')
SPEC = importlib.util.spec_from_file_location('gpu_market_audit_under_test', SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


class FakeAuditor:
    calls = []
    device = {'name': 'fixture GPU', 'compute_capability': '8.6'}
    startup_ms = 0.1

    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def audit(self, rows, sessions, verify_cpu=True):
        self.calls.append(len(rows))
        expected = cpu_oracle(rows, sessions)
        if any(expected['flags']):
            raise ValueError('GPU OHLCV validation rejected invalid fixture')
        return {**expected, 'device': self.device,
                'timings_ms': {'h2d': 0.2, 'gpu_kernels': 0.1, 'd2h': 0.1}}


def create_cached_source(root: Path, period='1m', rows=None):
    symbol = 'sh600000'
    part = audit.PERIOD_DIR[period]
    folder = root / 'acquisition/market_data/tdx' / part
    csv_path = folder / 'ohlcv' / f'{symbol}.csv.gz'
    metadata_path = folder / 'metadata' / f'{symbol}.json'
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows or [
        ('2026-11-12T09:31:00+08:00', '2026-11-12', 10.0, 11.0, 9.0, 10.5, 100.0),
        ('2026-11-12T09:32:00+08:00', '2026-11-12', 10.5, 12.0, 10.0, 11.0, 120.0),
        ('2026-11-12T13:01:00+08:00', '2026-11-12', 11.0, 11.5, 10.5, 11.25, 80.0),
        ('2026-11-13T09:31:00+08:00', '2026-11-13', 11.25, 12.5, 11.0, 12.0, 200.0),
        ('2026-11-13T09:32:00+08:00', '2026-11-13', 12.0, 12.2, 11.2, 11.5, 0.0),
    ]
    import io
    text = io.StringIO(newline='')
    fields = ['closed_at', 'open', 'high', 'low', 'close', 'volume', 'is_closed', 'trade_date']
    writer = csv.DictWriter(text, fieldnames=fields)
    writer.writeheader()
    for closed_at, day, open_, high, low, close, volume in rows:
        writer.writerow({'closed_at': closed_at, 'open': open_, 'high': high, 'low': low,
                         'close': close, 'volume': volume, 'is_closed': 'true', 'trade_date': day})
    raw, stored = text.getvalue().encode('utf-8'), None
    stored = gzip.compress(raw, mtime=0)
    csv_path.write_bytes(stored)
    metadata = {'symbol': symbol, 'period': part, 'source': 'tdx', 'adjustment': 'unadjusted',
                'csv_compression': 'gzip', 'csv_sha256': hashlib.sha256(raw).hexdigest(),
                'csv_storage_sha256': hashlib.sha256(stored).hexdigest(),
                'closed_rows': len(rows), 'unique_rows': len(rows)}
    metadata_path.write_text(json.dumps(metadata), encoding='utf-8')
    return symbol, csv_path, metadata_path, rows


class GpuMarketAuditTests(unittest.TestCase):
    def test_source_audit_is_batched_and_merges_session_extrema(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            symbol, csv_path, metadata_path, source_rows = create_cached_source(root)
            fake = FakeAuditor()
            with patch.object(audit, 'CudaAuditor', return_value=fake):
                record = audit.load_source(csv_path, metadata_path, symbol, '1m',
                                           audit.datetime.fromisoformat('2026-11-13T15:00:00+08:00'),
                                           max_batch_rows=2)
            self.assertEqual(fake.calls, [2, 2, 1])
            self.assertEqual(record['bars'], 5)
            self.assertEqual(record['batch_rows_limit'], 2)
            self.assertEqual(record['sessions'][0]['date'], '2026-11-12')
            self.assertEqual(record['sessions'][0]['low'], 9.0)
            self.assertEqual(record['sessions'][0]['high'], 12.0)
            self.assertEqual(record['sessions'][0]['count'], 3)
            self.assertEqual(record['sessions'][1]['low'], 11.0)
            self.assertTrue(record['verified_against_cpu_oracle'])

    def test_hash_mismatch_fails_before_cuda(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            symbol, csv_path, metadata_path, _ = create_cached_source(root)
            metadata = json.loads(metadata_path.read_text())
            metadata['csv_storage_sha256'] = '0' * 64
            metadata_path.write_text(json.dumps(metadata))
            fake = FakeAuditor()
            with patch.object(audit, 'CudaAuditor', return_value=fake):
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    audit.load_source(csv_path, metadata_path, symbol, '1m',
                                      audit.datetime.fromisoformat('2026-11-13T15:00:00+08:00'))
            self.assertEqual(fake.calls, [])

    def test_cutoff_is_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [('2026-11-14T09:31:00+08:00', '2026-11-14', 10, 11, 9, 10.5, 100)]
            symbol, csv_path, metadata_path, _ = create_cached_source(root, rows=rows)
            with patch.object(audit, 'CudaAuditor', return_value=FakeAuditor()):
                with self.assertRaisesRegex(ValueError, 'frozen cutoff'):
                    audit.load_source(csv_path, metadata_path, symbol, '1m',
                                      audit.datetime.fromisoformat('2026-11-13T15:00:00+08:00'))

    def test_invalid_ohlcv_is_not_counted_as_passed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [('2026-11-12T09:31:00+08:00', '2026-11-12', 10, 11, 12, 10.5, 100)]
            symbol, csv_path, metadata_path, _ = create_cached_source(root, rows=rows)
            with patch.object(audit, 'CudaAuditor', return_value=FakeAuditor()):
                with self.assertRaisesRegex(ValueError, 'rejected'):
                    audit.load_source(csv_path, metadata_path, symbol, '1m',
                                      audit.datetime.fromisoformat('2026-11-13T15:00:00+08:00'))

    def test_result_is_resumable_only_for_matching_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'result.json'
            result = {'state': 'passed', 'source_csv_sha256': 'csv',
                      'source_storage_sha256': 'storage', 'gpu_backend_sha256': 'ptx'}
            path.write_text(json.dumps(result))
            self.assertTrue(audit._read_cached_result(path, 'csv', 'storage', 'ptx'))
            self.assertFalse(audit._read_cached_result(path, 'changed', 'storage', 'ptx'))
            self.assertFalse(audit._read_cached_result(path, 'csv', 'storage', 'changed'))

    def test_runner_stops_on_existing_stop_marker_without_cuda_startup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'source-universe').mkdir()
            (root / 'source-universe/universe.json').write_text(json.dumps([{'symbol': 'sh600000'}]))
            (root / 'operations-20261117').mkdir()
            stop = root / 'operations-20261117/STOP'
            stop.write_text(json.dumps({'purpose': 'fixture stop'}))
            with patch.object(audit, 'CudaAuditor') as cuda:
                summary = audit.run(root)
            self.assertEqual(summary['state'], 'stopped_by_file')
            cuda.assert_not_called()

    def test_runner_reuses_one_cuda_context_and_resumes_without_reauditing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'source-universe').mkdir()
            (root / 'source-universe/universe.json').write_text(json.dumps([{'symbol': 'sh600000'}]))
            create_cached_source(root, period='1m')
            create_cached_source(root, period='5m')
            instances = []

            def factory():
                instance = FakeAuditor()
                instances.append(instance)
                return instance

            disk = SimpleNamespace(free=20 * audit.GIB, total=30 * audit.GIB, used=10 * audit.GIB)
            with patch.object(audit, 'CudaAuditor', side_effect=factory), \
                 patch.object(audit, 'available_memory_bytes', return_value=2 * audit.GIB), \
                 patch.object(audit.shutil, 'disk_usage', return_value=disk):
                first = audit.run(root)
                audited_calls = sum(len(instance.calls) for instance in instances)
                self.assertEqual(first['state'], 'completed')
                self.assertEqual(first['passed'], 2)
                self.assertEqual(len(instances), 1)
                self.assertEqual(audited_calls, 2)
                second = audit.run(root)
                self.assertEqual(second['state'], 'completed')
                self.assertEqual(second['passed'], 2)
                self.assertEqual(sum(len(instance.calls) for instance in instances), audited_calls)

    def test_batch_limit_is_capped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'source-universe').mkdir()
            (root / 'source-universe/universe.json').write_text(json.dumps([{'symbol': 'sh600000'}]))
            with self.assertRaisesRegex(ValueError, '1..200000'):
                audit.run(root, max_batch_rows=200001)


if __name__ == '__main__':
    unittest.main()
