import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from workbench import research_context
from workbench.research_context import normalize_flow


class ResearchContextTests(unittest.TestCase):
    def setUp(self):
        research_context.CACHE.clear()
    def payload(self, rows=None):
        return {'rc': 0, 'data': {'code': '600000', 'market': 1, 'klines': rows or [
            '2026-11-11,100,-40,-60,50,50,1,-.4,-.6,.5,.5,10,2',
            '2026-11-12,200,-80,-120,100,100,2,-.8,-1.2,1,1,11,10']}}

    def test_acquired_vintage_cannot_be_available_before_first_local_observation(self):
        rows = normalize_flow(self.payload(), 'sh600000', '2026-11-13T20:00:00+08:00')
        self.assertEqual(rows[0]['available_at'], '2026-11-13T20:00:00+08:00')
        self.assertEqual(rows[-1]['net_flow'], 200)
        self.assertIn('unverified', rows[0]['availability_semantics'])

    def test_wrong_security_future_duplicate_and_nonfinite_fail(self):
        with self.assertRaises(ValueError):
            normalize_flow(self.payload(), 'sz600000', '2026-11-13T20:00:00+08:00')
        for rows in [
            ['2026-11-14,100,-40,-60,50,50,1,-.4,-.6,.5,.5,10,2'],
            ['2026-11-12,100,-40,-60,50,50,1,-.4,-.6,.5,.5,10,2'] * 2,
            ['2026-11-12,nan,-40,-60,50,50,1,-.4,-.6,.5,.5,10,2']]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                normalize_flow(self.payload(rows), 'sh600000', '2026-11-13T20:00:00+08:00')

    def test_malformed_payload_rows_and_china_midnight(self):
        for payload in [[],self.payload([None]),self.payload([{}])]:
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                normalize_flow(payload,'sh600000','2026-11-13T20:00:00+08:00')
        payload=self.payload(['2026-11-13,100,-40,-60,50,50,1,-.4,-.6,.5,.5,10,2'])
        rows=normalize_flow(payload,'sh600000','2026-11-12T22:00:00+00:00')
        self.assertEqual(rows[0]['date'],'2026-11-13')

    def test_unsupported_bj_flow_is_explicit_without_network(self):
        with patch.object(research_context.urllib.request,'urlopen',side_effect=AssertionError('unexpected request')):
            result=research_context.fund_flow('bj920010',refresh=True)
        self.assertEqual(result['state'],'unavailable')
        self.assertEqual(result['rows'],[])
        self.assertFalse(result['execution_allowed'])

    def test_each_capture_is_archived_without_backdating_historical_rows(self):
        raw=json.dumps(self.payload()).encode('utf-8')
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):return raw
        first='2026-11-13T20:00:00+08:00'
        second='2026-11-13T20:05:00+08:00'
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(research_context,'STATE',Path(tmp)), \
             patch.object(research_context.urllib.request,'urlopen',side_effect=lambda *args,**kwargs:Response()), \
             patch.object(research_context,'now_iso',side_effect=[first,second]):
            before=research_context.fund_flow('sh600000',refresh=True)
            after=research_context.fund_flow('sh600000',refresh=True)
            receipts=sorted((Path(tmp)/'research-context/sh600000').glob('*.receipt.json'))
            self.assertEqual(len(receipts),2)
            self.assertEqual(before['source_response_sha256'],after['source_response_sha256'])
            self.assertEqual(before['rows'][0]['available_at'],first)
            self.assertEqual(after['rows'][0]['available_at'],second)
            self.assertFalse(before['pit_history_proven'])
            self.assertFalse(after['pit_history_proven'])
            self.assertEqual(before['rows'][0]['main_net_flow'],before['rows'][0]['net_flow'])


if __name__ == '__main__':
    unittest.main()
