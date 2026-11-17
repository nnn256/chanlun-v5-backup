"""UI contracts for truthful, bounded all-market backtest presentation."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'workbench/web/app.js').read_text(encoding='utf-8')
HTML=(ROOT/'workbench/web/index.html').read_text(encoding='utf-8')


def function_body(name):
    match=re.search(rf'function {re.escape(name)}\([^)]*\)\s*\{{',APP)
    if not match:raise AssertionError(f'missing {name} implementation')
    depth=1;index=match.end()
    while index<len(APP) and depth:
        if APP[index]=='{':depth+=1
        elif APP[index]=='}':depth-=1
        index+=1
    if depth:raise AssertionError(f'unclosed {name} implementation')
    return APP[match.end():index-1]


class BacktestUiTests(unittest.TestCase):
    def test_backtest_view_has_preflight_and_start_controls(self):
        section=re.search(r'<section class="workspace" id="view-backtests"[\s\S]*?</section>\s*<section',HTML)
        self.assertIsNotNone(section)
        markup=section.group(0)
        for element_id in ('backtest-preflight-run','backtest-preflight','backtest-start','backtest-runs'):
            self.assertIn(f'id="{element_id}"',markup)

    def test_failed_processed_rows_are_not_presented_as_successful_coverage(self):
        body=function_body('renderBacktestRun')
        self.assertIn('processed=',body)
        self.assertIn('成功覆盖',body)
        self.assertIn('completed_with_errors',function_body('backtestStateLabel'))
        self.assertIn('successful_coverage_complete',body)
        self.assertIn('失败明细',body)
        self.assertIn('缺缓存',body)

    def test_failure_details_are_loaded_lazily_and_paged_by_request(self):
        body=function_body('renderBacktestRun')
        self.assertIn("details.addEventListener('toggle'",body)
        self.assertIn('/api/backtests/errors?id=',body)
        self.assertIn('&offset=${state.offset}&limit=20',body)
        self.assertIn('上一页',body)
        self.assertIn('下一页',body)
        self.assertNotIn('failed_records',body)
        self.assertIn('backtestFailureState',body)

    def test_poll_is_single_flight_and_skips_identical_dom_rebuilds(self):
        body=function_body('refreshBacktests')
        self.assertIn('backtestPollInFlight',body)
        self.assertIn('snapshot!==backtestLastSnapshot',body)
        self.assertIn('backtestPollingActive=runs.some',body)
        self.assertIn("S.view==='backtests'&&backtestPollingActive",APP)
        self.assertIn("S.view==='market'||S.view==='tasks'||S.followJob",APP)

    def test_start_is_disabled_while_coverage_preflight_and_submission_run(self):
        body=APP[APP.index("$('#backtest-start').onclick"):APP.index("setInterval(()=>{if(S.view==='signals'")]
        self.assertIn('if(start.disabled)return',body)
        self.assertIn('start.disabled=true',body)
        self.assertLess(body.index('preflightBacktest()'),body.index("api('/api/backtests/start'"))
        self.assertIn('coverage.available!==coverage.total',body)
        self.assertIn('finally{start.disabled=false;}',body)


if __name__=='__main__':unittest.main()
