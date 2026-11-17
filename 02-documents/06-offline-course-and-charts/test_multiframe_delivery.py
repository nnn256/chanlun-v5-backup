"""Contract, six-class, witnessed lower-reversal and delivery CLI tests."""
from dataclasses import replace
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'engine'))

from run_multiframe import analyze_supplied, make_demo_series, write_csv
from chanmodel.model import Candle
from chanmodel.v2.series import Series, CN, derive_series, validate_multiframe, validate_series, session_closes
from chanmodel.v2.recursive import centers_from_units, partition_types
from chanmodel.v2.divergence import compare_divergences, make_signals
from chanmodel.v2.engine import structural_confirmations, trigger_after


def completed_units(vertices, rank=0):
    """Named structural fixtures, not fabricated OHLC trading observations."""
    result=[]
    for i,(a,b) in enumerate(zip(vertices,vertices[1:])):
        result.append({'id':f'u{rank}:{i*10}:{(i+1)*10}','rank':rank,
                       'kind':'base_segment' if rank==0 else 'consolidation',
                       'direction':'up' if b>a else 'down','state':'complete',
                       'start':i*10,'end':(i+1)*10,'start_price':a,'end_price':b,
                       'low':min(a,b),'high':max(a,b),'completed_at':(i+1)*10+2,
                       'available_at':(i+1)*10+2,'components':[f's{i}'],
                       'center_ids':[],
                       'completion':{'rule':'base_segment_confirmed','available_at':(i+1)*10+2}})
    return result


def five_minute_series(days=10):
    current=date(2026,1,5);bars=[];n=0
    while n<days:
        if current.weekday()<5:
            for instant in session_closes(current,'5m'):
                bars.append(Candle(len(bars),100,100.5,99.5,100,instant.isoformat(),100,True))
            n+=1
        current+=timedelta(days=1)
    return Series('sz000001','5m','unadjusted',tuple(bars),'synthetic_fixture')


class MultiframeDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.series=make_demo_series(8)
        cls.cutoff=cls.series['1m'].bars[-1].closed_at
        cls.report=analyze_supplied(cls.series,('30m','5m','1m'),cls.cutoff)

    def test_exact_ohlcv_aggregation_is_verified(self):
        self.assertEqual(self.report['state'],'calculated')
        self.assertEqual(self.report['data_contract']['state'],'verified')
        self.assertEqual([len(self.series[k].bars) for k in ('30m','5m','1m')],[64,384,1920])
        for pair in self.report['data_contract']['pairs']:
            self.assertGreater(pair['matched_parent_bars'],0)
            self.assertEqual(pair['mismatched_parent_bars'],0)
            self.assertTrue(all(x['volume_difference']==0 for x in pair['comparisons']))

    def test_full_study_reports_have_native_structure_layers(self):
        for report in self.report['levels'].values():
            for key in ('feature_sequences','center_evolution','decompositions',
                        'divergence_comparisons','center_monitors','construction_phases'):
                self.assertIn(key,report)
            self.assertEqual(report['certificate_audit']['state'],'passed')
        self.assertIn('small_to_large_audit',self.report['study_links'])
        self.assertIn('interval_nesting',self.report['study_links'])
        self.assertFalse(self.report['execution_allowed'])

    def test_future_data_are_cut_off_before_analysis(self):
        cut=self.series['1m'].bars[959].closed_at
        result=analyze_supplied(self.series,('30m','5m','1m'),cut)
        for period,report in result['levels'].items():
            self.assertLessEqual(datetime.fromisoformat(report['input_audit']['last_close']),datetime.fromisoformat(cut))
            self.assertEqual(report['input_audit']['bars_used'],len(self.series[period].prefix(cut).bars))

    def test_wrong_parent_ohlc_blocks_all_trigger_output(self):
        bad=dict(self.series)
        parent=bad['30m'];b=parent.bars[0]
        bad['30m']=replace(parent,bars=(replace(b,high=b.high+3),)+parent.bars[1:])
        result=analyze_supplied(bad,('30m','5m','1m'),self.cutoff)
        self.assertEqual(result['state'],'blocked_data_contract')
        self.assertEqual(result['signals'],[])
        self.assertEqual(result['levels'],{})

    def test_missing_volume_is_not_silently_zero(self):
        bad=dict(self.series);parent=bad['30m']
        bad['30m']=replace(parent,bars=tuple(replace(b,volume=None) for b in parent.bars))
        result=analyze_supplied(bad,('30m','5m','1m'),self.cutoff)
        self.assertEqual(result['state'],'blocked_data_contract')
        self.assertTrue(any(x['state']=='missing_volume' for x in result['data_contract']['pairs'][0]['comparisons']))

    def test_identical_period_data_cannot_be_relabelled(self):
        fake=replace(self.series['30m'],period='5m')
        with self.assertRaises(ValueError):
            validate_series(fake,self.cutoff)

    def test_fixed_profile_rejects_inconsistent_price_tolerance(self):
        with self.assertRaises(ValueError):
            analyze_supplied(self.series,('30m','5m','1m'),self.cutoff,price_tolerance=1.0)

    def test_security_and_adjustment_mismatch_are_rejected(self):
        for update in ({'symbol':'sh600000'},{'adjustment':'qfq'}):
            bad={**self.series,'5m':replace(self.series['5m'],**update)}
            with self.assertRaises(ValueError):
                validate_multiframe(bad,('30m','5m','1m'),self.cutoff)

    def test_all_six_structural_signal_classes_have_positive_paths(self):
        kinds=set()
        # Synthetic structure fixtures deliberately create all six branches;
        # this does not claim they occur in the independent OHLC example.
        vertices=[30,20,28,21,26,14,18,12,17,10,13,11]
        for mirror in (False,True):
            source=completed_units([40-v for v in vertices] if mirror else vertices)
            bars=[Candle(i,20,40,0,20) for i in range(125)]
            sign=1 if mirror else -1
            hist=[{'histogram':sign*(2 if 40<=i<=50 else .4 if 80<=i<=90 else .01),
                   'dif':10 if i<51 else 0,'dea':0} for i in range(125)]
            centers=centers_from_units(source,1,125)
            comps=compare_divergences(source,centers,bars,hist,1,125)
            signals=make_signals(source,centers,comps,bars,1,hist,second_policy='conservative')
            kinds.update(point['class'] for point in signals)
        self.assertEqual(kinds,{'first_buy','second_buy','third_buy','first_sell','second_sell','third_sell'})

    def test_lower_opposite_center_break_then_new_fine_stroke_is_real_gate(self):
        fine=five_minute_series(10);cut=fine.bars[-1].closed_at
        confirm=derive_series(fine,'30m',cut);trade=derive_series(confirm,'day',cut)
        lower=completed_units([30,20,25,18,28,27])
        for unit in lower:
            for key in ('start','end','completed_at','available_at'):unit[key]+=8
            unit['id']=f"u0:{unit['start']}:{unit['end']}"
        view=partition_types(lower,1,70)
        self.assertTrue(view['completed_types'])
        report={'hierarchy':{'base_units':lower,'levels':[{'centers':view['centers'],
                'completed_types':[],'movement_views':view}]}}
        parent={'side':'buy','terminal_range':[0,4],'anchor':4,'price':18,'invalidation':17}
        proof=structural_confirmations(parent,trade,confirm,report,cut)
        self.assertTrue(proof)
        at=datetime.fromisoformat(proof[0]['available_time'])
        index=next(i for i,b in enumerate(fine.bars) if datetime.fromisoformat(b.closed_at)>at)
        trigger_report={'base':{'strokes':[{'id':'new-up','direction':'up','start':index,
                        'end':index+4,'basis_at':index+8,'state':'confirmed',
                        'confirmation_basis':'next-down','end_price':101}]}}
        trigger=trigger_after(parent,proof[0],fine,trigger_report,cut,
                              datetime.fromisoformat(trade.bars[4].closed_at))
        self.assertIsNotNone(trigger)
        self.assertGreater(datetime.fromisoformat(trigger['available_time']),at)
        self.assertFalse(structural_confirmations({**parent,'price':19},trade,confirm,report,cut))

    def test_future_or_unconfirmed_fine_stroke_is_not_a_trigger(self):
        fine=five_minute_series(1);parent={'side':'buy','invalidation':90}
        proof={'available_time':fine.bars[10].closed_at,'return_end_time':fine.bars[8].closed_at}
        def stroke(start,end,basis,state='confirmed'):
            return {'id':str(start),'start':start,'end':end,'basis_at':basis,'direction':'up',
                    'state':state,'confirmation_basis':'next-down','end_price':101}
        report={'base':{'strokes':[stroke(1,4,6),stroke(8,13,15,'provisional'),stroke(10,17,20)]}}
        result=trigger_after(parent,proof,fine,report,fine.bars[18].closed_at,
                             datetime.fromisoformat(fine.bars[11].closed_at))
        self.assertIsNone(result)

    def test_no_positive_trigger_is_invented_for_sample_without_parent_points(self):
        native=self.report['levels']['30m']['signals']
        self.assertEqual(len(self.report['signals']),len(native))
        if not native:
            self.assertEqual(self.report['signals'],[])

    def test_cli_accepts_independently_named_actual_csv_periods(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);args=[]
            for role,period in (('trade','30m'),('confirm','5m'),('trigger','1m')):
                path=root/f'{period}.csv';write_csv(self.series[period],path)
                args.extend([f'--{role}',f'{period}={path}'])
            output=root/'result.json'
            process=subprocess.run([sys.executable,str(HERE/'run_multiframe.py'),*args,
                                    '--symbol','sz000001','--cutoff',self.cutoff,'--output',str(output)],
                                   capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(process.returncode,0,process.stderr)
            result=json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result['data_contract']['state'],'verified')
            self.assertFalse(result['synthetic'])
            self.assertEqual(result['data_origin'],'caller_supplied_timestamped_OHLCV')


if __name__=='__main__':
    unittest.main()
