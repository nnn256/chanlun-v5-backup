"""Synthetic fixtures only: these tests never launch the real batch runner."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import supervise_replay as supervisor


class SupervisorTests(unittest.TestCase):
    def test_no_progress_crashes_are_bounded(self):
        budget = supervisor.RetryBudget(10)
        self.assertTrue(budget.crash(10))
        self.assertTrue(budget.crash(10))
        self.assertFalse(budget.crash(10))

    def test_progress_resets_streak_but_total_restarts_stay_bounded(self):
        budget = supervisor.RetryBudget(10, max_restarts=2)
        self.assertTrue(budget.crash(10))
        self.assertTrue(budget.crash(11))
        self.assertEqual(budget.without_progress, 0)
        self.assertFalse(budget.crash(12))

    def test_resource_gates(self):
        self.assertEqual(supervisor.resource_gate(9, 20, 10, 10), 'stopped_low_disk')
        self.assertEqual(supervisor.resource_gate(20, 9, 10, 10), 'waiting_memory')
        self.assertEqual(supervisor.resource_gate(20, None, 10, 10), 'stopped_memory_unknown')
        self.assertEqual(supervisor.resource_gate(20, 20, 10, 10), 'ready')

    def fixture(self, path, source='pass\n'):
        (path / 'analysis').mkdir()
        (path / 'frozen-code/tools').mkdir(parents=True)
        (path / 'acceleration-20261117').mkdir(parents=True)
        runner = path / 'frozen-code/tools/run_all_market_intraday.py'
        runner.write_text(source, encoding='utf-8')
        adaptive = path / 'acceleration-20261117/run_adaptive_intraday.py'
        adaptive.write_text(source.replace('.parents[2]', '.parents[1]'), encoding='utf-8')
        (path / 'acceleration-20261117/adaptive_replay.py').write_text(source, encoding='utf-8')
        files = {'tools/run_all_market_intraday.py': hashlib.sha256(runner.read_bytes()).hexdigest()}
        digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        (path / 'analysis/manifest.json').write_text(json.dumps({'code': {'sha256': digest, 'files': files}}))
        with closing(sqlite3.connect(path / 'analysis/tasks.sqlite3')) as db:
            db.execute('create table tasks(state text)')
            db.execute("insert into tasks values ('verified')")
            db.commit()
        return runner

    def test_frozen_code_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = self.fixture(root)
            supervisor.check_frozen_code(root)
            runner.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'frozen code differs'):
                supervisor.check_frozen_code(root)

    def test_analysis_stop_does_not_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / 'analysis/STOP').touch()
            with patch.object(supervisor.subprocess, 'Popen') as popen:
                self.assertEqual(supervisor.supervise(root, .01, .01), 0)
            popen.assert_not_called()

    def test_existing_runner_is_not_restarted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            with supervisor.exclusive_lock(root / 'analysis/runner.lock'):
                def request_stop(_):
                    (root / supervisor.OPERATIONS / 'STOP').touch()
                with patch.object(supervisor.subprocess, 'Popen') as popen, patch.object(supervisor.time, 'sleep', side_effect=request_stop):
                    self.assertEqual(supervisor.supervise(root, .01, .01), 0)
                popen.assert_not_called()
            events = (root / supervisor.OPERATIONS / 'events.jsonl').read_text()
            self.assertIn('waiting_existing_runner', events)

    def test_fake_crash_recovers_then_normal_completion_stops(self):
        source = '''from pathlib import Path
import json, sys
root = Path(__file__).resolve().parents[1]
marker = root / 'fixture-attempt'
if not marker.exists():
    marker.write_text('crashed')
    sys.exit(7)
(root / 'analysis/summary.json').write_text(json.dumps({'processing_complete': True, 'state': 'completed', 'failed': 0}))
'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root, source)
            with patch.object(supervisor, 'memory_available', return_value=2 * 1024**3), \
                 patch.object(supervisor.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 20 * 1024**3})()):
                self.assertEqual(supervisor.supervise(root, .01, .01), 0)
            ops = root / supervisor.OPERATIONS
            status = json.loads((ops / 'status.json').read_text())
            events = [json.loads(line) for line in (ops / 'events.jsonl').read_text().splitlines()]
            self.assertEqual(status['state'], 'completed')
            self.assertEqual(status['restarts'], 1)
            self.assertEqual([item['exit_code'] for item in events if item['event'] == 'runner_exited'], [7, 0])

    def test_configuration_errors_are_terminal(self):
        self.assertTrue(supervisor.fatal_output('ValueError: resume configuration, universe, paths, cutoff or frozen code SHA256 differs'))
        self.assertTrue(supervisor.fatal_output('another batch orchestrator already owns this output directory'))
        self.assertFalse(supervisor.fatal_output('BrokenProcessPool'))
        self.assertTrue(supervisor.fatal_output('running task sh600000/1m has no valid worker PID; refusing database recovery'))

    def test_child_uses_verified_scheduler_with_default_gc(self):
        command = supervisor.child_command(Path('batch'), Path('batch/operations'))
        self.assertIn(str(Path('batch/acceleration-20261117/run_adaptive_intraday.py')), command)
        self.assertEqual(command[command.index('--gc-mode') + 1], 'default')
        self.assertEqual(command[command.index('--guard-mb') + 1], '512')
        self.assertEqual(command[command.index('--reserve-mb') + 1], '512')


if __name__ == '__main__':
    unittest.main()
