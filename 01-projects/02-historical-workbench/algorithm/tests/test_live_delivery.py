import copy
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import patch
import urllib.request

from workbench.live_delivery import snapshot_response
from workbench.server import Handler


def response():
    return {'available':True,'summary':{'symbol':'bj920000','live':{'received_at':'current'}},
        'chart':{'as_of':'current','panels':[{'period':'day','presentation_sha256':'a'*64,
            'bars':[{'source_index':i,'close':10} for i in range(1000)],'all_signals':[{'id':'one'}],
            'received_at':'current','source_receipt':{'hash':'new-response'},
            'regime_research':{'runtime':{'new_closed_bars':0},'provenance':{'source':'raw'}}}]},
        'evidence':{'reference_reports':{'day':'complete-proof'}}}


class LiveDeliveryTests(unittest.TestCase):
    def test_matching_full_chart_gets_only_fresh_metadata_and_preserves_source_object(self):
        value=response();before=copy.deepcopy(value)
        first=snapshot_response(value);token=first['snapshot_id']
        value['summary']['live']['received_at']='newer'
        value['chart']['panels'][0]['source_receipt']={'hash':'newer-response'}
        reply=snapshot_response(value,token)
        self.assertTrue(reply['unchanged'])
        self.assertNotIn('panels',reply['chart_metadata'])
        self.assertNotIn('bars',reply['panel_updates'][0])
        self.assertNotIn('evidence',reply)
        self.assertEqual(reply['summary']['live']['received_at'],'newer')
        self.assertEqual(reply['panel_updates'][0]['source_receipt']['hash'],'newer-response')
        self.assertEqual(reply['panel_updates'][0]['research_runtime'],{'new_closed_bars':0})
        self.assertEqual(value['chart']['panels'][0]['bars'],before['chart']['panels'][0]['bars'])
        self.assertLess(len(json.dumps(reply)),len(json.dumps(first))/10)

    def test_forming_or_signal_identity_change_and_period_set_change_require_complete_reply(self):
        value=response();token=snapshot_response(value)['snapshot_id']
        for changed in ('b','c','d'):
            value['chart']['panels'][0]['presentation_sha256']=changed*64
            fresh=snapshot_response(value,token)
            self.assertNotIn('unchanged',fresh)
            self.assertIn('bars',fresh['chart']['panels'][0])
        value=response();value['chart']['panels'].append({'period':'5m','presentation_sha256':'b'*64,'bars':[1]})
        self.assertNotIn('unchanged',snapshot_response(value,token))

    def test_full_export_always_contains_complete_evidence_even_with_matching_token(self):
        value=response();token=snapshot_response(value)['snapshot_id']
        exported=snapshot_response(value,token,full=True)
        self.assertNotIn('unchanged',exported)
        self.assertEqual(exported['evidence'],value['evidence'])
        self.assertEqual(exported['chart']['panels'][0]['bars'],value['chart']['panels'][0]['bars'])

    def test_missing_or_invalid_identity_never_claims_unchanged(self):
        for invalid in (None,'short','a'*63,'z'*64):
            value=response();value['chart']['panels'][0]['presentation_sha256']=invalid
            self.assertIs(snapshot_response(value,'known'),value)
            self.assertNotIn('snapshot_id',value)
        value=response();value['chart']['panels'].append(copy.deepcopy(value['chart']['panels'][0]))
        self.assertIs(snapshot_response(value,'known'),value)

    def test_another_symbol_token_cannot_validate_identical_panel_hashes(self):
        value=response();token=snapshot_response(value)['snapshot_id']
        value['summary']['symbol']='sz000001'
        self.assertNotIn('unchanged',snapshot_response(value,token))

    def test_real_handler_refreshes_source_before_returning_metadata_and_never_truncates_exports(self):
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base=f'http://127.0.0.1:{http.server_port}/api/live-stock/bj920000?period=day'
        def get(url):
            with opener.open(url,timeout=4) as result:return json.load(result)
        try:
            with patch('workbench.services.ensure_tdx') as ensure, \
                 patch('workbench.live.live_stock',side_effect=lambda *args:response()) as acquire:
                first=get(base)
                second=get(base+'&known_snapshot='+first['snapshot_id'])
                exported=get(base+'&full=1&known_snapshot='+first['snapshot_id'])
            self.assertEqual(acquire.call_count,3)
            self.assertEqual(ensure.call_count,3)
            self.assertTrue(second['unchanged'])
            self.assertIn('reference_reports',exported['evidence'])
        finally:
            http.shutdown();http.server_close();thread.join()


if __name__=='__main__':unittest.main()
