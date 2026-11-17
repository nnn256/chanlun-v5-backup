from datetime import datetime,timedelta
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from chanmodel.model import Candle
from chanmodel.v2.series import Series,CN
from chanmodel.v2.engine import analyze
from workbench.compute import make_chart
from workbench.history import normalize,five_day,calendar_analysis,build_panel,timeshare_panel,bucket_end,load_capture
from workbench import full_compute


class FullHistoryTests(unittest.TestCase):
    def daily(self,count=400):
        start=datetime(2021,2,26,15,tzinfo=CN)
        return tuple(Candle(i,10+i%6,12+i%6,9+i%6,11+i%6,(start+timedelta(days=i)).isoformat(),1000,True) for i in range(count))

    def test_chart_loads_early_history_and_all_overlays(self):
        bars=self.daily();series=Series('sz300949','day','unadjusted',bars,'fixture');cutoff=bars[-1].closed_at
        report=analyze(series,cutoff)
        chart,summary=make_chart({'symbol':'sz300949','code':'300949','name':'test','exchange':'sz'},{'day':series},{'day':report},cutoff)
        panel=chart['panels'][0]
        self.assertEqual(len(panel['bars']),400)
        self.assertEqual(panel['bars'][0]['date_cn'],'2021-02-26 15:00')
        self.assertEqual(panel['visible_start'],0)
        self.assertEqual(panel['strokes'],report['base']['strokes'])

    def test_calendar_forming_candle_excluded_and_week_closed_friday(self):
        def row(date):return {'Time':date+'T15:00:00+08:00','Open':10000,'High':12000,'Low':9000,'Close':11000,'Volume':10}
        month=normalize({'list':[row('2026-10-30'),row('2026-11-06')]},'month','2026-11-08T00:00:00+08:00')
        self.assertEqual([b.closed for b in month],[True,False])
        report=calendar_analysis('sz300949','month',month,'2026-11-08T00:00:00+08:00','hash')
        self.assertEqual(report['input_audit']['bars_used'],1)
        week=normalize({'list':[row('2026-11-06')]},'week','2026-11-08T00:00:00+08:00')
        self.assertTrue(week[0].closed)

    def test_cutoff_does_not_leak_future_prices(self):
        rows=[{'Time':d+'T15:00:00+08:00','Open':10000,'High':12000,'Low':9000,'Close':11000,'Volume':10} for d in ['2021-02-26','2026-11-06']]
        bars=normalize({'list':rows},'day','2021-03-01T15:00:00+08:00')
        self.assertEqual(len(bars),1)

    def test_five_day_group_not_calendar_week(self):
        bars=self.daily(11);groups=five_day(bars)
        self.assertEqual(len(groups),3)
        self.assertEqual(groups[0].open,bars[0].open)
        self.assertEqual(groups[0].close,bars[4].close)
        self.assertEqual(groups[0].volume,5000)
        self.assertFalse(groups[-1].closed)

    def test_invalid_native_minutes_rejected(self):
        row={'Time':'2026-11-06T12:05:00+08:00','Open':10000,'High':12000,'Low':9000,'Close':11000,'Volume':10}
        with self.assertRaisesRegex(ValueError,'off-grid'):normalize({'list':[row]},'5m','2026-11-08T00:00:00+08:00')

    def test_changed_capture_is_rejected_before_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'raw').mkdir();(root/'receipts').mkdir()
            (root/'raw/day.json.gz').write_bytes(gzip.compress(b'{"data":{"list":[]}}'))
            (root/'receipts/day.json').write_text(json.dumps({'response_sha256':'wrong'}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):load_capture(root,'sz300949','2026-11-08T00:00:00+08:00')

    def test_timeshare_is_line_never_fabricated_ohlc(self):
        rows=[]
        for i in range(240):
            minute=571+i if i<120 else 781+i-120
            rows.append({'Time':f'{minute//60:02}:{minute%60:02}','Price':10000,'Number':2})
        panel=timeshare_panel({'date':'20210226','Count':240,'List':rows},'20210226')
        self.assertEqual(panel['points'][0]['value'],10)
        self.assertNotIn('open',panel['points'][0])
        self.assertEqual(panel['points'][-1]['date_cn'],'2021-02-26 15:00')
        rows[0]['Time']='09:25'
        with self.assertRaisesRegex(ValueError,'off grid'):timeshare_panel({'date':'20210226','Count':240,'List':rows},'20210226')

    def timeshare_capture(self,folder):
        folder.mkdir(parents=True)
        (folder/'raw').mkdir()
        (folder/'timeshare').mkdir()
        day='20261113'
        rows=[]
        for i in range(240):
            minute=571+i if i<120 else 781+i-120
            rows.append({'Time':f'{minute//60:02}:{minute%60:02}','Price':10000,'Number':2})
        (folder/'timeshare'/f'{day}.json.gz').write_bytes(gzip.compress(json.dumps(
            {'data':{'date':day,'Count':240,'List':rows}}
        ).encode()))
        acquisition={'requested_at':'2026-11-14T00:00:00+08:00','periods':{},
                     'time_share_history':{'dates':[{'date':day,'status':'received'}]}}
        (folder/'acquisition.json').write_text(json.dumps(acquisition),encoding='utf-8')
        raw={'data':{'list':[{'Time':'2026-11-13T15:00:00+08:00',
                             'Open':10000,'High':12000,'Low':9000,'Close':11000,'Volume':10}]}}
        (folder/'raw/day.json.gz').write_bytes(gzip.compress(json.dumps(raw).encode()))
        return day

    def test_full_bundle_outside_project_uses_state_relative_timeshare(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);project=root/'algorithm';project.mkdir();state=root/'workbench-data-8895'
            folder=state/'jobs'/'fixture'/'history'/'sz300949'
            self.timeshare_capture(folder)
            with patch.object(full_compute,'ROOT',project),patch.object(full_compute,'STATE',state):
                bundle=full_compute.bundle_capture(
                    {'symbol':'sz300949','code':'300949','name':'fixture','exchange':'sz'},
                    folder,'2026-11-14T00:00:00+08:00')
                self.assertEqual(bundle['history_root_base'],'state')
                self.assertEqual(bundle['history_root'],'jobs/fixture/history/sz300949')
                view=full_compute.history_view(bundle,'timeshare','2026-11-13')
            self.assertTrue(view['available'])
            self.assertEqual(len(view['panel']['points']),240)

    def test_legacy_project_history_root_remains_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);project=root/'algorithm';folder=project/'runs'/'legacy-history'
            self.timeshare_capture(folder)
            bundle={'history_root':'runs/legacy-history',
                    'summary':{'as_of':'2026-11-14T00:00:00+08:00'}}
            with patch.object(full_compute,'ROOT',project),patch.object(full_compute,'STATE',root/'state'):
                view=full_compute.history_view(bundle,'five_days')
            self.assertTrue(view['available'])
            self.assertEqual(len(view['panel']['points']),240)

    def test_history_root_cannot_escape_declared_project_or_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);project=root/'algorithm';state=root/'state'
            with patch.object(full_compute,'ROOT',project),patch.object(full_compute,'STATE',state):
                for base in ('state','project'):
                    with self.assertRaisesRegex(ValueError,'invalid history root'):
                        full_compute.history_view({'history_root':'../other',
                            'history_root_base':base,'summary':{'as_of':'2026-11-14'}},'timeshare')
                with self.assertRaisesRegex(ValueError,'invalid history root base'):
                    full_compute.history_view({'history_root':'jobs/a','history_root_base':'anywhere'},'timeshare')
                with self.assertRaisesRegex(ValueError,'capture history must be inside'):
                    full_compute.capture_reference(root/'other')

    def test_clipped_legacy_panel_reloads_hash_verified_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);csv=root/'raw.csv'
            csv.write_text('closed_at,open,high,low,close,volume\n'
                           '2026-11-13T15:00:00+08:00,10,12,9,11,1000\n',encoding='utf-8')
            series,receipt=full_compute.load_series(csv,'sz300949','day','unadjusted','tdx')
            cutoff=series.bars[-1].closed_at
            report=calendar_analysis('sz300949','day',series.bars,cutoff,series.input_sha256)
            bundle={'summary':{'symbol':'sz300949'},
                    'chart':{'panels':[{'period':'day','input_bars':1,'bars':[]}]},
                    'evidence':{'reports':{'day':report},'source_receipts':{'day':receipt}}}
            with patch.object(full_compute,'ROOT',root):
                result=full_compute.expand_legacy(bundle)
            self.assertEqual(result['chart']['panels'][0]['input_bars'],1)
            self.assertEqual(result['chart']['panels'][0]['bars'][0]['close'],11)


if __name__=='__main__':unittest.main()
