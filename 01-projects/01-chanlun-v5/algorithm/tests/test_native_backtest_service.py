import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

from workbench import backtests,store,server


class NativeBacktestServiceTests(unittest.TestCase):
    def test_worker_count_allows_automatic_resource_policy(self):
        self.assertEqual(backtests.normalize_workers('auto'),'auto')
    def test_worker_count_accepts_integer_strings_and_integral_numbers(self):
        for value in (16, 16.0, '16', ' 16 '):
            with self.subTest(value=value):
                self.assertEqual(backtests.normalize_workers(value),16)

    def test_worker_count_rejects_booleans_fractions_and_out_of_range(self):
        for value in (True, False, 0, 17, 1.5, '16.0', '', 'many'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,'并行股票数'):
                    backtests.normalize_workers(value)

    def test_simultaneous_launch_requests_atomically_start_only_one_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);database=root/'state.sqlite3';store.initialize(database)
            state=root/'state';cache=root/'data'/'market_data';(cache/'tdx'/'day'/'ohlcv').mkdir(parents=True)
            with store.connect(database) as db:
                db.execute('INSERT INTO universe(symbol,code,name,exchange,active) VALUES(?,?,?,?,1)',
                           ('sh600000','600000','浦发银行','sh'))
            def spawn(*args,**kwargs):
                time.sleep(.1)
                return SimpleNamespace(pid=12345)
            def launch():
                try:
                    return backtests.launch({'scope':'all','workers':'16'})
                except ValueError as exc:
                    return str(exc)
                except Exception as exc:
                    return f'unexpected:{type(exc).__name__}:{exc}'
            outcomes=[]
            with patch.object(backtests,'connect',partial(store.connect,database)), \
                 patch.object(backtests,'STATE',state), \
                 patch.object(backtests,'ROOT',root/'algorithm'), \
                 patch.object(backtests.subprocess,'Popen',side_effect=spawn), \
                 patch.object(server,'alive',return_value=True), \
                 patch.dict(backtests.os.environ,{'CHANLUN_MARKET_DATA_DIR':str(cache)}):
                threads=[threading.Thread(target=lambda:outcomes.append(launch())) for _ in range(2)]
                for thread in threads:thread.start()
                for thread in threads:thread.join()
            accepted=[value for value in outcomes if isinstance(value,dict)]
            rejected=[value for value in outcomes if isinstance(value,str)]
            self.assertEqual(len(accepted),1)
            self.assertEqual(len(rejected),1)
            self.assertIn('already starting or running',rejected[0])

    def test_v5_default_backtest_cache_uses_local_market_data(self):
        with patch.dict(backtests.os.environ, {}, clear=True):
            self.assertEqual(backtests.default_cache_dir(),
                (backtests.ROOT.parent / 'data' / 'market_data').resolve())

    def test_v5_default_backtest_cache_honors_explicit_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(backtests.os.environ, {'CHANLUN_MARKET_DATA_DIR': tmp}):
                self.assertEqual(backtests.default_cache_dir(), Path(tmp).resolve())

    def test_worker_routes_native_jobs_to_the_pinned_engine_and_stopfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            request = folder / 'request.json'
            output = folder / 'run'
            output.mkdir()
            spec = {'engine': 'native', 'records': [{'symbol': 'sh600000'}],
                    'cache': str(folder / 'cache'), 'cutoff': None,
                    'output': str(output), 'workers': 3}
            request.write_text(json.dumps(spec), encoding='utf-8')
            with patch.object(backtests, 'run_native_market', return_value={'completed': 1}) as run_native, \
                 patch.object(backtests, 'run_market', side_effect=AssertionError('proxy engine selected')):
                result = backtests.worker(request)

        self.assertEqual(result, {'completed': 1})
        args = run_native.call_args.args
        self.assertEqual(args[:5], (spec['records'], spec['cache'], None, spec['output'], 3))
        self.assertEqual(args[6], output / 'STOP')

    def test_missing_engine_keeps_legacy_proxy_jobs_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / 'request.json'
            request.write_text(json.dumps({'records': [], 'cache': tmp, 'cutoff': None,
                'output': tmp, 'workers': 1}), encoding='utf-8')
            with patch.object(backtests, 'run_market', return_value={'legacy': True}) as run_proxy, \
                 patch.object(backtests, 'run_native_market', side_effect=AssertionError('native engine selected')):
                result = backtests.worker(request)
        self.assertEqual(result, {'legacy': True})
        self.assertEqual(run_proxy.call_args.args[0], [])


if __name__ == '__main__':
    unittest.main()
