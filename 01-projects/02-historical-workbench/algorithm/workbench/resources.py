"""Measured host resources and conservative process-admission budgets.

GPU discovery is informational. The recursive Chan engines execute on CPUs;
no CUDA availability claim or numerical backend change is made here.
"""
from __future__ import annotations

import copy
import csv
import ctypes
from datetime import datetime, timezone
import io
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import threading
import time

MIB = 1024 ** 2
GIB = 1024 ** 3
_LOCK = threading.Lock()
_STATIC = None
_GPU = None

# Budgets include per-stock decoded JSON, price history and engine state.
# They are admission estimates, not assertions about a stock's actual RSS.
WORKER_MEMORY = {
    'day': 320 * MIB, 'multi': 768 * MIB, 'full': 1024 * MIB,
    'replay': 512 * MIB, 'native_backtest': 512 * MIB,
    'backtest': 512 * MIB, 'regime': 384 * MIB,
}


def _memory():
    if os.name == 'nt':
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                        ('total_phys', ctypes.c_ulonglong), ('avail_phys', ctypes.c_ulonglong),
                        ('total_page', ctypes.c_ulonglong), ('avail_page', ctypes.c_ulonglong),
                        ('total_virtual', ctypes.c_ulonglong), ('avail_virtual', ctypes.c_ulonglong),
                        ('avail_extended', ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return {'total_bytes': int(status.total_phys), 'available_bytes': int(status.avail_phys),
                        'source': 'GlobalMemoryStatusEx', 'state': 'observed'}
        except (AttributeError, OSError):
            pass
    try:
        fields = {}
        for line in Path('/proc/meminfo').read_text().splitlines():
            name, value = line.split(':', 1)
            fields[name] = int(value.strip().split()[0]) * 1024
        return {'total_bytes': fields['MemTotal'],
                'available_bytes': fields.get('MemAvailable', fields.get('MemFree', 0)),
                'source': '/proc/meminfo', 'state': 'observed'}
    except (OSError, ValueError, KeyError):
        pass
    try:
        size = os.sysconf('SC_PAGE_SIZE')
        return {'total_bytes': int(size * os.sysconf('SC_PHYS_PAGES')),
                'available_bytes': int(size * os.sysconf('SC_AVPHYS_PAGES')),
                'source': 'os.sysconf', 'state': 'observed'}
    except (AttributeError, ValueError, OSError):
        return {'total_bytes': None, 'available_bytes': None, 'source': None, 'state': 'unavailable'}


def _cpu():
    logical = max(1, os.cpu_count() or 1)
    machine=os.environ.get('PROCESSOR_ARCHITECTURE','unknown') if os.name=='nt' else platform.machine()
    model = os.environ.get('PROCESSOR_IDENTIFIER') or machine
    physical = None
    source = 'os.cpu_count'
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                model = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
        except OSError:
            pass
        try:
            length = ctypes.c_ulong(0)
            function = ctypes.windll.kernel32.GetLogicalProcessorInformationEx
            function(0, None, ctypes.byref(length))
            buffer = ctypes.create_string_buffer(length.value)
            if function(0, buffer, ctypes.byref(length)):
                offset, count = 0, 0
                while offset + 8 <= length.value:
                    relation = int.from_bytes(buffer.raw[offset:offset + 4], 'little')
                    size = int.from_bytes(buffer.raw[offset + 4:offset + 8], 'little')
                    if size < 8:
                        break
                    count += relation == 0
                    offset += size
                physical = count or None
                source += '+GetLogicalProcessorInformationEx'
        except (AttributeError, OSError, ValueError):
            pass
    elif Path('/proc/cpuinfo').exists():
        try:
            content = Path('/proc/cpuinfo').read_text()
            cores = set()
            for block in content.split('\n\n'):
                entries = dict(line.split(':', 1) for line in block.splitlines() if ':' in line)
                entries = {k.strip(): v.strip() for k, v in entries.items()}
                model = entries.get('model name', model)
                if 'physical id' in entries and 'core id' in entries:
                    cores.add((entries['physical id'], entries['core id']))
            physical = len(cores) or None
            source += '+/proc/cpuinfo'
        except OSError:
            pass
    return {'model': model, 'physical_cores': physical, 'logical_processors': logical, 'source': source}


def _run(command, timeout=4):
    return subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def _gpu():
    devices, evidence, errors = [], [], []
    binary = shutil.which('nvidia-smi')
    if binary:
        try:
            result = _run([binary, '--query-gpu=name,memory.total,memory.free,driver_version',
                           '--format=csv,noheader,nounits'])
            if result.returncode == 0:
                for row in csv.reader(io.StringIO(result.stdout)):
                    if len(row) != 4:
                        continue
                    name, total, available, driver = [v.strip() for v in row]
                    devices.append({'name': name, 'memory_total_bytes': int(float(total) * MIB),
                                    'memory_available_bytes': int(float(available) * MIB),
                                    'driver_version': driver, 'source': 'nvidia-smi'})
                if devices:
                    evidence.append('nvidia-smi')
            else:
                errors.append('nvidia-smi returned exit ' + str(result.returncode))
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            errors.append(type(exc).__name__ + ': ' + str(exc))
    if os.name == 'nt':
        try:
            # CIM also lists Intel/AMD/display-only adapters; it does not prove
            # CUDA capability and AdapterRAM can be truncated on some drivers.
            command = '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress'
            result = _run(['powershell', '-NoProfile', '-Command', command], timeout=6)
            if result.returncode == 0 and result.stdout.strip():
                import json
                rows = json.loads(result.stdout)
                rows = rows if isinstance(rows, list) else [rows]
                names = {d['name'] for d in devices}
                for row in rows:
                    if row.get('Name') and row['Name'] not in names:
                        devices.append({'name': row['Name'], 'memory_total_bytes': row.get('AdapterRAM'),
                                        'memory_available_bytes': None, 'driver_version': row.get('DriverVersion'),
                                        'source': 'Win32_VideoController', 'memory_reporting': 'driver-reported display memory'})
                evidence.append('Win32_VideoController')
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            errors.append(type(exc).__name__ + ': ' + str(exc))
    return {'devices': devices, 'evidence': evidence, 'errors': errors,
            'state': 'observed' if devices else 'unavailable', 'compute_backend': 'cpu',
            'enabled': False, 'reason': 'Recursive structure engine has no validated GPU backend; GPU discovery does not enable CUDA.'}


def hardware_snapshot(include_gpu=False, refresh=False):
    """Observe free RAM every call; cache hardware inventory between calls."""
    global _STATIC, _GPU
    with _LOCK:
        if refresh or _STATIC is None:
            _STATIC = {'cpu': _cpu(), 'system': {'platform': 'Windows' if os.name=='nt' else platform.system(), 'machine':os.environ.get('PROCESSOR_ARCHITECTURE','unknown') if os.name=='nt' else platform.machine()}}
        if include_gpu and (refresh or _GPU is None):
            _GPU = _gpu()
        result = copy.deepcopy(_STATIC)
        if include_gpu:
            result['gpu'] = copy.deepcopy(_GPU)
    result['memory'] = _memory()
    result['observed_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return result


def plan_resources(mode='day', workers='auto', snapshot=None, max_workers=None):
    """Return a CPU/RAM bound, preserving a validated manual request as a cap."""
    snapshot = snapshot if snapshot is not None else hardware_snapshot()
    logical = max(1, int(snapshot.get('cpu', {}).get('logical_processors') or 1))
    cpu_reserve = max(1, math.ceil(logical * .2)) if logical > 1 else 0
    cpu_limit = max(1, logical - cpu_reserve)
    requested = workers
    automatic = workers is None or workers == 'auto'
    if not automatic and (isinstance(workers, bool) or not isinstance(workers, int) or workers < 1):
        raise ValueError('workers must be auto or a positive integer')
    if max_workers is not None and (isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1):
        raise ValueError('max_workers must be a positive integer')
    # Full-history jobs request three time-share threads per stock and share
    # one upstream service. Their safe cap is therefore primarily I/O, not GPU.
    task_cap = 3 if mode == 'full' else 32
    hard_cap = min(61 if os.name == 'nt' else 64, task_cap, max_workers or 32)
    request_cap = hard_cap if automatic else min(workers, hard_cap)
    memory = snapshot.get('memory', {})
    total, available = memory.get('total_bytes'), memory.get('available_bytes')
    per_worker = WORKER_MEMORY.get(mode, 1024 * MIB)
    reserve = max(256 * MIB, min(384 * MIB, int(total * .02))) if total else 384 * MIB
    memory_capacity = max(0, (int(total) - reserve) // per_worker) if total else 1
    memory_limit = max(0, (int(available) - reserve) // per_worker) if available is not None else 1
    capacity = max(1, min(cpu_limit, request_cap, memory_capacity))
    admission = min(capacity, memory_limit)
    chosen = max(1, admission)
    bottlenecks = []
    if admission == 0:
        bottlenecks.append('memory_pressure')
    elif memory_limit < min(cpu_limit, request_cap):
        bottlenecks.append('available_memory')
    if request_cap < cpu_limit:
        bottlenecks.append('upstream_limit' if mode == 'full' else 'requested_limit')
    if not total or available is None:
        bottlenecks.append('memory_probe_unavailable')
    reason = ('可用内存不足，暂缓派发新股票，已有计算继续保存结果' if not admission else
              f'按CPU与可用内存安排{chosen}个计算进程')
    return {'mode': mode, 'policy': 'auto' if automatic else 'manual', 'requested_workers': requested,
            'workers': chosen, 'effective_workers': chosen, 'capacity_workers': capacity,
            'admission_workers': admission, 'can_start': admission > 0,
            'cpu_limit': cpu_limit, 'cpu_reserved_logical': cpu_reserve,
            'memory_limit': memory_limit, 'memory_capacity': memory_capacity,
            'memory_reserve_bytes': reserve, 'per_worker_memory_bytes': per_worker,
            'memory_total_bytes': total, 'memory_available_bytes': available,
            'hard_limit': hard_cap, 'bottlenecks': bottlenecks, 'reason': reason,
            'gpu_enabled': False, 'compute_backend': 'cpu',
            'gpu_reason': '现有递归缠论引擎尚无通过一致性校验的GPU计算后端。',
            'budget_semantics': 'Conservative admission estimate; not a process RSS guarantee.'}


def admission_limit(plan, snapshot=None, active_workers=0):
    """Allowed active stocks now; zero means wait, never terminate workers.

    Available memory already excludes active and idle process RSS. Add only
    *new* worker budgets to active work, leaving the fixed desktop headroom.
    """
    if isinstance(active_workers, bool) or not isinstance(active_workers, int) or active_workers < 0:
        raise ValueError('active_workers must be a nonnegative integer')
    snapshot = snapshot if snapshot is not None else hardware_snapshot()
    available = snapshot.get('memory', {}).get('available_bytes')
    capacity = max(1, int(plan['capacity_workers']))
    if available is None:
        return min(capacity, max(active_workers, 1))
    budget = max(0, int(available) - int(plan['memory_reserve_bytes']))
    additional = budget // int(plan['per_worker_memory_bytes'])
    return max(active_workers, min(capacity, active_workers + additional))
