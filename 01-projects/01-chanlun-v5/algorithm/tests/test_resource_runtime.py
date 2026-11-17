from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chanmodel import resource_runtime as runtime


def square(value):return value*value


class InlinePool:
    sizes=[]
    shutdowns=[]
    def __init__(self,max_workers):self.sizes.append(max_workers)
    def submit(self,fn,task):
        result=Future()
        try:result.set_result(fn(task))
        except Exception as exc:result.set_exception(exc)
        return result
    def shutdown(self,**kwargs):self.shutdowns.append(kwargs)


class ResourceRuntimeTests(unittest.TestCase):
    def snapshot(self,free):return {'cpu':{'logical_processors':20},'memory':{'total_bytes':16*1024**3,'available_bytes':free}}

    def test_low_memory_wait_and_manual_upper_bound(self):
        self.assertEqual(runtime.plan_workers('auto',384,self.snapshot(900*1024**2))['target_workers'],0)
        self.assertEqual(runtime.plan_workers(2,384,self.snapshot(6*1024**3))['target_workers'],2)
        self.assertEqual(runtime.plan_workers('auto',384,self.snapshot(6*1024**3))['target_workers'],9)

    def test_unknown_memory_and_invalid_inputs(self):
        self.assertEqual(runtime.plan_workers('auto',snapshot={'cpu':{},'memory':{}})['reason'],'memory_unknown')
        for value in (True,False,0,17,'many',float('nan')):
            with self.subTest(value=value),self.assertRaises(ValueError):runtime.plan_workers(value)

    def test_preexisting_stop_does_not_consume_tasks_or_spawn(self):
        with TemporaryDirectory() as tmp:
            stop=Path(tmp)/'STOP';stop.touch()
            with patch.object(runtime,'ProcessPoolExecutor') as pool:
                result=list(runtime.adaptive_results(square,iter([1,2]),stop_file=stop,snapshot_fn=lambda:self.snapshot(6*1024**3)))
            self.assertEqual(result,[]);pool.assert_not_called()

    def test_bounded_execution_preserves_results_and_task_errors(self):
        InlinePool.sizes=[]
        with patch.object(runtime,'ProcessPoolExecutor',InlinePool):
            results=list(runtime.adaptive_results(square,range(5),workers=2,snapshot_fn=lambda:self.snapshot(6*1024**3)))
        self.assertEqual(sorted((task,future.result()) for task,future in results),[(i,i*i) for i in range(5)])
        self.assertEqual(InlinePool.sizes,[2])

    def test_pause_while_memory_waiting_does_not_lose_tasks(self):
        checked=[]
        def stop():checked.append(1);return len(checked)>1
        with patch.object(runtime,'ProcessPoolExecutor') as pool:
            self.assertEqual(list(runtime.adaptive_results(square,[1],should_stop=stop,poll_seconds=.01,
                snapshot_fn=lambda:self.snapshot(100*1024**2))),[])
            pool.assert_not_called()

    def test_pressure_drains_pool_then_releases_workers_before_restarting(self):
        InlinePool.sizes=[];InlinePool.shutdowns=[]
        snapshots=iter([self.snapshot(6*1024**3),self.snapshot(100*1024**2),self.snapshot(6*1024**3)])
        def snapshot():
            try:return next(snapshots)
            except StopIteration:return self.snapshot(6*1024**3)
        clock=iter(range(1000))
        with patch.object(runtime,'ProcessPoolExecutor',InlinePool),patch.object(runtime.time,'monotonic',side_effect=lambda:next(clock)):
            result=list(runtime.adaptive_results(square,range(3),workers=2,snapshot_fn=snapshot,poll_seconds=.01))
        self.assertEqual(sorted(future.result() for _,future in result),[0,1,4])
        self.assertEqual(InlinePool.sizes,[2,2])
        self.assertEqual(len(InlinePool.shutdowns),2)

    def test_no_tasks_does_not_wait_for_unavailable_memory(self):
        with patch.object(runtime,'ProcessPoolExecutor') as pool:
            self.assertEqual(list(runtime.adaptive_results(square,[],snapshot_fn=lambda:self.snapshot(0))),[])
        pool.assert_not_called()

    def test_real_single_process_executes_without_changing_results(self):
        # A small process smoke uses a deterministic planner fixture; it is
        # not a benchmark of this machine's current resource capacity.
        values=list(runtime.adaptive_results(square,[2,3],workers=1,
            snapshot_fn=lambda:self.snapshot(6*1024**3)))
        self.assertEqual(sorted((task,future.result()) for task,future in values),[(2,4),(3,9)])


if __name__=='__main__':unittest.main()
