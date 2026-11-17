"""Saved result loading must reuse immutable inputs without hiding revisions."""
from concurrent.futures import ThreadPoolExecutor
import functools
import gzip
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from workbench import saved_result_cache as cache, server, store


class SavedResultCacheTests(unittest.TestCase):
    def setUp(self):
        with cache.LOCK:
            cache.CACHE.clear()
            cache.CACHE_BYTES = 0

    def test_returned_periods_and_evidence_cannot_mutate_cached_snapshot(self):
        def build():
            return {'chart': {'panels': [{'period': 'day'}, {'period': '30m'}]},
                    'evidence': {'original': [1]}}
        first = cache.get_or_build('snapshot', build)
        first['chart']['panels'].clear()
        first['evidence']['original'].append(2)
        second = cache.get_or_build('snapshot', lambda: self.fail('duplicate rebuild'))
        self.assertEqual([p['period'] for p in second['chart']['panels']], ['day', '30m'])
        self.assertEqual(second['evidence']['original'], [1])
        second['chart']['panels'].pop()
        self.assertEqual(len(cache.get_or_build('snapshot', build)['chart']['panels']), 2)

    def test_retained_bytes_and_entries_are_bounded_and_oldest_is_evicted(self):
        value = {'text': 'x' * 120}
        with patch.object(cache, 'MAX_CACHE_BYTES', 270), patch.object(cache, 'MAX_ENTRY_BYTES', 200):
            cache.get_or_build('first', lambda: value)
            cache.get_or_build('second', lambda: value)
            cache.get_or_build('third', lambda: value)
            self.assertNotIn('first', cache.CACHE)
            self.assertEqual(cache.CACHE_BYTES, sum(len(raw) for raw in cache.CACHE.values()))
            self.assertLessEqual(cache.CACHE_BYTES, 270)
        with patch.object(cache, 'MAX_ENTRIES', 1):
            cache.get_or_build('fourth', lambda: value)
            self.assertEqual(list(cache.CACHE), ['fourth'])

    def test_oversize_payload_is_served_but_not_retained(self):
        with patch.object(cache, 'MAX_ENTRY_BYTES', 10):
            value = cache.get_or_build('large', lambda: {'large': 'x' * 40})
        self.assertEqual(value['large'], 'x' * 40)
        self.assertNotIn('large', cache.CACHE)
        self.assertEqual(cache.CACHE_BYTES, 0)

    def test_concurrent_identical_requests_build_once_and_get_isolated_objects(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        def build():
            calls.append(1)
            entered.set()
            self.assertTrue(release.wait(3))
            return {'rows': [1, 2]}
        with ThreadPoolExecutor(max_workers=4) as pool:
            first = pool.submit(cache.get_or_build, 'same', build)
            self.assertTrue(entered.wait(3))
            rest = [pool.submit(cache.get_or_build, 'same', build) for _ in range(3)]
            release.set()
            results = [first.result(3)] + [future.result(3) for future in rest]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len({id(result['rows']) for result in results}), 4)
        results[0]['rows'].append(3)
        self.assertEqual(results[-1]['rows'], [1, 2])

    def test_failed_build_releases_waiters_and_allows_a_later_retry(self):
        entered = threading.Event()
        release = threading.Event()
        def fail():
            entered.set()
            release.wait(3)
            raise ValueError('invalid source')
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.get_or_build, 'bad', fail)
            self.assertTrue(entered.wait(3))
            second = pool.submit(cache.get_or_build, 'bad', fail)
            release.set()
            for future in (first, second):
                with self.assertRaisesRegex(ValueError, 'invalid source'):
                    future.result(3)
        self.assertNotIn('bad', cache.FLIGHTS)
        self.assertEqual(cache.get_or_build('bad', lambda: {'repaired': True}), {'repaired': True})


class SavedStockLoadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'result.json.gz'
        self.db = self.root / 'state.sqlite3'
        store.initialize(self.db)
        self.connect = functools.partial(store.connect, self.db)
        with self.connect() as db:
            db.execute('INSERT INTO universe(symbol,code,name,exchange) VALUES(?,?,?,?)',
                       ('sh600000', '600000', 'sample', 'sh'))
            db.execute('INSERT INTO items(job_id,symbol,state,artifact) VALUES(?,?,?,?)',
                       ('sample', 'sh600000', 'success', 'result.json.gz'))
        self.bundle = {'summary': {'symbol': 'sh600000', 'as_of': '2026-11-12T15:00:00+08:00', 'price': 10},
                       'chart': {'panels': [{'period': 'day', 'bars': [1], 'input_bars': 1},
                                            {'period': '30m', 'bars': [2], 'input_bars': 1}]}}
        self.write()
        with cache.LOCK:
            cache.CACHE.clear()
            cache.CACHE_BYTES = 0
        self.stack = []
        for context in [patch.object(server, 'connect', self.connect), patch.object(server, 'STATE', self.root),
                        patch('workbench.full_compute.expand_legacy', side_effect=lambda value: value),
                        patch('workbench.reference_service.rebuild_bundle', side_effect=lambda value: value),
                        patch('workbench.research_service.attach_bundle', side_effect=lambda value: value),
                        patch('chanmodel.signal_chart.attach_chart_annotations')]:
            self.stack.append(context)
            context.start()

    def tearDown(self):
        for context in reversed(self.stack):
            context.stop()
        self.temp.cleanup()

    def write(self):
        self.path.write_bytes(gzip.compress(json.dumps(self.bundle).encode(), mtime=0))

    def test_repeat_open_reuses_completed_structure_and_annotates_only_once(self):
        with patch('workbench.reference_service.rebuild_bundle', side_effect=lambda value: value) as rebuilt:
            first = server.stock('sh600000', {'job': ['sample']})
            second = server.stock('sh600000', {'job': ['sample']})
        self.assertEqual(rebuilt.call_count, 1)
        self.assertEqual(first, second)

    def test_cached_research_snapshot_reports_zero_bars_advanced_this_request(self):
        def attach(value):
            value['chart']['panels'][0]['regime_research'] = {'runtime': {
                'new_closed_bars': 1426, 'session_reused': False,
                'history_rebuild_reason': 'cold_start'}}
        with patch('workbench.research_service.attach_bundle', side_effect=attach):
            first = server.stock('sh600000', {'job': ['sample']})
            second = server.stock('sh600000', {'job': ['sample']})
            third = server.stock('sh600000', {'job': ['sample']})
        initial = first['chart']['panels'][0]['regime_research']['runtime']
        self.assertFalse(initial['snapshot_reused'])
        self.assertEqual(initial['new_closed_bars'], 1426)
        for result in (second, third):
            runtime = result['chart']['panels'][0]['regime_research']['runtime']
            self.assertTrue(runtime['snapshot_reused'])
            self.assertEqual(runtime['new_closed_bars'], 0)
            self.assertEqual(runtime['snapshot_built_new_closed_bars'], 1426)
            self.assertFalse(runtime['session_reused'])

    def test_default_period_filter_does_not_trim_later_full_export(self):
        self.bundle['chart']['panels'].append({'period': 'week', 'bars': [3], 'input_bars': 1})
        self.write()
        default = server.stock('sh600000', {'job': ['sample']})
        with patch.object(server, 'load_import_evidence') as imported:
            full = server.stock('sh600000', {'job': ['sample'], 'full': ['1']})
        self.assertEqual(len(default['chart']['panels']), 2)
        self.assertEqual(len(full['chart']['panels']), 3)
        imported.assert_called_once()

    def test_full_import_evidence_is_loaded_each_time_and_does_not_pollute_default(self):
        values = iter([100, 200])
        def imported(value):
            value['evidence'] = {'external_value': next(values)}
        with patch.object(server, 'load_import_evidence', side_effect=imported):
            first = server.stock('sh600000', {'job': ['sample'], 'full': ['1']})
            second = server.stock('sh600000', {'job': ['sample'], 'full': ['1']})
        self.assertEqual(first['evidence']['external_value'], 100)
        self.assertEqual(second['evidence']['external_value'], 200)
        self.assertNotIn('evidence', server.stock('sh600000', {'job': ['sample']}))

    def test_period_request_mutation_does_not_change_saved_snapshot(self):
        def history(value, period, date):
            return {'panel': value['chart']['panels'].pop(0)}
        with patch('workbench.full_compute.history_view', side_effect=history):
            period = server.stock('sh600000', {'job': ['sample'], 'period': ['day']})
        self.assertEqual(period['panel']['period'], 'day')
        self.assertEqual(len(server.stock('sh600000', {'job': ['sample']})['chart']['panels']), 2)

    def test_content_revision_invalidates_even_when_size_and_mtime_are_preserved(self):
        self.path.write_bytes(gzip.compress(json.dumps(self.bundle).encode(), compresslevel=0, mtime=0))
        server.stock('sh600000', {'job': ['sample']})
        stamp = self.path.stat()
        self.bundle['summary']['price'] = 20
        self.path.write_bytes(gzip.compress(json.dumps(self.bundle).encode(), compresslevel=0, mtime=0))
        os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertEqual(self.path.stat().st_size, stamp.st_size)
        self.assertEqual(server.stock('sh600000', {'job': ['sample']})['summary']['price'], 20)

    def test_engine_settings_change_invalidates_transformed_snapshot(self):
        with patch('workbench.reference_service.rebuild_bundle', side_effect=lambda value: value) as rebuilt:
            server.stock('sh600000', {'job': ['sample']})
            with patch('chanmodel.reference_engine.SETTINGS', {'changed': True}):
                server.stock('sh600000', {'job': ['sample']})
        self.assertEqual(rebuilt.call_count, 2)

    def test_research_default_configuration_change_invalidates_saved_snapshot(self):
        from dataclasses import dataclass
        from chanmodel.regime_research import RegimeConfig
        @dataclass(frozen=True)
        class RevisedConfig(RegimeConfig):
            drawdown_threshold: float = .13
        with patch('workbench.reference_service.rebuild_bundle',side_effect=lambda value:value) as rebuilt:
            server.stock('sh600000',{'job':['sample']})
            with patch('chanmodel.regime_research.RegimeConfig',RevisedConfig):
                server.stock('sh600000',{'job':['sample']})
        self.assertEqual(rebuilt.call_count,2)

    def test_clipped_legacy_or_external_import_is_not_reused_without_dependency_validation(self):
        for key in ('clipped', 'imported'):
            if key == 'clipped':
                self.bundle['chart']['panels'][0]['input_bars'] = 100
            else:
                self.bundle['chart']['panels'][0]['input_bars'] = 1
                self.bundle['imported_from'] = 'external-example'
            self.write()
            with patch('workbench.reference_service.rebuild_bundle', side_effect=lambda value: value) as rebuilt:
                server.stock('sh600000', {'job': ['sample']})
                server.stock('sh600000', {'job': ['sample']})
            self.assertEqual(rebuilt.call_count, 2)


if __name__ == '__main__':
    unittest.main()
