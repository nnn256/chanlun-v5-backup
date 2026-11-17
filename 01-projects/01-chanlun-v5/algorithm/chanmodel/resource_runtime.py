"""Bound CPU task admission using live physical memory; no algorithm changes."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import ctypes
import math
import os
from pathlib import Path
import time

MIB=1024**2
GIB=1024**3
_CPU_PREVIOUS=None


def _memory_snapshot():
    if os.name=='nt':
        class Status(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[
                (name,ctypes.c_ulonglong) for name in ('total','available','total_page',
                'available_page','total_virtual','available_virtual','extended')]
        value=Status();value.length=ctypes.sizeof(value)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            return value.total,value.available,value.load
        return None,None,None
    try:
        page=os.sysconf('SC_PAGE_SIZE');total=os.sysconf('SC_PHYS_PAGES')*page
        available=os.sysconf('SC_AVPHYS_PAGES')*page
        return total,available,round((1-available/total)*100,1)
    except (AttributeError,OSError,ValueError):return None,None,None


def _cpu_percent():
    global _CPU_PREVIOUS
    if os.name!='nt':return None
    idle=ctypes.c_ulonglong();kernel=ctypes.c_ulonglong();user=ctypes.c_ulonglong()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):
        return None
    current=(idle.value,kernel.value+user.value);old=_CPU_PREVIOUS;_CPU_PREVIOUS=current
    if old is None or current[1]<=old[1]:return None
    return round(max(0,min(100,100*(1-(current[0]-old[0])/(current[1]-old[1])))),1)


def snapshot_resources():
    total,available,load=_memory_snapshot()
    return {'cpu':{'logical_processors':os.cpu_count() or 1,'load_percent':_cpu_percent()},
            'memory':{'total_bytes':total,'available_bytes':available,'load_percent':load},
            'observed_at':time.time()}


def worker_request(value):
    if value=='auto':return 'auto'
    if isinstance(value,bool):raise ValueError('workers must be auto or an integer from 1 to 16')
    if isinstance(value,str):
        text=value.strip()
        if not text.isascii() or not text.isdecimal():raise ValueError('workers must be auto or an integer from 1 to 16')
        value=int(text)
    if isinstance(value,float) and math.isfinite(value) and value.is_integer():value=int(value)
    if not isinstance(value,int) or not 1<=value<=16:raise ValueError('workers must be auto or an integer from 1 to 16')
    return value


def plan_workers(workers='auto',memory_per_worker_mb=384,snapshot=None):
    workers=worker_request(workers)
    if not isinstance(memory_per_worker_mb,(int,float)) or not math.isfinite(memory_per_worker_mb) or memory_per_worker_mb<=0:
        raise ValueError('memory_per_worker_mb must be positive and finite')
    snapshot=snapshot if snapshot is not None else snapshot_resources()
    logical=int(snapshot.get('cpu',{}).get('logical_processors') or 1)
    ceiling=max(1,min(16,logical-2 if logical>2 else 1))
    requested=ceiling if workers=='auto' else min(workers,ceiling)
    memory=snapshot.get('memory',{});total=memory.get('total_bytes');available=memory.get('available_bytes')
    reserve=max(int(1.5*GIB),int((total or 0)*.15));per_worker=int(memory_per_worker_mb*MIB)
    known=isinstance(available,int) and available>=0
    capacity=max(0,(available-reserve)//per_worker) if known else 0
    target=min(requested,capacity)
    reason='memory_unknown' if not known else 'insufficient_memory' if target==0 else 'memory_limit' if target<requested else 'ready'
    return {'target_workers':target,'ceiling':ceiling,'requested':workers,'reserve_bytes':reserve,
            'memory_per_worker_bytes':per_worker,'available_bytes':available,'reason':reason,
            'state':'ready' if target else 'waiting_memory','mode':'auto' if workers=='auto' else 'upper_bound'}


def adaptive_results(fn,tasks,*,workers='auto',memory_per_worker_mb=384,stop_file=None,
                     should_stop=None,on_resource=None,snapshot_fn=snapshot_resources,
                     poll_seconds=.5):
    """Yield (task, Future), keeping task iteration lazy and results unchanged.

    Pool resizing drains admitted work first, then destroys idle processes to
    release their memory. No unfinished stock is killed for a resource change.
    """
    workers=worker_request(workers)
    if poll_seconds<=0:raise ValueError('poll_seconds must be positive')
    iterator=iter(tasks);pool=None;size=0;pending={};exhausted=False
    missing=object();buffer=missing
    last_notice=0.;signature=None;last_plan=None;last_probe=0.
    def stopped():return bool((stop_file and Path(stop_file).exists()) or (should_stop and should_stop()))
    try:
        while pending or not exhausted:
            if stopped() and not pending:break
            if buffer is missing and not exhausted and not stopped():
                try:buffer=next(iterator)
                except StopIteration:exhausted=True
            if exhausted and not pending:break
            now=time.monotonic()
            if last_plan is None or now-last_probe>=1:
                snapshot=snapshot_fn();last_plan=plan_workers(workers,memory_per_worker_mb,snapshot);last_probe=now
            plan=dict(last_plan);stop=stopped();target=0 if stop else plan['target_workers']
            if pool is not None and not stop and isinstance(plan['available_bytes'],int):
                limit=plan['ceiling'] if workers=='auto' else min(workers,plan['ceiling'])
                deficit=plan['reserve_bytes']-plan['available_bytes']
                if deficit>0:
                    target=max(0,size-math.ceil(deficit/plan['memory_per_worker_bytes']))
                else:
                    target=min(limit,size+target)
                plan['target_workers']=target
            rotating=pool is not None and target!=size
            if rotating and not pending:
                pool.shutdown(wait=True,cancel_futures=True);pool=None;size=0
                # Releasing idle children can materially change free memory.
                last_plan=None
                continue
            if not stop and target>0 and pool is None:
                pool=ProcessPoolExecutor(max_workers=target);size=target
            if pool is not None and not rotating and not stop:
                while len(pending)<target and not exhausted:
                    if stopped():stop=True;break
                    if buffer is not missing:task=buffer;buffer=missing
                    else:
                        try:task=next(iterator)
                        except StopIteration:exhausted=True;break
                    pending[pool.submit(fn,task)]=task
            status={**snapshot,'plan':plan,'active_workers':len(pending),'pool_workers':size,
                    'state':'stopping' if stop else 'draining_to_resize' if rotating else 'running' if pending else 'waiting_memory',
                    'resource_policy':'cpu_memory_adaptive_v1','execution_backend':'cpu_multiprocess'}
            key=(target,size,status['state'],plan['reason'])
            if on_resource and (key!=signature or now-last_notice>=5):
                on_resource(status);signature=key;last_notice=now
            if pending:
                done,_=wait(pending,timeout=min(poll_seconds,1),return_when=FIRST_COMPLETED)
                for future in done:yield pending.pop(future),future
            elif exhausted or stop:break
            else:time.sleep(min(poll_seconds,1))
    finally:
        if pool is not None:pool.shutdown(wait=True,cancel_futures=True)
        if on_resource:
            on_resource({**snapshot_fn(),'plan':last_plan or {},'active_workers':0,'pool_workers':0,
                'state':'completed' if exhausted and buffer is missing else 'stopped',
                'resource_policy':'cpu_memory_adaptive_v1','execution_backend':'cpu_multiprocess'})
