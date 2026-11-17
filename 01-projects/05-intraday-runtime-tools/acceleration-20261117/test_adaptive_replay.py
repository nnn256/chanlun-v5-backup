"""Temporary scheduler fixtures; never launch a worker for the real batch."""
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import adaptive_replay as adaptive


class PolicyTests(unittest.TestCase):
    def policy(self):
        return adaptive.AdmissionPolicy(logical_cpus=20)

    def test_idle_starts_one_with_512mb_and_waits_below(self):
        p = self.policy()
        required = p.guard + p.reservation
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

    def test_running_task_without_pid_is_not_requeued_automatically(self):
        with tempfile.TemporaryDirectory() as temp:
            _, cache, output, manifest = self.fixture(Path(temp))
            db_path = output / 'tasks.sqlite3'
            with closing(adaptive.native.connect_db(db_path)) as db:
                db.execute("UPDATE tasks SET state='running',worker_pid=NULL WHERE symbol='sh600000'")
                db.commit()
            with self.assertRaisesRegex(ValueError, 'no registered worker PID'):
                adaptive.recover_database(db_path, manifest, cache, False)
            with closing(adaptive.native.connect_db(db_path)) as db:
                state = db.execute("SELECT state FROM tasks WHERE symbol='sh600000'").fetchone()['state']
            self.assertEqual(state, 'running')

    def test_worker_failure_is_recorded_and_pool_break_is_terminal(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, output, _ = self.fixture(Path(temp))
            future = Future(); future.set_exception(adaptive.BrokenProcessPool('fixture abrupt exit'))
            self.assertTrue(adaptive.finish_future(future, ('sh600000', '1m'), output / 'tasks.sqlite3', output))
            with closing(adaptive.native.connect_db(output / 'tasks.sqlite3')) as db:
                row = db.execute("select state,error from tasks where symbol='sh600000'").fetchone()
            self.assertEqual(row['state'], 'failed')
            self.assertIn('BrokenProcessPool', row['error'])

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
            runtime = json.loads((root / 'acceleration-20261117/runtime.json').read_text())
            self.assertEqual(runtime['state'], 'completed')
            self.assertTrue(runtime['uses_unchanged_native_worker'])

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


if __name__ == '__main__':
    unittest.main()
