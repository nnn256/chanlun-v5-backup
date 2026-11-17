from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workbench.backtest_cache import resolve_sources


def pair(cache, symbol='sh600000', first='2020-01-01', last='2026-11-05', **overrides):
    folder = cache / 'tdx/day'
    csv_path = folder / 'ohlcv' / f'{symbol}.csv'
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    raw = b'closed_at,open,high,low,close,volume,is_closed\n'
    csv_path.write_bytes(raw)
    meta_path = folder / 'metadata' / f'{symbol}.json'
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {'symbol': symbol, 'source': 'tdx', 'adjustment': 'unadjusted',
                'provider_meta': {'type': 'day'}, 'csv_sha256': hashlib.sha256(raw).hexdigest(),
                'first_date': first, 'last_date': last, 'closed_rows': 100,
                'received_at': last + 'T20:00:00+08:00', **overrides}
    meta_path.write_text(json.dumps(metadata), encoding='utf-8')
    return csv_path, meta_path


class BacktestCacheTests(unittest.TestCase):
    def test_automatic_selection_uses_latest_whole_job_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / 'market_data'
            latest = root / 'runtime/workbench/jobs/job-new/cache'
            pair(original)
            csv_path, _ = pair(latest, last='2026-11-12')
            def read_bytes(path):
                if path.suffix == '.csv':
                    raise AssertionError('CSV read in preflight')
                with path.open('rb') as stream:
                    return stream.read()
            with patch.object(Path, 'read_bytes', autospec=True, side_effect=read_bytes):
                result = resolve_sources(root, [{'symbol': 'sh600000'}], '2026-11-13T15:00:00+08:00')
            self.assertEqual(result['sources']['sh600000'], str(latest.resolve()))
            self.assertEqual(result['source_details']['sh600000']['csv_path'], str(csv_path.resolve()))
            self.assertEqual(result['source_details']['sh600000']['alternative_sources'], 1)
            self.assertFalse(result['source_details']['sh600000']['content_hash_verified'])
            self.assertTrue(result['coverage_complete'])

    def test_explicit_cache_does_not_fall_back_to_other_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pair(root / 'runtime/workbench/jobs/job/cache')
            explicit = root / 'market_data'
            result = resolve_sources(root, [{'symbol': 'sh600000'}], explicit_cache=explicit)
            self.assertEqual(result['sources'], {})
            self.assertEqual(result['missing_symbols'], ['sh600000'])
            self.assertFalse(result['coverage_complete'])
            self.assertEqual(result['candidate_roots'], [str(explicit.resolve())])

    def test_only_valid_metadata_identity_and_pairs_are_selected(self):
        for field, value in [('symbol', 'sz000001'), ('source', 'ths'),
                             ('adjustment', 'qfq'), ('period', '30m'),
                             ('csv_sha256', 'bad-hash'), ('closed_rows', 0)]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, metadata = pair(root / 'market_data')
                values = json.loads(metadata.read_text(encoding='utf-8'))
                values[field] = value
                metadata.write_text(json.dumps(values), encoding='utf-8')
                result = resolve_sources(root, [{'symbol': 'sh600000'}])
                self.assertEqual(result['available'], 0)
                self.assertEqual(len(result['invalid_sources']), 1)

    def test_source_beginning_after_cutoff_does_not_mask_eligible_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pair(root / 'market_data', first='2020-01-01', last='2026-11-05')
            pair(root / 'runtime/workbench/jobs/job/cache', first='2026-11-01', last='2026-11-12')
            result = resolve_sources(root, [{'symbol': 'sh600000'}], '2021-01-01T15:00:00+08:00')
            self.assertEqual(result['sources']['sh600000'], str((root / 'market_data').resolve()))
            self.assertEqual(result['source_details']['sh600000']['effective_last_date'], '2021-01-01')
            self.assertEqual(len(result['invalid_sources']), 1)

    def test_missing_pair_remains_missing_without_creating_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'does-not-exist'
            result = resolve_sources(root, [{'symbol': 'sh600000'}, {'symbol': 'bj920010'}])
            self.assertEqual((result['total'], result['available'], result['missing']), (2, 0, 2))
            self.assertEqual(result['missing_symbols'], ['sh600000', 'bj920010'])
            self.assertFalse(root.exists())

    def test_csv_without_metadata_or_empty_csv_is_not_a_usable_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path, metadata = pair(root / 'market_data')
            metadata.unlink()
            self.assertEqual(resolve_sources(root, [{'symbol': 'sh600000'}])['available'], 0)
            pair(root / 'market_data')
            csv_path.write_bytes(b'')
            result = resolve_sources(root, [{'symbol': 'sh600000'}])
            self.assertEqual(result['available'], 0)
            self.assertIn('empty', result['invalid_sources'][0]['error'])

    def test_china_cutoff_date_and_declared_hash_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, meta_path = pair(root / 'market_data')
            metadata = json.loads(meta_path.read_text(encoding='utf-8'))
            result = resolve_sources(root, [{'symbol': 'sh600000'}], datetime(2026, 11, 4, 20, tzinfo=timezone.utc))
            detail = result['source_details']['sh600000']
            self.assertEqual(detail['effective_last_date'], '2026-11-05')
            self.assertEqual(detail['declared_csv_sha256'], metadata['csv_sha256'])

    def test_bad_record_duplicates_and_ambiguous_cutoff_are_rejected(self):
        for records in [[{'symbol': '600000'}], [{'symbol': 'sh600000'}] * 2, ['sh600000']]:
            with self.subTest(records=records), self.assertRaises(ValueError):
                resolve_sources('.', records)
        with self.assertRaisesRegex(ValueError, 'timezone'):
            resolve_sources('.', [{'symbol': 'sh600000'}], '2026-11-13')


if __name__ == '__main__':
    unittest.main()
