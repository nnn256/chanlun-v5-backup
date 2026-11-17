from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import Future

from chanmodel import native_market_backtest as native,market_backtest as proxy


class StoppedResourceAdmissionTests(unittest.TestCase):
    def test_finished_batch_has_no_stale_memory_wait_or_active_workers(self):
        for module in (native,proxy):
            with self.subTest(module=module.__name__),tempfile.TemporaryDirectory() as tmp:
                result_future=Future()
                result_future.set_result({'symbol':'sh600000','name':'sample','state':'complete','bars':3,
                    'signal_counts':{},'candidate_count':0,'confirmation_count':0,'withdrawal_count':0,
                    'invalidation_count':0,'confirmations':0,
                    'metrics':{'total_return':0,'max_drawdown':0,'completed_trades':0,'total_fees':0}})
                with patch('workbench.parallel.AdaptiveProcessPool') as pool:
                    instance=pool.return_value.__enter__.return_value
                    instance.admission.return_value=1;instance.submit.return_value=result_future
                    result=module.run_market([{'symbol':'sh600000','name':'sample'}],Path(tmp)/'unused',None,Path(tmp),
                        workers=1,resource_plan={'workers':1,'capacity_workers':1})
                self.assertEqual(result['completed'],1)
                self.assertFalse(result['resources']['waiting_for_memory'])
                self.assertEqual(result['resources']['active_workers'],0)
                self.assertEqual(result['resources']['admission_workers'],0)

    def test_existing_stop_does_not_start_a_cpu_process_pool(self):
        for module in (native,proxy):
            with self.subTest(module=module.__name__),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);stop=root/'STOP';stop.write_text('user stop',encoding='utf-8')
                with patch('workbench.parallel.AdaptiveProcessPool') as pool:
                    instance=pool.return_value.__enter__.return_value
                    instance.admission.side_effect=AssertionError('stopped run created pool')
                    result=module.run_market([{'symbol':'sh600000','name':'sample'}],root/'missing',None,root,
                        workers=1,stop_file=stop,resource_plan={'workers':1,'capacity_workers':1})
                instance.admission.assert_not_called();instance.submit.assert_not_called()
                self.assertEqual(result['completed'],0)
                self.assertFalse(result['successful_coverage_complete'])
                self.assertFalse(result['resources']['waiting_for_memory'])
                self.assertEqual(result['resources']['active_workers'],0)
                self.assertEqual(result['resources']['admission_workers'],0)


if __name__=='__main__':unittest.main()
