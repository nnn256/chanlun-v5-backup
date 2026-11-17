import json
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch

from workbench import backtests, store


class BacktestCacheLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / 'db.sqlite3'
        store.initialize(self.db)
        with store.connect(self.db) as db:
            db.executemany('INSERT INTO universe(symbol,code,name,exchange,active) VALUES(?,?,?,?,1)', [
                ('sh600000', '600000', 'A', 'sh'),
                ('sz000001', '000001', 'B', 'sz'),
                ('bj920002', '920002', 'C', 'bj')])
        self.connect = patch.object(backtests, 'connect', lambda: store.connect(self.db))
        self.connect.start()
        self.state = patch.object(backtests, 'STATE', self.root / 'runtime/workbench')
        self.state.start()

    def tearDown(self):
        self.state.stop(); self.connect.stop(); self.tmp.cleanup()

    @staticmethod
    def coverage(available):
        all_symbols = ['sh600000', 'sz000001', 'bj920002']
        sources = {symbol: f'/cache/{symbol}' for symbol in available}
        details = {symbol: {'declared_csv_sha256': 'a' * 64} for symbol in available}
        missing = [symbol for symbol in all_symbols if symbol not in sources]
        return {'sources': sources, 'source_details': details, 'total': 3, 'available': len(sources),
                'missing': len(missing), 'missing_symbols': missing, 'coverage_complete': not missing,
                'schema': 'local_daily_backtest_sources_v1', 'explicit_cache': False,
                'candidate_roots': ['/project/market_data', '/project/jobs/cache'],
                'preflight_semantics': 'metadata identity only; worker checks CSV content hash',
                'source_selection': 'whole file per symbol; never splice', 'network_used': False,
                'invalid_sources': []}

    def test_incomplete_cache_refusal_happens_before_process_launch(self):
        coverage = self.coverage(['sh600000'])
        with (patch.object(backtests, '_coverage', return_value=(coverage, '2026-11-13T15:00:00+08:00')),
              patch.object(backtests.subprocess, 'Popen') as launch):
            with self.assertRaisesRegex(ValueError, '覆盖 1/3'):
                backtests.launch({'scope': 'all', 'engine': 'native', 'cache_policy': 'complete'})
        launch.assert_not_called()

    def test_available_policy_freezes_only_present_sources_and_marks_skipped_universe(self):
        coverage = self.coverage(['sh600000', 'bj920002'])
        proc = Mock(pid=98765)
        with (patch.object(backtests, '_coverage', return_value=(coverage, '2026-11-13T15:00:00+08:00')),
              patch.object(backtests.subprocess, 'Popen', return_value=proc)):
            result = backtests.launch({'scope': 'all', 'engine': 'native', 'cache_policy': 'available'})
        spec = json.loads((Path(result['output']) / 'request.json').read_text(encoding='utf-8'))
        self.assertEqual([r['symbol'] for r in spec['records']], ['bj920002', 'sh600000'])
        self.assertEqual(spec['requested_total'], 3)
        self.assertEqual(spec['skipped_missing_count'], 1)
        self.assertEqual(spec['cache_sources']['sh600000'], '/cache/sh600000')
        self.assertEqual(spec['source_hashes']['bj920002'], 'a' * 64)
        self.assertEqual(result['requested_total'], 3)
        self.assertEqual(result['total'], 2)

    def test_all_missing_refuses_and_never_runs_zero_symbol_backtest(self):
        coverage = self.coverage([])
        with (patch.object(backtests, '_coverage', return_value=(coverage, '2026-11-13T15:00:00+08:00')),
              patch.object(backtests.subprocess, 'Popen') as launch):
            with self.assertRaisesRegex(ValueError, '没有可运行'):
                backtests.launch({'scope': 'all', 'engine': 'native', 'cache_policy': 'available'})
        launch.assert_not_called()

    def test_failed_symbols_are_paginated_and_legacy_summary_csv_remains_supported(self):
        from unittest.mock import patch as mock_patch
        run = {'id': 'bt-fail', 'output': str(self.root / 'backtest'), 'total': 3,
               'requested_total': 4, 'skipped_missing_count': 1, 'cache_policy': 'available'}
        with store.connect(self.db) as db:
            db.execute('INSERT INTO metadata VALUES(?,?)', ('backtest:bt-fail', json.dumps(run)))
        folder = Path(run['output']); folder.mkdir()
        (folder / 'stocks.csv').write_text(
            'symbol,state,error\nsh600000,failed,FileNotFoundError\nsz000001,failed,bad rows\n', encoding='utf-8')
        with mock_patch.object(backtests, '_summary', return_value={'failed': 2}):
            result = backtests.errors('bt-fail', 1, 1)
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['rows'][0]['symbol'], 'sz000001')

    def test_processed_failure_and_cache_skips_are_not_full_universe_success(self):
        from unittest.mock import patch as mock_patch
        run={'id':'bt-partial','state':'running','pid':999,'created':'2026-11-13T15:00:00+08:00','output':str(self.root/'partial'),
             'total':2,'requested_total':3,'skipped_missing_count':1,'cache_policy':'available'}
        folder=Path(run['output']);folder.mkdir()
        (folder/'summary.json').write_text(json.dumps({'completed':1,'failed':1,'remaining':0,
            'coverage_complete':True,'all_securities_successful':False,'bars':123,'failed_records':[
                {'symbol':'sz000001','error':'bad daily row'}]}),encoding='utf-8')
        with store.connect(self.db) as db:
            db.execute('INSERT INTO metadata VALUES(?,?)',('backtest:bt-partial',json.dumps(run)))
        with mock_patch('workbench.server.alive',return_value=False):
            result=backtests.results()['runs'][0]
        self.assertEqual(result['state'],'completed_with_errors')
        self.assertTrue(result['summary']['processing_complete'])
        self.assertFalse(result['summary']['scheduled_success_complete'])
        self.assertFalse(result['summary']['successful_coverage_complete'])
        self.assertEqual(result['summary']['requested_total'],3)
        self.assertEqual(result['summary']['failure_preview'][0]['symbol'],'sz000001')

    def test_two_concurrent_preflights_only_spawn_one_worker(self):
        barrier=threading.Barrier(2)
        coverage=self.coverage(['sh600000','sz000001','bj920002'])
        def prepare(*args):
            barrier.wait(timeout=5)
            return coverage,'2026-11-13T15:00:00+08:00'
        def start():
            try:return backtests.launch({'scope':'all','engine':'native'})
            except ValueError as error:return str(error)
        with (patch.object(backtests,'_coverage',side_effect=prepare),
              patch.object(backtests.subprocess,'Popen',return_value=Mock(pid=98765)) as spawn,
              patch('workbench.server.alive',return_value=True),
              ThreadPoolExecutor(max_workers=2) as pool):
            results=list(pool.map(lambda _:start(),range(2)))
        self.assertEqual(spawn.call_count,1)
        self.assertEqual(sum(isinstance(result,dict) for result in results),1)
        self.assertTrue(any(isinstance(result,str) and '已有回测' in result for result in results))

    def test_legacy_wrong_cache_resume_refuses_before_spawning(self):
        run={'id':'legacy','state':'running','pid':987,'created':'2026-11-13T15:00:00+08:00',
             'output':str(self.root/'legacy'),'total':1}
        folder=Path(run['output']);folder.mkdir()
        (folder/'request.json').write_text(json.dumps({'records':[{'symbol':'sh600000'}],
            'cache':str(self.root/'missing'),'cutoff':'2026-11-13T15:00:00+08:00'}),encoding='utf-8')
        with store.connect(self.db) as db:
            db.execute('INSERT INTO metadata VALUES(?,?)',('backtest:legacy',json.dumps(run)))
        with patch('workbench.server.alive',return_value=False),patch.object(backtests.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(ValueError,'请新建回测'):
                backtests.resume('legacy')
        spawn.assert_not_called()

    def test_native_preflight_excludes_declared_short_histories_before_worker_launch(self):
        value=self.coverage(['sh600000','sz000001','bj920002'])
        value['source_details']['sh600000']['closed_rows']=49
        value['source_details']['sz000001']['closed_rows']=50
        value['source_details']['bj920002']['closed_rows']=100
        with patch('workbench.backtest_cache.resolve_sources',return_value=value):
            result,cutoff=backtests._coverage({'engine':'native','cutoff':'2026-11-14T15:00:00+08:00'},[])
        self.assertEqual(result['source_pairs_available'],3)
        self.assertEqual(result['available'],2)
        self.assertEqual(result['insufficient_history_symbols'],['sh600000'])
        self.assertNotIn('sh600000',result['sources'])

    def test_summary_payload_removes_large_failure_arrays_and_keeps_pagination(self):
        folder=self.root/'large';folder.mkdir()
        records=[{'symbol':f'sh{i:06d}','error':'FileNotFoundError: missing history'} for i in range(5570)]
        (folder/'summary.json').write_text(json.dumps({'completed':10,'failed':5570,'coverage_complete':True,
            'all_securities_successful':False,'failed_records':records,'failed_symbols':[r['symbol'] for r in records]}),encoding='utf-8')
        run={'id':'large','created':'2026-11-14T15:00:00+08:00','state':'running','pid':987,
             'output':str(folder),'total':5580}
        with store.connect(self.db) as db:db.execute('INSERT INTO metadata VALUES(?,?)',('backtest:large',json.dumps(run)))
        with patch('workbench.server.alive',return_value=False):result=backtests.results()
        self.assertLess(len(json.dumps(result)),5000)
        self.assertFalse(result['runs'][0]['summary']['cache_preflight_verified'])
        self.assertEqual(result['runs'][0]['state'],'completed_with_errors')
        page=backtests.errors('large',20,20)
        self.assertEqual(page['rows'],records[20:40])
        self.assertEqual(page['total'],5570)


if __name__ == '__main__':
    unittest.main()
