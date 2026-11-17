"""Unchanged closed histories must avoid rebuilding their display and audit."""
import copy
from datetime import datetime,timedelta
from dataclasses import dataclass
import hashlib
import json
import unittest
from unittest.mock import MagicMock,patch

from chanmodel.kline_audit import audit_panel
from chanmodel.model import Candle
from chanmodel.reference_engine import ReferenceSession
from chanmodel.regime_research import RegimeConfig
from chanmodel.v2.series import Series
from tests.test_recursive_v2 import daily_series
from workbench import live,research_service
from workbench.incremental import LiveSession


class LivePresentationReuseTests(unittest.TestCase):
    def setUp(self):
        live.PRESENTATION_CACHE.clear();live.CACHE.clear();research_service.CACHE.clear()
        self.bars=daily_series(97).bars
        self.record={'symbol':'sz000001','code':'000001','name':'测试','exchange':'sz'}

    def bundle(self,closed_count=96,forming_close=None,report_change=None,stamp_offset=0,source='http://one'):
        closed=self.bars[:closed_count]
        engine=ReferenceSession('day',observe=True)
        for bar in closed:engine.append(bar)
        digest=hashlib.sha256(json.dumps([live._bar_signature(bar) for bar in closed],separators=(',',':')).encode()).hexdigest()
        report=engine.snapshot('sz000001',closed[-1].closed_at,'tdx_live_ohlcv','unadjusted',digest)
        if report_change:report_change(report)
        bars=tuple(closed)
        stamp=datetime.fromisoformat(closed[-1].closed_at)+timedelta(hours=1,seconds=stamp_offset)
        if forming_close is not None:
            future=(datetime.fromisoformat(closed[-1].closed_at)+timedelta(days=1)).isoformat()
            bars+=(Candle(len(closed),forming_close,forming_close+1,forming_close-1,
                          forming_close,future,1200.0,False),)
        series=Series('sz000001','day','unadjusted',bars,'tdx_live_ohlcv',digest)
        receipt={'observed_at':stamp.isoformat(),'received_at':stamp.isoformat(),
                 'url':source+'/api/kline-all/tdx?code=sz000001&type=day',
                 'response_sha256':str(stamp_offset),'raw_path':'live/example.json.gz'}
        meta={'session':LiveSession(engine,len(closed)), 'report':report,'checkpoint_sha256':digest,
              'restored':False,'session_reused':True,'resident':True,'appended':0,'rebuilt':False,
              'total_closed':len(closed),'revision':None,'checkpoint_journal_bars':0,'checkpoint_migrated':False}
        return live.build_live(self.record,{'day':series},{'day':receipt},{'day':meta})

    def test_unchanged_closed_history_avoids_chart_audit_and_research_rebuild(self):
        first=self.bundle(stamp_offset=0)
        with patch.object(live,'make_chart',side_effect=AssertionError('recreated old chart')), \
             patch.object(live,'audit_panel',side_effect=AssertionError('reaudited old candles')), \
             patch.object(research_service,'attach_research',side_effect=AssertionError('recomputed research')):
            second=self.bundle(stamp_offset=15)
        a,b=first['chart']['panels'][0],second['chart']['panels'][0]
        self.assertEqual(a['bars'],b['bars']);self.assertEqual(a['all_signals'],b['all_signals'])
        self.assertEqual(a['presentation_sha256'],b['presentation_sha256'])
        self.assertEqual(a['kline_audit'],b['kline_audit'])
        self.assertNotEqual(a['received_at'],b['received_at'])
        self.assertEqual(second['chart']['as_of'],second['summary']['live']['observed_at'])
        self.assertTrue(b['presentation_reused'])
        self.assertEqual(b['regime_research']['runtime']['new_closed_bars'],0)

    def test_forming_changes_update_only_suffix_with_exact_audit_identity(self):
        first=self.bundle(forming_close=12.34567)
        with patch.object(live,'make_chart',side_effect=AssertionError('rebuilt closed chart')), \
             patch.object(live,'audit_panel',side_effect=AssertionError('rechecked whole history')):
            second=self.bundle(forming_close=13.12345678,stamp_offset=15)
        a,b=first['chart']['panels'][0],second['chart']['panels'][0]
        self.assertEqual(a['bars'][:-1],b['bars'][:-1])
        self.assertEqual(a['all_signals'],b['all_signals'])
        self.assertNotEqual(a['presentation_sha256'],b['presentation_sha256'])
        self.assertEqual(b['kline_audit'],audit_panel(b))
        self.assertEqual(second['summary']['price'],13.12345678)
        self.assertEqual(second['summary']['periods']['day']['bars'],97)
        self.assertTrue(b['regime_research']['provenance']['open_bar_excluded'])
        self.assertEqual(b['regime_research']['runtime']['forming_bars_excluded'],1)

    def test_closed_bar_and_source_or_name_revision_invalidate(self):
        first=self.bundle()
        with patch.object(live,'make_chart',wraps=live.make_chart) as build:
            second=self.bundle(closed_count=97)
            third=self.bundle(closed_count=97,source='http://other')
            self.record={**self.record,'name':'新证券名称'}
            renamed=self.bundle(closed_count=97,source='http://other')
        self.assertEqual(build.call_count,3)
        self.assertNotEqual(first['chart']['panels'][0]['presentation_sha256'],second['chart']['panels'][0]['presentation_sha256'])
        self.assertNotEqual(second['chart']['panels'][0]['presentation_sha256'],third['chart']['panels'][0]['presentation_sha256'])
        self.assertEqual(renamed['summary']['name'],'新证券名称')
        self.assertEqual(renamed['chart']['name'],'新证券名称')

    def test_same_bars_changed_signal_or_geometry_cannot_reuse_display_identity(self):
        self.bars=daily_series(601).bars
        first=self.bundle(closed_count=600)
        def signal_revision(report):
            if not report['signals']:raise AssertionError('fixture needs an observed signal')
            report['signals'][0]['state']='needs_review'
            report['signals'][0]['rule_audit']['missing']=['new-ledger-evidence']
        second=self.bundle(closed_count=600,report_change=signal_revision)
        third=self.bundle(closed_count=600,report_change=lambda report:report['geometry_review'].update(extra_review='changed'))
        self.assertNotEqual(first['chart']['panels'][0]['presentation_sha256'],second['chart']['panels'][0]['presentation_sha256'])
        self.assertNotEqual(first['chart']['panels'][0]['presentation_sha256'],third['chart']['panels'][0]['presentation_sha256'])
        self.assertEqual(second['chart']['panels'][0]['all_signals'][0]['state'],'needs_review')

    def test_research_configuration_changes_content_and_identity_on_same_bars(self):
        first=self.bundle()
        @dataclass(frozen=True)
        class ChangedConfig(RegimeConfig):
            drawdown_threshold:float=.13
        with patch('chanmodel.regime_research.RegimeConfig',new=ChangedConfig):
            second=self.bundle()
        a,b=first['chart']['panels'][0],second['chart']['panels'][0]
        self.assertNotEqual(a['regime_research']['config_sha256'],b['regime_research']['config_sha256'])
        self.assertNotEqual(a['presentation_sha256'],b['presentation_sha256'])

    def test_same_bars_changed_base_or_hierarchy_cannot_reuse_structure(self):
        first=self.bundle()
        second=self.bundle(report_change=lambda report:report['base']['strokes'][0].update(
            basis_at=9999,confirmed_time='different-observation-ledger'))
        third=self.bundle(report_change=lambda report:report['hierarchy']['levels'][0].update(
            presentation_revision='new-structural-first-ledger'))
        a,b,c=(item['chart']['panels'][0] for item in (first,second,third))
        self.assertNotEqual(a['presentation_sha256'],b['presentation_sha256'])
        self.assertNotEqual(a['presentation_sha256'],c['presentation_sha256'])
        self.assertEqual(b['strokes'][0]['basis_at'],9999)
        self.assertFalse(b['presentation_reused'])
        self.assertEqual(c['structure_layers'][0]['presentation_revision'],'new-structural-first-ledger')

    def test_returned_mutations_do_not_poison_cached_closed_template(self):
        first=self.bundle(forming_close=12)
        first['chart']['panels'][0]['bars'][0]['close']=999999
        first['chart']['panels'][0]['bars'].clear()
        first['chart']['panels'][0]['signal_chart']['objects'].clear()
        first['evidence']['reference_reports'].clear()
        second=self.bundle(forming_close=13,stamp_offset=15)
        self.assertEqual(len(second['chart']['panels'][0]['bars']),97)
        self.assertNotEqual(second['chart']['panels'][0]['bars'][0]['close'],999999)
        self.assertEqual(second['chart']['panels'][0]['kline_audit'],audit_panel(second['chart']['panels'][0]))
        self.assertIn('day',second['evidence']['reference_reports'])

    def test_template_cache_obeys_encoded_byte_budget_and_skips_oversized_entries(self):
        with patch.object(live,'PRESENTATION_MAX_BYTES',100000), \
             patch.object(live,'PRESENTATION_MAX_ENTRY_BYTES',90000):
            for i in range(8):
                self.record={**self.record,'name':'证券'+str(i)}
                self.bundle()
                self.assertLessEqual(sum(len(item['raw']) for item in live.PRESENTATION_CACHE.values()),100000)
        live.PRESENTATION_CACHE.clear()
        with patch.object(live,'PRESENTATION_MAX_ENTRY_BYTES',1):self.bundle()
        self.assertFalse(live.PRESENTATION_CACHE)

    def test_response_cache_full_and_compact_results_are_isolated(self):
        connection=MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchone.return_value=None
        original={'available':True,'summary':{'symbol':'sz000001'},
                  'chart':{'panels':[{'period':'day','bars':[{'close':10}]}]},
                  'evidence':{'reference_reports':{'day':{'signals':['proof']}}}}
        with patch.object(live,'connect',return_value=connection), \
             patch.object(live,'_period_inputs',return_value=({'day':object()},{},{},{})) as acquire, \
             patch.object(live,'build_live',return_value=copy.deepcopy(original)), \
             patch.object(live.TdxClient,'__init__',return_value=None), \
             patch.object(live.TdxClient,'base_url','http://fixture',create=True):
            compact=live.live_stock('sz000001','day',full=False)
            self.assertNotIn('evidence',compact)
            compact['chart']['panels'].clear()
            exported=live.live_stock('sz000001','day',full=True)
            exported['evidence']['reference_reports'].clear()
            self.assertEqual(len(exported['chart']['panels']),1)
            again=live.live_stock('sz000001','day',full=True)
        self.assertEqual(acquire.call_count,1)
        self.assertEqual(again['evidence']['reference_reports']['day']['signals'],['proof'])
        self.assertTrue(all(isinstance(entry[1],bytes) for entry in live.CACHE.values()))

    def test_response_cache_budget_removes_replaced_and_oversized_entries(self):
        connection=MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchone.return_value=None
        def output(record,*args):
            return {'available':True,'summary':{'symbol':record['symbol']},'chart':{},'evidence':{'body':'x'*150}}
        with patch.object(live,'connect',return_value=connection), \
             patch.object(live,'_period_inputs',return_value=({'day':object()},{},{},{})), \
             patch.object(live,'build_live',side_effect=output), \
             patch.object(live,'RESPONSE_MAX_BYTES',500),patch.object(live,'RESPONSE_MAX_ENTRY_BYTES',400):
            for code in ('sz000001','sh600000','bj920000'):
                live.live_stock(code,'day',fresh=True)
                self.assertLessEqual(sum(len(entry[1]) for entry in live.CACHE.values()),500)
            self.assertTrue(live.CACHE)
            with patch.object(live,'RESPONSE_MAX_ENTRY_BYTES',1):
                live.live_stock('bj920000','day',fresh=True)
            self.assertNotIn('bj920000',[identity[0] for identity in live.CACHE])

    def test_all_keeps_three_standard_periods_and_one_minute_is_explicit(self):
        connection=MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchone.return_value=None
        with patch.object(live,'connect',return_value=connection), \
             patch.object(live,'_period_inputs',return_value=({'day':object()},{},{},{})) as acquire, \
             patch.object(live,'build_live',return_value={'summary':{},'chart':{},'evidence':{}}):
            live.live_stock('sz000001','all',fresh=True)
            live.live_stock('sz000001','1m',fresh=True)
        self.assertEqual(acquire.call_args_list[0].args[1],('day','30m','5m'))
        self.assertEqual(acquire.call_args_list[1].args[1],('day','1m'))


if __name__=='__main__':unittest.main()
