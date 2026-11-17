from concurrent.futures import Future
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from workbench.parallel import AdaptiveProcessPool


class AdaptiveParallelTests(unittest.TestCase):
    def test_low_memory_does_not_start_idle_windows_workers(self):
        with patch('workbench.parallel.admission_limit',return_value=0),patch('workbench.parallel.ProcessPoolExecutor') as factory:
            with AdaptiveProcessPool({'workers':1,'capacity_workers':16}) as pool:
                self.assertEqual(pool.admission(0),0)
            factory.assert_not_called()

    def test_pool_never_grows_while_stocks_are_in_flight(self):
        with patch('workbench.parallel.admission_limit',side_effect=[2,8,4]),patch('workbench.parallel.ProcessPoolExecutor') as factory:
            with AdaptiveProcessPool({'workers':2,'capacity_workers':8}) as pool:
                self.assertEqual(pool.admission(0),2)
                self.assertEqual(pool.admission(2),2)
                factory.assert_called_once_with(max_workers=2)
                self.assertEqual(pool.admission(0),4)
                self.assertEqual(factory.call_count,2)
                self.assertEqual(factory.call_args.kwargs['max_workers'],4)

    def test_waiting_for_ram_does_not_mark_backtest_complete(self):
        from chanmodel import native_market_backtest as native
        plan={'workers':1,'capacity_workers':2}
        records=[{'symbol':'sh600000'}]
        instance=Mock();instance.__enter__=Mock(return_value=instance);instance.__exit__=Mock(return_value=False)
        instance.admission.return_value=0
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);stop=folder/'STOP';observed=[]
            def progress(summary):
                observed.append(summary)
                stop.write_text('stop requested while waiting')
            with patch('workbench.parallel.AdaptiveProcessPool',return_value=instance),patch('chanmodel.native_market_backtest.time.sleep'):
                result=native.run_market(records,folder,None,folder,1,progress,stop,resource_plan=plan)
            self.assertTrue(observed[0]['resources']['waiting_for_memory'])
            self.assertFalse(result['processing_complete'])
            self.assertEqual(result['remaining'],1)
            instance.submit.assert_not_called()


if __name__=='__main__':unittest.main()
