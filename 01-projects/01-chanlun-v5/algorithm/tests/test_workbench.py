import functools
import gzip
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

from workbench import store, server, compute


class WorkbenchContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'test.sqlite3'
        store.initialize(self.db)
        self.connection=functools.partial(store.connect,self.db)
        self.patcher=patch.object(server,'connect',self.connection);self.patcher.start()
        with self.connection() as db:
            db.executemany('INSERT INTO universe(symbol,code,name,exchange,active) VALUES(?,?,?,?,?)',[
                ('sh600699','600699','均胜电子','sh',1),('sz301079','301079','邵阳液压','sz',1),('sh600000','600000','退出测试池','sh',0)])

    def tearDown(self):
        self.patcher.stop();self.temp.cleanup()

    def request(self,method,path):
        http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            request=urllib.request.Request(f'http://127.0.0.1:{http.server_port}{path}',method=method)
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read())
        finally:
            http.shutdown();http.server_close();thread.join()

    def test_old_market_date_cannot_replace_new_result(self):
        with self.connection() as db:
            store.publish_result(db,'sh600699','multi','new','2026-11-07',json.dumps({'last_date':'2026-11-06'}),'new.gz')
            published=store.publish_result(db,'sh600699','multi','old','2026-11-08',json.dumps({'last_date':'2026-11-05'}),'old.gz')
            self.assertFalse(published)
            self.assertEqual(db.execute('SELECT artifact FROM results').fetchone()[0],'new.gz')

    def test_full_market_only_active_symbols(self):
        result=server.create_job({'scope':'all','mode':'day','workers':2})
        self.assertEqual(result['total'],2)
        with self.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM items').fetchone()[0],2)

    def test_jobs_default_to_automatic_cpu_memory_scheduling(self):
        result=server.create_job({'symbols':['600699'],'mode':'day'})
        with self.connection() as db:
            settings=json.loads(db.execute('SELECT settings FROM jobs WHERE id=?',(result['id'],)).fetchone()[0])
        self.assertEqual(settings['workers'],'auto')
        self.assertEqual(settings['resource_policy'],'cpu_memory_adaptive_v1')

    def test_resources_endpoint_reports_real_backend_without_enabling_gpu(self):
        response=self.request('GET','/api/resources')
        self.assertEqual(response['execution_backend'],'cpu_multiprocess')
        self.assertIn('plan',response)
        self.assertIn('memory',response)
        self.assertFalse(response['gpu']['supported'])

    def test_default_market_page_uses_page_scoped_result_lookup(self):
        for symbol,job,mode,date,price in [('sh600699','new','day','2026-11-12',20.0),
                                           ('sh600699','old','full','2026-11-11',19.0)]:
            summary={'last_date':date,'price':price,'change_pct':1.2,'mode':mode,
                     'algorithm':'V4','state':'success','triggered':0,'active_candidates':0,'periods':{}}
            with self.connection() as db:
                db.execute('INSERT OR REPLACE INTO results VALUES(?,?,?,?,?,?)',
                    (symbol,mode,job,date,json.dumps(summary),job+'.gz'))
        with patch.object(server,'PICK',side_effect=AssertionError('default list ranked every historical result')):
            result=server.market({'q':['600699'],'limit':['5'],'offset':['0'],'filter':[''],'job':[''],'exchange':['sh']})
        self.assertEqual(result['total'],1)
        self.assertEqual(result['rows'][0]['job_id'],'new')
        self.assertEqual(result['rows'][0]['price'],20.0)
        self.assertEqual(result['rows'][0]['item_state'],'success')

    def test_full_history_job_has_bounded_fetch_and_interactive_lane(self):
        result=server.create_job({'symbols':['600699'],'mode':'full','workers':12,'refresh':False})
        with self.connection() as db:
            settings=json.loads(db.execute('SELECT settings FROM jobs WHERE id=?',(result['id'],)).fetchone()[0])
        self.assertTrue(settings['refresh'])
        self.assertTrue(settings['interactive'])
        self.assertEqual(settings['workers'],3)

    def test_server_health_exposes_v5_profile_release_and_database(self):
        response = self.request('GET', '/api/health')
        self.assertEqual(response['release'], 'V5')
        self.assertEqual(response['workbench_profile'], 'course_feature_sequence_recursive_v2')
        self.assertEqual(Path(response['database']), store.DB)

    def test_full_history_result_wins_same_market_date(self):
        with self.connection() as db:
            store.publish_result(db,'sh600699','full','full','2026-11-07',json.dumps({'last_date':'2026-11-06','price':20.74,'mode':'full'}),'full.gz')
            store.publish_result(db,'sh600699','multi','multi','2026-11-08',json.dumps({'last_date':'2026-11-06','price':20.74,'mode':'multi'}),'multi.gz')
        self.assertEqual(server.market({'q':['600699']})['rows'][0]['mode'],'full')

    def test_duplicate_and_bad_input_rejected(self):
        body={'symbols':['600699'],'mode':'day'}
        server.create_job(body)
        with self.assertRaisesRegex(ValueError,'已经'):server.create_job(body)
        for values in ({'symbols':['../600699']},{'symbols':['600699'],'workers':0},
                       {'symbols':['600699'],'volume_tolerance':-1},{'symbols':['600699'],'cutoff':'2026-10-01'}):
            with self.assertRaises(ValueError):server.create_job(values)

    def test_pause_resume_and_retry_preserve_success(self):
        job=server.create_job({'scope':'all','mode':'day'})['id']
        self.assertEqual(server.control_job(job,'pause')['state'],'paused')
        self.assertEqual(server.control_job(job,'resume')['state'],'queued')
        with self.connection() as db:
            db.execute("UPDATE jobs SET state='completed' WHERE id=?",(job,))
            db.execute("UPDATE items SET state='success' WHERE symbol='sh600699'")
            db.execute("UPDATE items SET state='failed',error='sample failure' WHERE symbol='sz301079'")
        server.control_job(job,'retry')
        with self.connection() as db:
            states=dict(db.execute('SELECT symbol,state FROM items'))
        self.assertEqual(states,{'sh600699':'success','sz301079':'pending'})

    def test_job_filter_does_not_use_other_run_result(self):
        job=server.create_job({'symbols':['600699'],'mode':'day'})['id']
        with self.connection() as db:
            store.publish_result(db,'sh600699','multi','different','2026-11-07',json.dumps({'last_date':'2026-11-06','price':20.74,'mode':'multi'}),'other.gz')
        result=server.market({'job':[job]})
        self.assertEqual(result['total'],1)
        self.assertIsNone(result['rows'][0]['price'])
        self.assertEqual(result['rows'][0]['item_state'],'pending')

    def test_cross_origin_mutation_and_bad_host_rejected(self):
        http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{http.server_port}'
        try:
            req=urllib.request.Request(url+'/api/jobs',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://foreign.example'})
            with self.assertRaises(urllib.error.HTTPError) as cm:urllib.request.urlopen(req)
            self.assertEqual(cm.exception.code,400)
            req=urllib.request.Request(url+'/api/overview',headers={'Host':'foreign.example'})
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(req)
        finally:http.shutdown();http.server_close();thread.join()

    def test_terminal_layout_stylesheet_is_served_from_the_workbench_web_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            web=Path(tmp);(web/'terminal-layout.css').write_text('.signal-rail{display:flex}',encoding='utf-8')
            with patch.object(server,'WEB',web):
                http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
                thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{http.server_port}/terminal-layout.css') as response:
                        self.assertIn('text/css',response.headers.get('Content-Type',''))
                        self.assertEqual(response.read(),b'.signal-rail{display:flex}')
                finally:
                    http.shutdown();http.server_close();thread.join()

    def test_missing_source_cannot_report_success(self):
        with patch.object(compute,'STATE',Path(self.temp.name)),patch.object(compute,'load_cache_series',side_effect=FileNotFoundError('missing real history')):
            result=compute.process_stock({'symbol':'sh600699','name':'均胜电子','code':'600699','exchange':'sh'},
                {'mode':'day','cutoff':'2026-11-06T15:00:00+08:00','refresh':False,'volume_tolerance':100},'test')
        self.assertEqual(result['state'],'failed')
        self.assertIn('missing real history',result['error'])


if __name__=='__main__':unittest.main()
