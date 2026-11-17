"""Conservative local CPU/RAM scheduling and factual optional-GPU reporting.

Market/provider fan-out is network I/O. The Python structural replay runs in
bounded local processes, while the existing OpenCL kernel remains restricted
to independent bootstrap integer sums.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from functools import lru_cache


MIB=1024*1024
GIB=1024*MIB
_LOCK=threading.Lock()
_CACHE={'at':0.0,'gpu':None}
_RESERVE_MIB=384
_WORKER_MIB=512


def _read(path):
    try:return Path(path).read_text(encoding='ascii').strip()
    except (OSError,UnicodeError):return None


def _memory():
    total=available=None;source='unknown'
    if os.name=='nt':
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_=[('dwLength',ctypes.c_ulong),('dwMemoryLoad',ctypes.c_ulong),
                      ('ullTotalPhys',ctypes.c_ulonglong),('ullAvailPhys',ctypes.c_ulonglong),
                      ('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),
                      ('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),
                      ('ullAvailExtendedVirtual',ctypes.c_ulonglong)]
        try:
            info=MEMORYSTATUSEX();info.dwLength=ctypes.sizeof(info)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
                total=int(info.ullTotalPhys);available=int(info.ullAvailPhys);source='windows_globalmemorystatusex'
        except (AttributeError,OSError):pass
    elif os.path.isfile('/proc/meminfo'):
        values={}
        for line in Path('/proc/meminfo').read_text(encoding='ascii').splitlines():
            match=re.match(r'^(MemTotal|MemAvailable):\s+(\d+)\s+kB$',line)
            if match:values[match.group(1)]=int(match.group(2))*1024
        total=values.get('MemTotal');available=values.get('MemAvailable');source='proc_meminfo'
    try:
        if hasattr(os,'sysconf'):
            page=os.sysconf('SC_PAGE_SIZE');physical=os.sysconf('SC_PHYS_PAGES')
            if total is None:total=page*physical
            if available is None:available=os.sysconf('SC_AVPHYS_PAGES')*page
            if source=='unknown':source='sysconf'
    except (AttributeError,OSError,ValueError):pass

    # The effective cgroup limit wins over host memory so a container cannot
    # allocate based on RAM that it is not permitted to use.
    limit_text=_read('/sys/fs/cgroup/memory.max')
    current_text=_read('/sys/fs/cgroup/memory.current')
    cgroup_version='v2'
    if not limit_text:
        limit_text=_read('/sys/fs/cgroup/memory/memory.limit_in_bytes')
        current_text=_read('/sys/fs/cgroup/memory/memory.usage_in_bytes')
        cgroup_version='v1'
    if limit_text and limit_text!='max':
        try:
            limit=int(limit_text);current=int(current_text or 0)
            if 0<limit<1<<60:
                total=min(total,limit) if total is not None else limit
                available=min(available,max(0,limit-current)) if available is not None else max(0,limit-current)
                source+=f'+cgroup_{cgroup_version}'
        except ValueError:pass
    if total is not None:total=max(1,int(total))
    if available is not None:available=max(0,min(int(available),total or int(available)))
    return {'total_bytes':total,'available_bytes':available,'source':source}


def _cpu():
    logical=os.cpu_count() or 1
    affinity=None
    try:affinity=len(os.sched_getaffinity(0))
    except (AttributeError,OSError):
        if os.name=='nt':
            try:
                class SYSTEM_INFO(ctypes.Structure):
                    _fields_=[('wProcessorArchitecture',ctypes.c_ushort),('wReserved',ctypes.c_ushort),
                              ('dwPageSize',ctypes.c_ulong),('lpMinimumApplicationAddress',ctypes.c_void_p),
                              ('lpMaximumApplicationAddress',ctypes.c_void_p),('dwActiveProcessorMask',ctypes.c_size_t),
                              ('dwNumberOfProcessors',ctypes.c_ulong),('dwProcessorType',ctypes.c_ulong),
                              ('dwAllocationGranularity',ctypes.c_ulong),('wProcessorLevel',ctypes.c_ushort),
                              ('wProcessorRevision',ctypes.c_ushort)]
                info=SYSTEM_INFO();ctypes.windll.kernel32.GetSystemInfo(ctypes.byref(info));affinity=int(info.dwNumberOfProcessors)
            except (AttributeError,OSError):pass
    effective=max(1,min(logical,affinity or logical))
    # Leave one logical core to the UI, browser and the operating system.
    return {'logical':logical,'affinity':affinity,'effective':effective,'reserved_for_ui':1}


@lru_cache(maxsize=1)
def _gpu_cached():
    with _LOCK:
        if _CACHE['gpu'] is not None and time.monotonic()-_CACHE['at']<60:return _CACHE['gpu']
    report={'detected':[],'opencl_bootstrap':None,'recursive_engine_backend':'cpu',
            'recursive_engine_gpu_acceleration':False}
    binary=shutil.which('nvidia-smi')
    if binary:
        try:
            result=subprocess.run([binary,'--query-gpu=name,memory.total,memory.free,driver_version','--format=csv,noheader,nounits'],
                                  capture_output=True,text=True,timeout=2,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if result.returncode==0:
                for line in result.stdout.splitlines():
                    columns=[column.strip() for column in line.split(',')]
                    if len(columns)>=4:report['detected'].append({'name':columns[0],'memory_total_mib':int(columns[1]),'memory_free_mib':int(columns[2]),'driver':columns[3],'probe':'nvidia-smi'})
        except (OSError,ValueError,subprocess.TimeoutExpired) as error:report['nvidia_probe_error']=str(error)
    with _LOCK:_CACHE.update(at=time.monotonic(),gpu=report)
    return report


def _gpu():
    return _gpu_cached()


def inspect():
    cpu=_cpu();memory=_memory()
    hosted=os.environ.get('LIANGCE_HOSTING','hosted')
    local=hosted in {'local-research','local'} and os.environ.get('LIANGCE_AUTO_RESOURCES','1')!='0'
    try:cpu_ceiling=max(1,min(int(os.environ.get('LIANGCE_LOCAL_MAX_WORKERS','4')),16))
    except ValueError:cpu_ceiling=4
    maximum=max(1,min(cpu['effective']-cpu['reserved_for_ui'],cpu_ceiling))
    available=memory['available_bytes'];total=memory['total_bytes']
    reserve=max(256*MIB,min(_RESERVE_MIB*MIB,int((total or _RESERVE_MIB*MIB)*.02)))
    try:per_worker=max(256*MIB,int(os.environ.get('LIANGCE_WORKER_MEMORY_MIB',str(_WORKER_MIB)))*MIB)
    except ValueError:per_worker=_WORKER_MIB*MIB
    if available is None:memory_workers=1;memory_pressure='unknown_conservative'
    else:
        memory_workers=0 if available<reserve else (available-reserve)//per_worker
        memory_pressure='low' if available<reserve+per_worker*2 else 'normal'
    detected=min(maximum,int(memory_workers)) if local else 1
    manual=os.environ.get('LIANGCE_WORKERS')
    if local and manual and manual.lower() not in {'auto','0'}:
        try:detected=min(detected,max(1,int(manual)))
        except ValueError:pass
    gpu=_gpu()
    try:
        opencl=_opencl_probe()
        gpu['opencl_bootstrap']={key:opencl.get(key) for key in ('supported','backend','name','vendor','driver_version','opencl_version','reason','operation')}
        if opencl.get('supported') and not any(item.get('name')==opencl.get('name') for item in gpu['detected']):
            gpu['detected'].append({'name':opencl['name'],'vendor':opencl.get('vendor'),'probe':'OpenCL GPU device query only'})
    except Exception as error:gpu['opencl_bootstrap']={'supported':False,'reason':f'{type(error).__name__}: {error}'}
    return {'profile':'local_auto' if local else 'hosted_serial','automatic':local,'hosting':hosted,
        'cpu':cpu,'memory':{**memory,'reserve_bytes':reserve,'estimated_bytes_per_worker':per_worker,
                             'pressure':memory_pressure,'planned_concurrency':detected},
        'workers':detected,'max_workers':maximum,
        'selection_reason':('CPU affinity and available RAM after reserve; V4 local-research limit is '+str(cpu_ceiling)+' worker(s)' if detected else 'local dispatch paused because available RAM is below the desktop reserve') if local else 'hosted deployment retains one serialized compute slot',
        'gpu':gpu,'gpu_used_for_current_recursive_compute':False,
        'network_accelerated_by_cpu_or_gpu':False}


@lru_cache(maxsize=1)
def _opencl_probe():
    from chanmodel.local_gpu import probe_gpu
    return probe_gpu()
