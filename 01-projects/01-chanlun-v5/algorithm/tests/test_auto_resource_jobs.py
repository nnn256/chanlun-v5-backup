import functools
import json
from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from workbench import jobs,store,backtests


class AutoResourceJobsTests(unittest.TestCase):
    def setup_database(self,root):
        database=root/'state.sqlite3';store.initialize(database)
        connection=functools.partial(store.connect,database)
        settings={'mode':'day','workers':'auto','refresh':False,'cutoff':'2026-11-13T15:00:00+08:00','volume_tolerance':1}
        with connection() as db:
            db.execute('INSERT INTO universe(symbol,code,name,exchange) VALUES(?,?,?,?)',('sh600000','600000','测试','sh'))
            db.execute('INSERT INTO jobs(id,title,mode,state,settings) VALUES(?,?,?,?,?)',('job','auto','day','starting',json.dumps(settings)))
            db.execute('INSERT INTO items(job_id,symbol) VALUES(?,?)',('job','sh600000'))
        return connection

    def test_job_uses_adaptive_executor_and_persists_resource_wait(self):
        with TemporaryDirectory() as tmp:
            connection=self.setup_database(Path(tmp))
            captured={}
            def execute(fn,tasks,**kwargs):
                captured.update(kwargs)
                kwargs['on_resource']({'state':'waiting_memory','active_workers':0})
                for record in tasks:
                    value=Future();value.set_result({'state':'failed','error':'fixture-no-source'})
                    yield record,value
            with patch.object(jobs,'connect',connection),patch.object(jobs,'adaptive_results',side_effect=execute):
                jobs.run('job')
            with connection() as db:
                job=dict(db.execute('SELECT * FROM jobs WHERE id=?',('job',)).fetchone())
                state=db.execute('SELECT state FROM items').fetchone()[0]
            self.assertEqual(captured['workers'],'auto')
            self.assertEqual(json.loads(job['settings'])['resources']['state'],'waiting_memory')
            self.assertEqual(state,'failed')
            self.assertEqual(job['state'],'completed')

    def test_pause_during_resource_wait_keeps_unsubmitted_stock_pending(self):
        with TemporaryDirectory() as tmp:
            connection=self.setup_database(Path(tmp))
            def wait_then_pause(fn,tasks,**kwargs):
                with connection() as db:db.execute("UPDATE jobs SET state='pausing' WHERE id='job'")
                self.assertTrue(kwargs['should_stop']())
                return iter(())
            with patch.object(jobs,'connect',connection),patch.object(jobs,'adaptive_results',side_effect=wait_then_pause):
                jobs.run('job')
            with connection() as db:
                self.assertEqual(db.execute('SELECT state FROM jobs').fetchone()[0],'paused')
                self.assertEqual(db.execute('SELECT state FROM items').fetchone()[0],'pending')

    def test_backtest_rejects_another_running_analysis_before_launch(self):
        with TemporaryDirectory() as tmp:
            connection=self.setup_database(Path(tmp))
            with connection() as db:db.execute("UPDATE jobs SET state='running',pid=123 WHERE id='job'")
            with patch.object(backtests,'connect',connection),patch('workbench.server.alive',return_value=True),patch.object(backtests.subprocess,'Popen') as spawn:
                with self.assertRaisesRegex(ValueError,'分析任务'):
                    backtests.launch({'workers':'auto'})
            spawn.assert_not_called()


if __name__=='__main__':unittest.main()
