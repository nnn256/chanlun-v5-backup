import json
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock,patch

import run_v5_market


class V5MarketPipelineTests(unittest.TestCase):
    def setUp(self):
        self.plan_patch=patch.object(run_v5_market,'plan_workers',return_value={'target_workers':4})
        self.plan_patch.start();self.addCleanup(self.plan_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = self.root/'market_data'
        self.cache.mkdir()
        self.run_dir = self.root/'run'
        self.symbols = [f'sh600{i:03d}' for i in range(20)]
        daily = self.cache/'tdx/day/ohlcv'
        metadata = self.cache/'tdx/day/metadata'
        daily.mkdir(parents=True)
        metadata.mkdir(parents=True)
        for symbol in self.symbols:
            (daily/f'{symbol}.csv').write_text('closed_at,open,high,low,close,volume\n', encoding='utf-8')
            (metadata/f'{symbol}.json').write_text(json.dumps({'symbol': symbol}), encoding='utf-8')
        self.args = Namespace(
            source='tdx', workers=4, cache_dir=self.cache, run_dir=self.run_dir,
            base_url='http://127.0.0.1:18080', resume=False, smoke=True,
        )

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, *, pending=0):
        calls = []

        def command(args, **kwargs):
            calls.append(args)
            if args[1].endswith('market_scan.py'):
                root = Path(args[args.index('--run-dir')+1])
                root.mkdir(parents=True, exist_ok=True)
                (root/'universe.json').write_text(json.dumps({'records': [
                    {'symbol': symbol} for symbol in self.symbols
                ]}), encoding='utf-8')
                (root/'summary.json').write_text(json.dumps({
                    'as_of': '2026-11-14T15:00:00+08:00',
                    'pending': pending, 'all_symbols_finished': pending == 0,
                    'processed': len(self.symbols)-pending, 'universe_count': len(self.symbols),
                }), encoding='utf-8')
                return subprocess.CompletedProcess(args, 1 if pending else 0)
            recursive = Path(args[args.index('--run-dir')+1])
            recursive.mkdir(parents=True, exist_ok=True)
            (recursive/'summary.json').write_text(json.dumps({
                'profile': 'course_feature_sequence_recursive_v2', 'max_rank': 8,
                'success': len(self.symbols), 'failed': 0, 'pending': 0,
                'cutoff': '2026-11-14T15:00:00+08:00',
            }), encoding='utf-8')
            return subprocess.CompletedProcess(args, 0)

        return calls, command

    def test_scan_then_recursive_use_exact_provider_universe(self):
        calls, command = self.runner()
        result = run_v5_market.run(self.args, ensure_provider=Mock(return_value={'ready': True}), command_runner=command)
        self.assertEqual(len(calls), 2)
        self.assertIn('--limit', calls[0])
        self.assertEqual(calls[0][calls[0].index('--limit')+1], '20')
        symbol_file = Path(calls[1][calls[1].index('--symbols-file')+1])
        self.assertEqual(json.loads(symbol_file.read_text(encoding='utf-8'))['symbols'], self.symbols)
        self.assertEqual(calls[1][calls[1].index('--max-rank')+1], '8')
        self.assertEqual(result['recursive_success'], 20)
        self.assertEqual(result['max_rank'], 8)

    def test_automatic_pipeline_keeps_dynamic_mode_for_recursive_analysis(self):
        calls,command=self.runner();self.args.workers='auto'
        run_v5_market.run(self.args,ensure_provider=Mock(return_value={'ready':True}),command_runner=command)
        self.assertEqual(calls[0][calls[0].index('--workers')+1],'4')
        self.assertEqual(calls[1][calls[1].index('--workers')+1],'auto')

    def test_low_memory_prevents_acquisition_from_starting(self):
        calls,command=self.runner()
        with patch.object(run_v5_market,'plan_workers',return_value={'target_workers':0}):
            with self.assertRaisesRegex(ValueError,'内存不足'):
                run_v5_market.run(self.args,ensure_provider=Mock(),command_runner=command)
        self.assertEqual(calls,[])

    def test_incomplete_acquisition_never_starts_recursive_stage(self):
        calls, command = self.runner(pending=1)
        with self.assertRaisesRegex(RuntimeError, 'acquisition is incomplete'):
            run_v5_market.run(self.args, ensure_provider=Mock(), command_runner=command)
        self.assertEqual(len(calls), 1)

    def test_ths_is_rejected_before_provider_or_scan(self):
        calls, command = self.runner()
        self.args.source = 'ths'
        provider = Mock()
        with self.assertRaisesRegex(ValueError, 'source=ths is not supported'):
            run_v5_market.run(self.args, ensure_provider=provider, command_runner=command)
        provider.assert_not_called()
        self.assertFalse(calls)

    def test_missing_daily_receipt_blocks_recursive_stage(self):
        calls, command = self.runner()
        (self.cache/'tdx/day/metadata'/f'{self.symbols[0]}.json').unlink()
        with self.assertRaisesRegex(RuntimeError, 'no normalized TDX daily cache'):
            run_v5_market.run(self.args, ensure_provider=Mock(), command_runner=command)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
