"""Standard-library hardware discovery and conservative batch admission.

CPU process admission uses current *available* RAM, affinity and container
limits. GPU discovery reports capability only; it never implies that the
recursive structural engine or a network request is running on that device.
"""
from __future__ import annotations

import copy
import ctypes
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

MIB = 1024 * 1024
GIB = 1024 * MIB
MIN_WORKER_BYTES = 512 * MIB
DEFAULT_WORKER_BYTES = 768 * MIB
OS_RESERVE_BYTES = 1536 * MIB
GPU_PROBE_TTL = 60.0
_GPU_LOCK = threading.Lock()
_GPU_CACHE = None


def _read_text(path):
    try:
        return Path(path).read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        return None


def _positive_int(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number <= 0 or isinstance(value, float) and number != value:
        return None
    return number


def _cpu_quota():
    """Return a cgroup CPU capacity without assuming the host allocation."""
    current = _read_text('/sys/fs/cgroup/cpu.max')
    if current:
        parts = current.split()
        if len(parts) == 2 and parts[0] != 'max':
            quota, period = _positive_int(parts[0]), _positive_int(parts[1])
            if quota and period:
                return quota / period, 'cgroup_v2'
    quota = _read_text('/sys/fs/cgroup/cpu/cpu.cfs_quota_us')
    period = _read_text('/sys/fs/cgroup/cpu/cpu.cfs_period_us')
    quota, period = _positive_int(quota), _positive_int(period)
    if quota and period:
        return quota / period, 'cgroup_v1'
    return None, None


def _cpu_snapshot():
    logical = _positive_int(os.cpu_count()) or 1
    affinity = None
    try:
        affinity = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        if os.name == 'nt':
            try:
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.GetCurrentProcess.restype = ctypes.c_void_p
                kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
                process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
                if kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(),
                        ctypes.byref(process_mask), ctypes.byref(system_mask)):
                    affinity = int(process_mask.value).bit_count()
            except (AttributeError, OSError):
                pass
    quota, quota_source = _cpu_quota()
    limits = [logical]
    if affinity:
        limits.append(affinity)
    if quota is not None:
        # A fractional quota cannot sustain another full CPU-bound process.
        limits.append(max(1, math.floor(quota)))
    effective = max(1, min(limits))
    return {'logical': logical, 'affinity': affinity,
            'quota_cpus': quota, 'quota_source': quota_source,
            'logical_limit': effective, 'reserved_for_ui': 1}


def _memory_snapshot():
    total = available = None
    source = 'unknown'
    if os.name == 'nt':
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    'total_phys', 'available_phys', 'total_page', 'available_page',
                    'total_virtual', 'available_virtual', 'extended')]
        try:
            value = MemoryStatus()
            value.length = ctypes.sizeof(value)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            if kernel.GlobalMemoryStatusEx(ctypes.byref(value)):
                total, available = int(value.total_phys), int(value.available_phys)
                source = 'windows_globalmemorystatusex'
        except (AttributeError, OSError):
            pass
    else:
        text = _read_text('/proc/meminfo')
        if text:
            values = dict(re.findall(r'^(MemTotal|MemAvailable):\s+(\d+)\s+kB$', text, re.M))
            total = int(values['MemTotal']) * 1024 if 'MemTotal' in values else None
            available = int(values['MemAvailable']) * 1024 if 'MemAvailable' in values else None
            source = 'proc_meminfo'
        if total is None or available is None:
            try:
                page = os.sysconf('SC_PAGE_SIZE')
                if total is None:
                    total = page * os.sysconf('SC_PHYS_PAGES')
                if available is None:
                    available = page * os.sysconf('SC_AVPHYS_PAGES')
                source = 'sysconf'
            except (AttributeError, OSError, ValueError):
                pass
    limit = _read_text('/sys/fs/cgroup/memory.max')
    used = _read_text('/sys/fs/cgroup/memory.current')
    cgroup = 'v2'
    if not limit:
        limit = _read_text('/sys/fs/cgroup/memory/memory.limit_in_bytes')
        used = _read_text('/sys/fs/cgroup/memory/memory.usage_in_bytes')
        cgroup = 'v1'
    if limit and limit != 'max':
        maximum = _positive_int(limit)
        try:
            consumed = int(used) if used is not None else None
        except (ValueError, OverflowError):
            consumed = None
        if maximum and maximum < 1 << 60:
            total = min(total, maximum) if total is not None else maximum
            if consumed is not None and consumed >= 0:
                remainder = max(0, maximum - consumed)
                available = min(available, remainder) if available is not None else remainder
            source += '+cgroup_' + cgroup
    total = max(0, int(total)) if total is not None else None
    available = max(0, int(available)) if available is not None else None
    if available is not None and total is not None:
        available = min(available, total)
    return {'total_bytes': total, 'available_bytes': available, 'source': source}


