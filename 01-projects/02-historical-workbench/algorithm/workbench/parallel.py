"""Process batches sized before Windows eagerly spawns all pool workers."""
from concurrent.futures import ProcessPoolExecutor

from .resources import admission_limit


class AdaptiveProcessPool:
    def __init__(self,plan):
        self.plan=plan;self.pool=None;self.workers=0;self.drain_pending=False

    def __enter__(self):return self

    def __exit__(self,*exc):
        if self.pool:self.pool.shutdown(wait=True)

    def admission(self,active_workers):
        allowed=admission_limit(self.plan,active_workers=active_workers)
        if active_workers:
            desired=min(allowed,self.plan.get('capacity_workers',self.plan['workers']))
            if desired!=self.workers:self.drain_pending=True
            # Once a resize is requested, keep the remaining tasks but stop
            # refilling freed slots. Otherwise a steady multi-worker queue
            # never becomes empty and cannot use recovered CPU/RAM capacity.
            if self.drain_pending:return active_workers
            return min(allowed,self.workers)
        # No in-flight work is cancelled. A new pool can use more cores only
        # after its prior batch drains; Windows spawns max_workers eagerly.
        target=min(allowed,self.plan.get('capacity_workers',self.plan['workers']))
        if self.pool and target!=self.workers:
            self.pool.shutdown(wait=True);self.pool=None;self.workers=0
        if target>0 and not self.pool:
            self.pool=ProcessPoolExecutor(max_workers=target);self.workers=target
        self.drain_pending=False
        return target

    def submit(self,fn,*args,**kwargs):
        if not self.pool:raise RuntimeError('worker admission must precede submit')
        return self.pool.submit(fn,*args,**kwargs)
