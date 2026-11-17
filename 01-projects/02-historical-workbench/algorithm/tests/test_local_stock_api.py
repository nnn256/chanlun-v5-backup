from contextlib import ExitStack
from functools import partial
from pathlib import Path
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
from http.server import ThreadingHTTPServer

from tests.test_history_archive import pair
from workbench import local_stock as local,store,server,history_archive as history
from workbench import history_export_jobs as exports,history_inventory_jobs as inventory


class LocalStockApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'project';self.root.mkdir()
        self.state=self.root/'runtime/workbench';self.state.mkdir(parents=True)
        self.db=self.state/'workbench.sqlite3';store.initialize(self.db)
        connect=partial(store.connect,self.db)
        with connect() as db:db.execute('INSERT INTO universe(symbol,code,name,exchange) VALUES(?,?,?,?)',
            ('sh600000','600000','测试本地','sh'))
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for module in (local,history,server):
            for key,value in [('ROOT',self.root),('STATE',self.state)]:
                self.stack.enter_context(patch.object(module,key,value))
        for module in (local,server):self.stack.enter_context(patch.object(module,'connect',connect))
        self.stack.enter_context(patch('workbench.reference_service.STATE',self.state))
        local.TASKS.clear();exports.JOBS.clear();inventory.JOBS.clear();history.INVENTORY_CACHE.clear()
        self.stack.enter_context(patch('chanmodel.tdx_data.TdxClient.request',side_effect=AssertionError('local path contacted network')))

    def wait(self,value):
        for _ in range(100):
            if value.get('available') or value.get('state')!='building':return value
            time.sleep(.02);value=local.local_status(value['id'])
        self.fail('local build did not finish')

    def test_missing_artifact_uses_validated_raw_cache_without_provider(self):
        pair(self.root/'runtime/workbench/jobs/old/cache',start='2026-11-02')
        pair(self.root/'runtime/workbench/jobs/new/cache',start='2026-11-09')
        first=self.wait(local.request_local('sh600000','all'))
        self.assertTrue(first['available'],first)
        self.assertNotIn('live',first['summary'])
        self.assertEqual(first['summary']['mode'],'local_cache')
        self.assertFalse(first['summary']['local_cache']['network_used'])
        self.assertEqual(first['chart']['panels'][0]['bars'][-1]['date_cn'][:10],'2026-11-11')
        self.assertEqual(first['chart']['panels'][0]['kline_audit']['state'],'raw_validated')
        self.assertIn('30m',first['summary']['local_cache']['period_errors'])
        first['chart']['panels'][0]['bars'].clear()
        cached=self.wait(local.request_local('sh600000','all'))
        self.assertEqual(len(cached['chart']['panels'][0]['bars']),3)

    def test_changed_csv_with_unchanged_metadata_fails_instead_of_showing_wrong_prices(self):
        csv,_=pair(self.root/'market_data')
        csv.write_text(csv.read_text().replace('10,11,9,10','99,100,98,99'))
        value=self.wait(local.request_local('sh600000','day'))
        self.assertFalse(value['available'])
        self.assertEqual(value['state'],'failed')
        self.assertIn('校验',value['reason'])

    def test_saved_chart_revalidates_content_even_when_size_and_mtime_are_preserved(self):
        import os
        csv,_=pair(self.root/'market_data')
        self.assertTrue(self.wait(local.request_local('sh600000','day'))['available'])
        old=csv.stat();raw=csv.read_bytes()
        changed=raw.replace(b'10,11,9,10',b'20,21,9,20')
        self.assertEqual(len(raw),len(changed));csv.write_bytes(changed)
        os.utime(csv,ns=(old.st_atime_ns,old.st_mtime_ns))
        value=self.wait(local.request_local('sh600000','day'))
        self.assertEqual(value['state'],'failed')

    def test_checkpoint_read_uses_authenticated_disk_instead_of_live_resident_cache(self):
        from workbench import incremental
        from chanmodel.reference_engine import ReferenceSession
        from tests.test_recursive_v2 import daily_series
        root=self.state/'live-sessions'
        session=ReferenceSession('day')
        for bar in daily_series(40).bars:session.append(bar)
        with patch.object(incremental,'ROOT',root),patch.object(incremental,'MEMORY',incremental.OrderedDict()):
            incremental.save('sh600000','day',incremental.LiveSession(session,40))
        with patch.object(incremental,'get',side_effect=AssertionError('local used a live resident engine')):
            value=self.wait(local.request_local('sh600000','day'))
        self.assertTrue(value['available'],value)
        self.assertEqual(len(value['chart']['panels'][0]['bars']),40)
        self.assertFalse(value['summary']['local_cache']['network_used'])

    def test_corrupt_csv_can_use_an_independently_authenticated_saved_checkpoint(self):
        from workbench import incremental
        from chanmodel.reference_engine import ReferenceSession
        from tests.test_recursive_v2 import daily_series
        csv,_=pair(self.root/'market_data');csv.write_bytes(csv.read_bytes()+b'corrupt')
        session=ReferenceSession('day')
        for bar in daily_series(40).bars:session.append(bar)
        with patch.object(incremental,'ROOT',self.state/'live-sessions'),patch.object(incremental,'MEMORY',incremental.OrderedDict()):
            incremental.save('sh600000','day',incremental.LiveSession(session,40))
        result=self.wait(local.request_local('sh600000','day'))
        self.assertTrue(result['available'],result)
        self.assertEqual(len(result['chart']['panels'][0]['bars']),40)
        self.assertEqual(result['summary']['local_cache']['sources']['day']['source_kind'],'authenticated_saved_session')

    def test_new_journal_changes_content_identity_after_sources_were_preflighted(self):
        from workbench import incremental
        from chanmodel.reference_engine import ReferenceSession
        from tests.test_recursive_v2 import daily_series
        session=ReferenceSession('day')
        for bar in daily_series(40).bars:session.append(bar)
        with patch.object(incremental,'ROOT',self.state/'live-sessions'),patch.object(incremental,'MEMORY',incremental.OrderedDict()):
            incremental.save('sh600000','day',incremental.LiveSession(session,40))
        options,_=local._sources('sh600000','day')
        before=local._content_identity('test',options)
        wal=self.state/'live-sessions/sh600000/day/session.wal'
        wal.write_bytes(b'new journal')
        self.assertNotEqual(before,local._content_identity('test',options))

    def test_no_saved_history_is_explicit_and_invalid_identifiers_rejected(self):
        value=local.request_local('sh600000','all')
        self.assertEqual(value['state'],'unavailable')
        for code in ('../secret','bad','sh600000/..'):
            with self.assertRaises(ValueError):local.request_local(code)
        with self.assertRaises(ValueError):local.local_status('../secret')

    def test_local_csv_route_and_streamed_history_zip_work_without_network(self):
        pair(self.root/'market_data')
        self.assertTrue(self.wait(local.request_local('sh600000','day'))['available'])
        http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{http.server_port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def get(path,body=None):
            req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),
                headers={'Content-Type':'application/json','Origin':base})
            with opener.open(req,timeout=5) as response:return response.status,response.headers,response.read()
        try:
            code,_,raw=get('/api/local-stock/sh600000?period=day')
            self.assertIn(code,(200,202));self.assertTrue(self.wait(json.loads(raw))['available'])
            code,headers,raw=get('/api/kline-csv/sh600000?period=day&local=1')
            self.assertEqual(code,200);self.assertIn(b'closed_at',raw)
            _,_,raw=get('/api/history/exports',{'scope':'stock','symbol':'sh600000','period':'day'})
            value=json.loads(raw)
            for _ in range(100):
                if value['state']!='building':break
                time.sleep(.02);_,_,raw=get(value['status_url']);value=json.loads(raw)
            self.assertEqual(value['state'],'ready',value)
            code,headers,raw=get(value['download_url'])
            self.assertEqual(code,200);self.assertEqual(headers['Content-Type'],'application/zip')
            self.assertEqual(len(raw),int(headers['Content-Length']));self.assertTrue(raw.startswith(b'PK'))
            self.assertNotIn('path',value)
        finally:http.shutdown();http.server_close();thread.join()


if __name__=='__main__':unittest.main()