def _cuda_driver():
    try:
        driver = ctypes.WinDLL('nvcuda.dll') if os.name == 'nt' else ctypes.CDLL('libcuda.so.1')
        driver.cuInit.argtypes = [ctypes.c_uint]
        driver.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
        status = int(driver.cuInit(0))
        if status:
            return {'available': False, 'device_count': 0, 'error': 'cuInit status ' + str(status)}
        count = ctypes.c_int()
        status = int(driver.cuDeviceGetCount(ctypes.byref(count)))
        return {'available': status == 0 and count.value > 0,
                'device_count': max(0, count.value) if status == 0 else 0,
                **({'error': 'cuDeviceGetCount status ' + str(status)} if status else {})}
    except (OSError, AttributeError) as exc:
        return {'available': False, 'device_count': 0, 'error': f'{type(exc).__name__}: {exc}'}


def _probe_gpu():
    report = {'devices': [], 'probe': 'not_detected', 'cuda_driver': _cuda_driver(),
              'kernel_active': False, 'recursive_engine_backend': 'cpu',
              'network_accelerated': False}
    binary = shutil.which('nvidia-smi')
    if binary:
        try:
            result = subprocess.run([binary,
                '--query-gpu=name,memory.total,memory.free,driver_version',
                '--format=csv,noheader,nounits'], capture_output=True, text=True,
                timeout=2, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    fields = [value.strip() for value in line.split(',')]
                    if len(fields) != 4:
                        continue
                    try:
                        total, free = int(fields[1]) * MIB, int(fields[2]) * MIB
                    except ValueError:
                        continue
                    report['devices'].append({'name': fields[0],
                        'memory_total_bytes': max(0, total), 'memory_free_bytes': max(0, free),
                        'driver_version': fields[3]})
                report['probe'] = 'nvidia-smi'
            else:
                report['probe_error'] = f'nvidia-smi exit {result.returncode}'
        except (OSError, subprocess.TimeoutExpired) as exc:
            report['probe_error'] = f'{type(exc).__name__}: {exc}'
    report['detected'] = bool(report['devices']) or report['cuda_driver']['device_count'] > 0
    return report


def _gpu_status():
    global _GPU_CACHE
    now = time.monotonic()
    with _GPU_LOCK:
        if _GPU_CACHE is None or now - _GPU_CACHE[0] >= GPU_PROBE_TTL:
            _GPU_CACHE = (now, _probe_gpu())
        result = copy.deepcopy(_GPU_CACHE[1])
        result['probe_age_seconds'] = round(max(0, now - _GPU_CACHE[0]), 3)
        return result


def hardware_status(include_gpu=True):
    """Inspect current CPU/RAM; GPU process/driver discovery is cached 60 s."""
    gpu = _gpu_status() if include_gpu else {'detected': None, 'probe': 'not_requested',
        'kernel_active': False, 'recursive_engine_backend': 'cpu', 'network_accelerated': False}
    return {'cpu': _cpu_snapshot(), 'memory': _memory_snapshot(), 'gpu': gpu,
            'scope': {'quotes': 'network_io', 'structure': 'sequential_cpu_per_symbol',
                      'independent_symbols': 'bounded_cpu_processes',
                      'gpu': 'capability_only; a compatible batch kernel must be selected separately'}}


def resource_plan(task_count=None, requested='auto', per_worker_bytes=None, mode=None, *,
                  status=None, env=None, tasks=None, requested_workers=None):
    """Plan independent CPU tasks without claiming GPU execution.

    `requested` accepts ``auto``, ``cpu``, ``gpu`` or a positive CPU worker
    integer. The string is a backend preference, not permission to bypass the
    CPU/RAM budget. GPU kernels use their own batch/VRAM admission.
    """
    settings = os.environ if env is None else env
    warnings = []
    if tasks is not None:
        if task_count is not None and tasks != task_count:
            raise ValueError('task_count and tasks disagree')
        task_count = tasks
    if requested_workers is not None:
        requested = requested_workers
    if task_count is not None and (isinstance(task_count, bool) or not isinstance(task_count, int) or task_count < 0):
        raise ValueError('task_count must be a nonnegative integer')
    if requested == 'auto' and settings.get('LIANGCE_COMPUTE_WORKERS'):
        override = settings['LIANGCE_COMPUTE_WORKERS']
        parsed = _positive_int(override)
        if parsed:
            requested = parsed
        elif override != 'auto':
            warnings.append('invalid LIANGCE_COMPUTE_WORKERS ignored')
    if isinstance(requested, str) and requested.isdecimal():
        requested = int(requested)
    if requested not in ('auto', 'cpu', 'gpu') and (isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0):
        raise ValueError('requested must be auto, cpu, gpu or a positive worker count')
    explicit_mode = mode is not None
    mode = mode or settings.get('LIANGCE_COMPUTE_MODE', 'auto')
    if mode not in {'auto', 'eco', 'performance', 'mem'}:
        if explicit_mode:
            raise ValueError('mode must be auto, eco, performance or mem')
        warnings.append('invalid LIANGCE_COMPUTE_MODE ignored');mode = 'auto'
    def setting(name, fallback, minimum=1):
        if name not in settings:
            return fallback
        parsed = _positive_int(settings[name])
        if parsed is None or parsed < minimum:
            warnings.append('invalid ' + name + ' ignored');return fallback
        return parsed
    reserve = max(OS_RESERVE_BYTES, setting('LIANGCE_COMPUTE_RESERVE_MB', 1536) * MIB)
    if per_worker_bytes is None:
        per_worker = setting('LIANGCE_COMPUTE_WORKER_MB', DEFAULT_WORKER_BYTES // MIB) * MIB
    else:
        if isinstance(per_worker_bytes, bool) or not isinstance(per_worker_bytes, int) or per_worker_bytes <= 0:
            raise ValueError('per_worker_bytes must be a positive integer')
        per_worker = per_worker_bytes
    per_worker = max(MIN_WORKER_BYTES, per_worker)
    snapshot = copy.deepcopy(status) if status is not None else hardware_status(include_gpu=requested == 'gpu')
    cpu = snapshot.get('cpu', {})
    cpu_limit = _positive_int(cpu.get('logical_limit', cpu.get('effective', cpu.get('logical')))) or 1
    # One logical CPU remains available for the interface/OS. Serial work stays
    # inline, avoiding a spawned copy of the Python environment under pressure.
    usable_cpu = max(1, cpu_limit - 1)
    mode_cap = {'auto': 8, 'eco': 4, 'performance': 16, 'mem': 2}[mode]
    if mode == 'eco':
        usable_cpu = max(1, usable_cpu // 2)
    env_cap = setting('LIANGCE_COMPUTE_MAX_WORKERS', mode_cap)
    cpu_cap = max(1, min(usable_cpu, mode_cap, env_cap, 32))
    memory = snapshot.get('memory', {})
    available = memory.get('available_bytes')
    if isinstance(available, bool) or not isinstance(available, int) or available < 0:
        available = None
    if available is None:
        memory_cap, memory_reason = 1, 'memory_unknown'
    elif available < GIB:
        memory_cap, memory_reason = 1, 'memory_pressure'
    else:
        memory_cap = max(1, (available - reserve) // per_worker)
        memory_reason = 'memory_limited' if memory_cap < cpu_cap else 'available_memory'
    maximum = min(cpu_cap, memory_cap)
    if task_count is not None:
        maximum = min(maximum, task_count)
    requested_count = requested if isinstance(requested, int) and not isinstance(requested, bool) else maximum
    workers = min(maximum, requested_count)
    reasons = [memory_reason]
    if requested_count > maximum:
        reasons.append('requested_workers_clamped')
    if task_count == 0:
        reasons.append('no_tasks')
    if requested == 'gpu':
        reasons.append('gpu_requires_compatible_batch_kernel')
    reason = 'no_tasks' if task_count == 0 else memory_reason if memory_reason in {'memory_unknown', 'memory_pressure', 'memory_limited'} else 'cpu_limited'
    return {'profile': 'hardware_compute_v1', 'mode': mode, 'automatic': requested in ('auto', 'cpu', 'gpu'),
            'requested': requested, 'requested_workers': requested_count,
            'workers': workers, 'max_workers': maximum,
            'start_method': 'inline' if workers <= 1 else 'spawn',
            'memory_available_bytes': available, 'reserve_bytes': reserve, 'per_worker_bytes': per_worker,
            'reason': reason, 'reasons': reasons, 'warnings': warnings,
            'cpu': {**cpu, 'planned_limit': cpu_cap},
            'memory': {**memory, 'available_bytes': available, 'reserve_bytes': reserve,
                       'per_worker_bytes': per_worker, 'worker_limit': memory_cap,
                       'pressure': memory_reason},
            'gpu': snapshot.get('gpu', {'detected': None, 'probe': 'not_requested', 'kernel_active': False}),
            'scope': snapshot.get('scope', {})}
