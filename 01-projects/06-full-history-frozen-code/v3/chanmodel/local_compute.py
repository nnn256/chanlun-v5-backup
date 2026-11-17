"""Local-only CPU scheduling with live RAM admission and deterministic ordering.

Independent symbols may run in separate processes; bars inside a symbol remain
sequential. The hosted API's single-allocation gate is deliberately unchanged.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import ctypes
import multiprocessing
import os
import platform
import time

MIB=1024**2
DEFAULT_RESERVE_MIB=1024
DEFAULT_WORKER_MIB=256


def memory_snapshot():
    if os.name=='nt':
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),
                ('total',ctypes.c_ulonglong),('available',ctypes.c_ulonglong),
                ('page_total',ctypes.c_ulonglong),('page_available',ctypes.c_ulonglong),
                ('virtual_total',ctypes.c_ulonglong),('virtual_available',ctypes.c_ulonglong),
                ('extended',ctypes.c_ulonglong)]
        value=Memory();value.length=ctypes.sizeof(value)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            raise OSError('GlobalMemoryStatusEx failed')
        return {'total_bytes':int(value.total),'available_bytes':int(value.available),'source':'GlobalMemoryStatusEx'}
    try:
        values={}
        with open('/proc/meminfo',encoding='ascii') as f:
            for line in f:
                key,value=line.split(':',1);values[key]=int(value.split()[0])*1024
        available=values.get('MemAvailable',values.get('MemFree',0))
        result={'total_bytes':values['MemTotal'],'available_bytes':available,'source':'proc_meminfo'}
        # Respect a container limit when this module is used from a local image.
        try:
            with open('/sys/fs/cgroup/memory.max') as f:limit=int(f.read().strip())
            with open('/sys/fs/cgroup/memory.current') as f:used=int(f.read().strip())
            result.update(total_bytes=min(result['total_bytes'],limit),available_bytes=min(available,max(0,limit-used)))
        except (OSError,ValueError):pass
        return result
    except (OSError,KeyError,ValueError):
        return {'total_bytes':None,'available_bytes':None,'source':'unavailable'}


def plan_resources(requested='auto',task_count=1,*,worker_mib=DEFAULT_WORKER_MIB,
                   reserve_mib=DEFAULT_RESERVE_MIB,memory=None,cpu_count=None):
    if type(task_count) is not int or task_count<0:raise ValueError('task_count must be nonnegative')
    if type(worker_mib) is not int or worker_mib<32:raise ValueError('worker_mib must be at least 32')
    if type(reserve_mib) is not int or reserve_mib<256:raise ValueError('reserve_mib must be at least 256')
    if requested!='auto':
        if isinstance(requested,str) and requested.isdigit():requested=int(requested)
        if type(requested) is not int or not 1<=requested<=32:raise ValueError('workers must be auto or 1..32')
    memory=memory_snapshot() if memory is None else memory
    cpus=cpu_count or os.cpu_count() or 1
    cap=min(8,max(1,cpus-2)) if requested=='auto' else min(requested,max(1,cpus-1))
    free=memory.get('available_bytes')
    ram_cap=max(1,(free-reserve_mib*MIB)//(worker_mib*MIB)) if free is not None else 1
    selected=max(1,min(max(1,task_count),cap,ram_cap))
    reason='memory_limited' if ram_cap<cap else 'cpu_and_task_limit'
    if requested==1:reason='explicit_serial_reference'
    return {'requested_workers':requested,'workers':selected,'logical_cpus':cpus,
        'reserve_mib':reserve_mib,'estimated_worker_mib':worker_mib,
        'memory':dict(memory),'reason':reason,'memory_unknown_serial':free is None,
        'start_method':'spawn' if selected>1 else 'inline','scope':'local_offline_batch',
        'hosted_compute_gate_changed':False}


def _worker_setup():
    # Each spawned process owns one Python state machine. Prevent numerical
    # libraries from multiplying their own thread pools per process.
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[name]='1'
    if os.name=='nt':
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),0x4000)
    elif hasattr(os,'nice'):
        try:os.nice(5)
        except OSError:pass


class OrderedLocalMap:
    def __init__(self,function,tasks,*,workers='auto',worker_mib=DEFAULT_WORKER_MIB,
                 reserve_mib=DEFAULT_RESERVE_MIB):
        self.function=function;self.tasks=list(tasks)
        self.plan=plan_resources(workers,len(self.tasks),worker_mib=worker_mib,reserve_mib=reserve_mib)
        self.stats={'max_in_flight':0,'admission_throttles':0,'completed':0,'seconds':None,
            'ordering':'input_order','workers_started':self.plan['workers'] if self.plan['workers']>1 else 0}

    def __iter__(self):
        start=time.perf_counter()
        try:
            if self.plan['workers']==1:
                for task in self.tasks:
                    result=self.function(task);self.stats['completed']+=1
                    yield result
                return
            with ProcessPoolExecutor(max_workers=self.plan['workers'],
                    mp_context=multiprocessing.get_context('spawn'),initializer=_worker_setup) as pool:
                pending={};ready={};submitted=0;next_output=0
                while next_output<len(self.tasks):
                    while submitted<len(self.tasks) and len(pending)+len(ready)<self.plan['workers']:
                        memory=memory_snapshot();free=memory.get('available_bytes')
                        # A single active task can make progress; extra work is
                        # admitted only while the desktop reserve remains free.
                        if pending and (free is None or free<self.plan['reserve_mib']*MIB):
                            self.stats['admission_throttles']+=1;break
                        future=pool.submit(self.function,self.tasks[submitted]);pending[future]=submitted;submitted+=1
                        self.stats['max_in_flight']=max(self.stats['max_in_flight'],len(pending))
                    if pending:
                        completed,_=wait(pending,return_when=FIRST_COMPLETED)
                        for future in completed:ready[pending.pop(future)]=future.result()
                    while next_output in ready:
                        result=ready.pop(next_output);next_output+=1;self.stats['completed']+=1
                        yield result
        finally:self.stats['seconds']=round(time.perf_counter()-start,6)
