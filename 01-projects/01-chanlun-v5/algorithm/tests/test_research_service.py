from datetime import datetime,timedelta,timezone
import unittest

from workbench import research_service as service


CN=timezone(timedelta(hours=8))


def row(index,close,is_closed=True):
    stamp=(datetime(2026,1,1,15,tzinfo=CN)+timedelta(days=index)).isoformat()
    return {'source_index':index,'closed_at':stamp,'open':close-.1,'high':close+.2,
            'low':close-.2,'close':close,'volume':1000.,'is_closed':is_closed}


def panel(rows):
    return {'kind':'candlestick','period':'day','bars':rows}


class ResearchServiceTests(unittest.TestCase):
    def setUp(self):
        with service.LOCK:
            service.CACHE.clear();service.KEY_LOCKS.clear()

    def test_only_closed_daily_rows_enter_resident_session_and_append_once(self):
        first=panel([row(i,100-i*.3) for i in range(80)]+[row(80,76,False)])
        service.attach_research(first,'sh600000')
        before=first['regime_research']
        self.assertEqual(before['runtime']['closed_bars'],80)
        self.assertEqual(before['runtime']['new_closed_bars'],80)
        self.assertTrue(before['provenance']['open_bar_excluded'])
        self.assertEqual(before['runtime']['forming_bars_excluded'],1)
        self.assertEqual(before['as_of'],first['bars'][79]['closed_at'])

        appended=panel([*first['bars'],row(80,76,True)])
        service.attach_research(appended,'sh600000')
        after=appended['regime_research']
        self.assertTrue(after['runtime']['session_reused'])
        self.assertEqual(after['runtime']['new_closed_bars'],1)
        self.assertEqual(after['runtime']['closed_bars'],81)
        self.assertEqual(after['latest']['index'],80)

    def test_changed_history_invalidates_resident_prefix(self):
        source=panel([row(i,100-i*.2) for i in range(80)])
        service.attach_research(source,'sh600519')
        changed=panel([row(i,99-i*.2) for i in range(80)]+[row(80,83)])
        service.attach_research(changed,'sh600519')
        receipt=changed['regime_research']['runtime']
        self.assertFalse(receipt['session_reused'])
        self.assertEqual(receipt['new_closed_bars'],81)
        self.assertEqual(receipt['history_rebuild_reason'],'cold_start_or_changed_history_or_context')

    def test_intraday_and_line_panels_are_not_mutated_with_daily_regime(self):
        for value in [{'kind':'line','period':'day','bars':[row(i,10+i) for i in range(3)]},
                      {'kind':'candlestick','period':'30m','bars':[row(i,10+i) for i in range(3)]}]:
            before=dict(value);result=service.attach_research(value,'sh600000')
            self.assertIs(result,value)
            self.assertEqual(value,before)
            self.assertNotIn('regime_research',value)

    def test_partly_invalid_suffix_does_not_poison_the_next_valid_request(self):
        source=[row(i,100-i*.2) for i in range(80)]
        service.attach_research(panel(source),'sh600000')
        bad=row(81,84);bad['high']=1
        with self.assertRaises(ValueError):
            service.attach_research(panel(source+[row(80,84),bad]),'sh600000')
        self.assertNotIn('sh600000',service.CACHE)
        valid=panel(source+[row(80,84)])
        service.attach_research(valid,'sh600000')
        self.assertEqual(valid['regime_research']['latest']['index'],80)
        self.assertFalse(valid['regime_research']['runtime']['session_reused'])

    def test_changed_embedded_context_invalidates_cached_same_price_prefix(self):
        rows=[row(i,100-i*.2) for i in range(80)]
        context={'net_flow':100,'available_at':rows[-1]['closed_at'],'source':'fixture'}
        before=panel([*rows[:-1],{**rows[-1],'context':context}])
        service.attach_research(before,'sh600000')
        after=panel([*rows[:-1],{**rows[-1],'context':{**context,'net_flow':999}}])
        service.attach_research(after,'sh600000')
        self.assertFalse(after['regime_research']['runtime']['session_reused'])
        self.assertEqual(after['regime_research']['latest']['features']['actual_fund_flow']['net_flow'],999)


if __name__=='__main__':unittest.main()
