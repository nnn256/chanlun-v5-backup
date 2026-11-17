import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workbench import backtests


class NativeBacktestServiceTests(unittest.TestCase):
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

    def test_native_worker_passes_frozen_per_symbol_sources_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);request=folder/'request.json';output=folder/'out';output.mkdir()
            spec={'engine':'native','records':[{'symbol':'sh600000'}],'cache':str(folder/'unused'),
                  'cache_sources':{'sh600000':str(folder/'job-cache')},'source_hashes':{'sh600000':'a'*64},
                  'cutoff':'2026-11-14T15:00:00+08:00','output':str(output),'workers':2}
            request.write_text(json.dumps(spec),encoding='utf-8')
            with patch.object(backtests,'run_native_market',return_value={'completed':1}) as run:
                backtests.worker(request)
            self.assertEqual(run.call_args.kwargs['cache_sources'],spec['cache_sources'])
            self.assertEqual(run.call_args.kwargs['source_hashes'],spec['source_hashes'])


if __name__ == '__main__':
    unittest.main()
