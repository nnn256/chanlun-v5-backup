"""Temporary scheduler fixtures; never launch a worker for the real batch."""
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import json
import gc
import multiprocessing
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import run_adaptive_intraday as adaptive


class EngineSelectionTests(unittest.TestCase):
    def test_default_engine_prefers_nearby_batch_frozen_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'frozen-code/tools').mkdir(parents=True)
            (root / 'frozen-code/tools/run_all_market_intraday.py').write_text('')
            self.assertEqual(adaptive.default_engine_root(root / 'acceleration/run_adaptive_intraday.py'),
                             (root / 'frozen-code').resolve())

    def test_spawn_worker_selects_same_native_engine(self):
        with patch.dict(os.environ, {'LIANGCE_ADAPTIVE_ENGINE_ROOT': str(adaptive.ENGINE_ROOT)}):
            with adaptive.ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1,
                    mp_context=multiprocessing.get_context('spawn'),
                    initializer=adaptive.initialize_worker,
                    initargs=('default', str(adaptive.ENGINE_ROOT))) as pool:
                identity = pool.submit(adaptive.native.code_identity).result(timeout=30)
        self.assertEqual(identity, adaptive.native.code_identity())

    def test_cli_preparse_uses_explicit_engine_root(self):
        result = subprocess.run([sys.executable, '-B', str(Path(adaptive.__file__)),
                                 '--engine-root', str(adaptive.ENGINE_ROOT), '--help'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertIn(b'--runtime-dir', result.stdout)


class PolicyTests(unittest.TestCase):
    def policy(self):
        return adaptive.AdmissionPolicy(logical_cpus=20)

    def test_idle_starts_one_with_512mb_and_waits_below(self):
        p = self.policy()
        required = max(p.minimum, p.guard + p.reservation)
        self.assertTrue(p.decide(required, [], None)[0])
        self.assertFalse(p.decide(required - 1, [], 10)[0])
        self.assertFalse(p.decide(None, [], 10)[0])

    def test_parallel_uses_free_memory_plus_unallocated_growth_reserve(self):
        p = self.policy()
        current = [(256 * adaptive.MIB, 300 * adaptive.MIB)]
        ready, _, needed = p.decide(2048 * adaptive.MIB, current, 50)
        self.assertEqual(needed, 2048 * adaptive.MIB)
        self.assertTrue(ready)
        self.assertFalse(p.decide(2047 * adaptive.MIB, current, 50)[0])

    def test_unreported_pid_reserves_entire_worker_and_cpu_limit(self):
        p = self.policy()
        self.assertFalse(p.decide(2200 * adaptive.MIB, [None], 40)[0])
        self.assertTrue(p.decide(2304 * adaptive.MIB, [None], 40)[0])
        self.assertFalse(p.decide(8000 * adaptive.MIB, [None], None)[0])
        self.assertFalse(p.decide(8000 * adaptive.MIB, [None], 85)[0])

    def test_peak_growth_raises_reservation_and_no_kill_on_pressure(self):
        p = self.policy()
        p.observe([(800 * adaptive.MIB, 1024 * adaptive.MIB)])
        self.assertEqual(p.reservation, 1280 * adaptive.MIB)
        self.assertFalse(p.decide(1500 * adaptive.MIB, [(800 * adaptive.MIB, 1024 * adaptive.MIB)], 30)[0])
        self.assertEqual(p.max_workers, 4)
        self.assertEqual(adaptive.AdmissionPolicy(max_workers=8, logical_cpus=20).max_workers, 4)
        self.assertEqual(adaptive.AdmissionPolicy(logical_cpus=2).max_workers, 1)


class OrchestrationTests(unittest.TestCase):
    def fixture(self, root):
        universe = root / 'universe.json'
        universe.write_text(json.dumps(['sh600000', 'sh600001']))
        output, cache = root / 'analysis', root / 'cache'
        output.mkdir(); cache.mkdir()
        manifest = {'profile': adaptive.native.RUNNER_PROFILE, 'output': str(output), 'cache': str(cache),
                    'cutoff': '2026-11-13T15:00:00+08:00', 'periods': ['1m'],
                    'universe': [{'symbol': 'sh600000', 'name': 'sh600000'}, {'symbol': 'sh600001', 'name': 'sh600001'}],
                    'universe_file_sha256': adaptive.native.file_hash(universe), 'config': {},
                    'sessions': 0, 'warmup': 0, 'code': {'sha256': 'fixture', 'files': {}},
                    'execution_allowed': False, 'uploaded': False}
        adaptive.native.initialize(output / 'tasks.sqlite3', manifest)
        for symbol in ['sh600000', 'sh600001']:
            for path in adaptive.native.source_paths(cache, symbol, '1m'):
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text('fixture')
        return universe, cache, output, manifest

    def test_manifest_is_exact_native_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            universe, cache, output, expected = self.fixture(root)
            with patch.object(adaptive.native, 'asdict_config', return_value={}), patch.object(adaptive.native, 'code_identity', return_value=expected['code']):
                actual = adaptive.build_manifest(universe, cache, output, expected['cutoff'], ('1m',))
            self.assertEqual(actual, expected)
            self.assertNotIn('scheduler', actual)

    def test_submit_one_only_admits_one_and_commits_before_return(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, output, manifest = self.fixture(Path(temp))
            calls = []
            class Pool:
                def submit(self, *args):
                    calls.append(args)
                    return Future()
            futures = {}
            self.assertTrue(adaptive.submit_one(Pool(), futures, output / 'tasks.sqlite3', manifest, True, None))
            self.assertEqual(len(calls), 1)
            self.assertIs(calls[0][0], adaptive.native.worker)
            self.assertEqual(len(futures), 1)
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                counts = dict(db.execute('select state,count(*) from tasks group by state'))
            self.assertEqual(counts, {'pending': 1, 'running': 1})

    def test_failed_submit_rolls_back_running_state(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, output, manifest = self.fixture(Path(temp))
            class Pool:
                def submit(self, *args):
                    raise adaptive.BrokenProcessPool('fixture')
            with self.assertRaises(adaptive.BrokenProcessPool):
                adaptive.submit_one(Pool(), {}, output / 'tasks.sqlite3', manifest, True, None)
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                self.assertEqual(db.execute("select count(*) from tasks where state='running'").fetchone()[0], 0)

    def test_worker_failure_is_recorded_and_pool_break_is_terminal(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, output, _ = self.fixture(Path(temp))
            future = Future(); future.set_exception(adaptive.BrokenProcessPool('fixture abrupt exit'))
            self.assertTrue(adaptive.finish_future(future, ('sh600000', '1m'), output / 'tasks.sqlite3', output))
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                row = db.execute("select state,error from tasks where symbol='sh600000'").fetchone()
            self.assertEqual(row['state'], 'failed')
            self.assertIn('BrokenProcessPool', row['error'])

    def test_source_readiness_is_read_only_cached_and_distinguishes_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, cache, output, _ = self.fixture(root)
            missing_csv, missing_meta = adaptive.native.source_paths(cache, 'sh600001', '1m')
            missing_csv.unlink()
            missing_meta.unlink()
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                before = dict(db.execute("SELECT state,COUNT(*) FROM tasks GROUP BY state").fetchall())
            sampler = adaptive.SourceReadinessCache(interval=30)
            first = sampler.sample(output / 'tasks.sqlite3', cache, now=100)
            self.assertEqual((first['ready'], first['missing'], first['total']), (1, 1, 2))
            self.assertEqual((first['pending_ready'], first['pending_missing']), (1, 1))
            missing_csv.parent.mkdir(parents=True, exist_ok=True)
            missing_meta.parent.mkdir(parents=True, exist_ok=True)
            missing_csv.write_text('late source')
            missing_meta.write_text('{}')
            cached = sampler.sample(output / 'tasks.sqlite3', cache, now=120)
            refreshed = sampler.sample(output / 'tasks.sqlite3', cache, now=131)
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                after = dict(db.execute("SELECT state,COUNT(*) FROM tasks GROUP BY state").fetchall())
            self.assertEqual(cached['missing'], 1)
            self.assertEqual(refreshed['ready'], 2)
            self.assertEqual(before, after)

    def test_gc_boundary_collects_between_replay_and_audit_and_preserves_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output, cache = root / 'out', root / 'cache'
            output.mkdir(); cache.mkdir()
            events = []
            record = {'state': 'complete'}

            def replay(*args, **kwargs):
                events.append('replay')
                return record

            def audit(*args, **kwargs):
                events.append('audit')
                return {'state': 'passed'}

            config = {'output': str(output), 'cache': str(cache), 'config': {},
                      'code': {'sha256': 'fixture'}, 'cutoff': '2026-11-13T15:00:00+08:00'}
            was_enabled = gc.isenabled()
            try:
                with patch.object(adaptive.native, 'code_identity', return_value=config['code']), \
                     patch.object(adaptive.native, 'source_identity', return_value={'stable': True}), \
                     patch.object(adaptive.native, 'write_stage'), \
                     patch.object(adaptive.native, 'run_one', new=replay), \
                     patch.object(adaptive.native, 'audit_record', side_effect=audit), \
                     patch.object(adaptive.native, 'atomic_json'), \
                     patch.object(adaptive.gc, 'collect', side_effect=lambda: events.append('collect') or 0):
                    adaptive.initialize_worker('disabled', str(adaptive.ENGINE_ROOT))
                    result = adaptive.native.worker('sh600000', '1m', config, str(root / 'tasks.sqlite3'), None)
            finally:
                if was_enabled:
                    gc.enable()
            log = output / 'stocks/sh600000/1m/worker.log'
            self.assertEqual(result['state'], 'verified', log.read_text(encoding='utf-8'))
            self.assertEqual(events, ['replay', 'collect', 'audit'])
            self.assertIs(record, result['record'])

    def test_live_worker_is_rejected_before_initialize(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            universe, cache, output, manifest = self.fixture(root)
            (output / 'manifest.json').write_text(json.dumps(manifest))
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                db.execute("UPDATE tasks SET state='running',worker_pid=123 WHERE symbol='sh600000'")
                db.commit()
            with patch.object(adaptive, 'worker_exit_state', return_value='alive'), \
                 patch.object(adaptive.native, 'initialize', side_effect=AssertionError('initialize ran')):
                with self.assertRaisesRegex(ValueError, 'live worker'):
                    adaptive.run(universe, cache, output, manifest['cutoff'], periods=('1m',), resume=True)

    def test_running_task_without_pid_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            universe, cache, output, manifest = self.fixture(root)
            (output / 'manifest.json').write_text(json.dumps(manifest))
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                db.execute("UPDATE tasks SET state='running',worker_pid=NULL WHERE symbol='sh600000'")
                db.commit()
            with patch.object(adaptive.native, 'initialize', side_effect=AssertionError('initialize ran')):
                with self.assertRaisesRegex(ValueError, 'no valid worker PID'):
                    adaptive.run(universe, cache, output, manifest['cutoff'], periods=('1m',), resume=True)
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                state, pid = db.execute("SELECT state,worker_pid FROM tasks WHERE symbol='sh600000'").fetchone()
            self.assertEqual((state, pid), ('running', None))

    def test_unknown_worker_exit_state_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            universe, cache, output, manifest = self.fixture(root)
            (output / 'manifest.json').write_text(json.dumps(manifest))
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                db.execute("UPDATE tasks SET state='running',worker_pid=123 WHERE symbol='sh600000'")
                db.commit()
            with patch.object(adaptive, 'worker_exit_state', return_value='unknown'), \
                 patch.object(adaptive.native, 'initialize', side_effect=AssertionError('initialize ran')):
                with self.assertRaisesRegex(ValueError, 'exit state is unknown'):
                    adaptive.run(universe, cache, output, manifest['cutoff'], periods=('1m',), resume=True)
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                self.assertEqual(db.execute("SELECT state FROM tasks WHERE symbol='sh600000'").fetchone()[0], 'running')

    def test_temp_end_to_end_preserves_manifest_and_completes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            universe, cache, output, manifest = self.fixture(root)
            (output / 'manifest.json').write_text(json.dumps(manifest))
            original = (output / 'manifest.json').read_bytes()
            def worker(*args):
                return {'state': 'verified', 'record': {'input_bars': 2, 'alerts': 1},
                        'verification': {'state': 'passed'}, 'source_identity': {}}
            def executor(**kwargs):
                return ThreadPoolExecutor(max_workers=kwargs['max_workers'])
            with patch.object(adaptive.native, 'asdict_config', return_value={}), \
                 patch.object(adaptive.native, 'code_identity', return_value=manifest['code']), \
                 patch.object(adaptive.native, 'code_matches', return_value=True), \
                 patch.object(adaptive.native, 'worker', side_effect=worker), \
                 patch.object(adaptive.native, 'available_memory_bytes', return_value=8 * 1024**3), \
                 patch.object(adaptive.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 20 * 1024**3})()), \
                 patch.object(adaptive, 'ProcessPoolExecutor', side_effect=executor), \
                 patch.object(adaptive.CpuSampler, 'sample', return_value=40):
                result = adaptive.run(universe, cache, output, manifest['cutoff'], periods=('1m',), resume=True)
            self.assertEqual(result['state'], 'completed')
            self.assertEqual(result['verified'], 2)
            self.assertEqual(result['bars_verified'], 4)
            self.assertEqual((output / 'manifest.json').read_bytes(), original)
            runtime = json.loads((output / 'scheduler/runtime.json').read_text(encoding='utf-8'))
            self.assertEqual(runtime['state'], 'completed')
            self.assertTrue(runtime['uses_unchanged_native_worker'])
            summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['source_readiness']['ready'], 0)
            self.assertEqual(summary['source_readiness']['missing'], 0)

    def test_stop_never_submits_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            universe, cache, output, manifest = self.fixture(root)
            (output / 'manifest.json').write_text(json.dumps(manifest))
            (output / 'STOP').touch()
            with patch.object(adaptive.native, 'asdict_config', return_value={}), \
                 patch.object(adaptive.native, 'code_identity', return_value=manifest['code']), \
                 patch.object(adaptive.native, 'code_matches', return_value=True), \
                 patch.object(adaptive, 'submit_one') as submit:
                result = adaptive.run(universe, cache, output, manifest['cutoff'], periods=('1m',), resume=True)
            submit.assert_not_called()
            self.assertEqual(result['state'], 'stopped_by_file')

    def test_explicit_runtime_and_stop_paths_are_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            universe, cache, output, manifest = self.fixture(root)
            (output / 'manifest.json').write_text(json.dumps(manifest))
            stop = root / 'request-stop'
            stop.touch()
            runtime = root / 'custom-runtime'
            with patch.object(adaptive.native, 'asdict_config', return_value={}), \
                 patch.object(adaptive.native, 'code_identity', return_value=manifest['code']), \
                 patch.object(adaptive, 'submit_one') as submit:
                result = adaptive.run(universe, cache, output, manifest['cutoff'], periods=('1m',),
                                      resume=True, stop_file=stop, runtime_dir=runtime)
            submit.assert_not_called()
            self.assertEqual(result['state'], 'stopped_by_file')
            self.assertTrue((runtime / 'runtime.json').is_file())
            self.assertFalse((output / 'scheduler').exists())


if __name__ == '__main__':
    unittest.main()
