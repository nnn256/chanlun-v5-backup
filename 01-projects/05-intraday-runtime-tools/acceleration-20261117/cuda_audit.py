"""Independent OHLCV integrity and session-extrema audit on the NVIDIA GPU.

Only the CUDA driver is required: no CUDA toolkit or Python GPU packages. The
native Chan replay is not changed. Input columns are open, high, low, close,
volume; all arithmetic uses float64. Invalid flags: 1 price <= 0, 2 OHLC range,
4 negative/non-numeric volume, 8 a non-finite input. Session extrema ignore rows
whose low or high is non-finite; counts still include every input row.
"""
from __future__ import annotations

import ctypes as C
import math
import os
import time


PTX = r'''.version 7.1
.target sm_86
.address_size 64

.visible .entry validate_ohlcv(
    .param .u64 rows, .param .u32 count, .param .u64 flags)
{
 .reg .pred %p<16>;
 .reg .b32 %r<16>;
 .reg .b64 %rd<10>;
 .reg .f64 %fd<12>;
 ld.param.u64 %rd1, [rows];
 ld.param.u32 %r1, [count];
 ld.param.u64 %rd2, [flags];
 mov.u32 %r2, %ctaid.x;
 mov.u32 %r3, %ntid.x;
 mov.u32 %r4, %tid.x;
 mad.lo.u32 %r5, %r2, %r3, %r4;
 setp.ge.u32 %p1, %r5, %r1;
 @%p1 bra V_DONE;
 mul.wide.u32 %rd3, %r5, 40;
 add.u64 %rd4, %rd1, %rd3;
 ld.global.f64 %fd1, [%rd4];
 ld.global.f64 %fd2, [%rd4+8];
 ld.global.f64 %fd3, [%rd4+16];
 ld.global.f64 %fd4, [%rd4+24];
 ld.global.f64 %fd5, [%rd4+32];
 setp.gt.f64 %p2, %fd1, 0d0000000000000000;
 setp.gt.f64 %p3, %fd2, 0d0000000000000000;
 setp.gt.f64 %p4, %fd3, 0d0000000000000000;
 setp.gt.f64 %p5, %fd4, 0d0000000000000000;
 and.pred %p2, %p2, %p3;
 and.pred %p2, %p2, %p4;
 and.pred %p2, %p2, %p5;
 selp.u32 %r6, 0, 1, %p2;
 setp.ge.f64 %p3, %fd1, %fd3;
 setp.ge.f64 %p4, %fd4, %fd3;
 setp.le.f64 %p5, %fd1, %fd2;
 setp.le.f64 %p6, %fd4, %fd2;
 and.pred %p3, %p3, %p4;
 and.pred %p3, %p3, %p5;
 and.pred %p3, %p3, %p6;
 selp.u32 %r7, 0, 2, %p3;
 or.b32 %r6, %r6, %r7;
 setp.ge.f64 %p4, %fd5, 0d0000000000000000;
 selp.u32 %r7, 0, 4, %p4;
 or.b32 %r6, %r6, %r7;
 abs.f64 %fd6, %fd1;
 abs.f64 %fd7, %fd2;
 abs.f64 %fd8, %fd3;
 abs.f64 %fd9, %fd4;
 abs.f64 %fd10, %fd5;
 setp.lt.f64 %p5, %fd6, 0d7FF0000000000000;
 setp.lt.f64 %p6, %fd7, 0d7FF0000000000000;
 setp.lt.f64 %p7, %fd8, 0d7FF0000000000000;
 setp.lt.f64 %p8, %fd9, 0d7FF0000000000000;
 setp.lt.f64 %p9, %fd10, 0d7FF0000000000000;
 and.pred %p5, %p5, %p6;
 and.pred %p5, %p5, %p7;
 and.pred %p5, %p5, %p8;
 and.pred %p5, %p5, %p9;
 selp.u32 %r7, 0, 8, %p5;
 or.b32 %r6, %r6, %r7;
 mul.wide.u32 %rd5, %r5, 4;
 add.u64 %rd6, %rd2, %rd5;
 st.global.u32 [%rd6], %r6;
 V_DONE:
 ret;
}

.visible .entry session_extrema(
 .param .u64 rows, .param .u64 ranges, .param .u32 count,
 .param .u64 lows, .param .u64 highs, .param .u64 finite_counts)
{
 .reg .pred %p<8>;
 .reg .b32 %r<12>;
 .reg .b64 %rd<18>;
 .reg .f64 %fd<8>;
 ld.param.u64 %rd1, [rows];
 ld.param.u64 %rd2, [ranges];
 ld.param.u32 %r1, [count];
 ld.param.u64 %rd3, [lows];
 ld.param.u64 %rd4, [highs];
 ld.param.u64 %rd5, [finite_counts];
 mov.u32 %r2, %ctaid.x;
 mov.u32 %r3, %ntid.x;
 mov.u32 %r4, %tid.x;
 mad.lo.u32 %r5, %r2, %r3, %r4;
 setp.ge.u32 %p1, %r5, %r1;
 @%p1 bra S_DONE;
 mul.wide.u32 %rd6, %r5, 8;
 add.u64 %rd7, %rd2, %rd6;
 ld.global.u32 %r6, [%rd7];
 ld.global.u32 %r7, [%rd7+4];
 mov.f64 %fd1, 0d7FF0000000000000;
 mov.f64 %fd2, 0dFFF0000000000000;
 mov.u32 %r8, 0;
 S_LOOP:
 setp.ge.u32 %p2, %r6, %r7;
 @%p2 bra S_STORE;
 mul.wide.u32 %rd8, %r6, 40;
 add.u64 %rd9, %rd1, %rd8;
 ld.global.f64 %fd3, [%rd9+16];
 ld.global.f64 %fd4, [%rd9+8];
 abs.f64 %fd5, %fd3;
 abs.f64 %fd6, %fd4;
 setp.lt.f64 %p3, %fd5, 0d7FF0000000000000;
 setp.lt.f64 %p4, %fd6, 0d7FF0000000000000;
 and.pred %p3, %p3, %p4;
 @!%p3 bra S_NEXT;
 min.f64 %fd1, %fd1, %fd3;
 max.f64 %fd2, %fd2, %fd4;
 add.u32 %r8, %r8, 1;
 S_NEXT:
 add.u32 %r6, %r6, 1;
 bra S_LOOP;
 S_STORE:
 add.u64 %rd10, %rd3, %rd6;
 add.u64 %rd11, %rd4, %rd6;
 st.global.f64 [%rd10], %fd1;
 st.global.f64 [%rd11], %fd2;
 mul.wide.u32 %rd12, %r5, 4;
 add.u64 %rd13, %rd5, %rd12;
 st.global.u32 [%rd13], %r8;
 S_DONE:
 ret;
}
'''


class CudaError(RuntimeError):
    pass


def prepare_rows(rows, sessions=None):
    converted = []
    for row in rows:
        if len(row) != 5:
            raise ValueError('OHLCV rows require exactly open, high, low, close, volume')
        converted.append(tuple(float(x) for x in row))
    if len(converted) > 0xffffffff:
        raise ValueError('row count exceeds GPU uint32 indexing')
    ranges = [(0, len(converted))] if sessions is None else list(sessions)
    for pair in ranges:
        if len(pair) != 2 or any(type(x) is not int for x in pair):
            raise ValueError('session ranges require integer [start,end) pairs')
        if not 0 <= pair[0] <= pair[1] <= len(converted):
            raise ValueError('session range leaves OHLCV rows')
    return converted, ranges


def cpu_oracle(rows, sessions=None):
    rows, sessions = prepare_rows(rows, sessions)
    flags = []
    for open_, high, low, close, volume in rows:
        bits = (0 if all(x > 0 for x in (open_, high, low, close)) else 1)
        bits |= 0 if open_ >= low and close >= low and open_ <= high and close <= high else 2
        bits |= 0 if volume >= 0 else 4
        bits |= 0 if all(math.isfinite(x) for x in (open_, high, low, close, volume)) else 8
        flags.append(bits)
    extrema = []
    for start, end in sessions:
        finite = [row for row in rows[start:end] if math.isfinite(row[2]) and math.isfinite(row[1])]
        extrema.append({'start': start, 'end': end, 'count': end-start,
                        'finite_extrema_rows': len(finite),
                        'low': min(row[2] for row in finite) if finite else None,
                        'high': max(row[1] for row in finite) if finite else None})
    return {'flags': flags, 'sessions': extrema}


class CudaAuditor:
    """Own one CUDA context; reuse for sequential security/period audits."""
    def __init__(self, device_ordinal=0):
        started = time.perf_counter()
        self.driver = C.WinDLL('nvcuda.dll') if os.name == 'nt' else C.CDLL('libcuda.so.1')
        self.context, self.module = C.c_void_p(), C.c_void_p()
        self._configure()
        try:
            self._check(self.driver.cuInit(0), 'cuInit')
            device = C.c_int()
            self._check(self.driver.cuDeviceGet(C.byref(device), device_ordinal), 'cuDeviceGet')
            label = C.create_string_buffer(256)
            self._check(self.driver.cuDeviceGetName(label, len(label), device), 'cuDeviceGetName')
            total = C.c_size_t()
            self._check(self.driver.cuDeviceTotalMem_v2(C.byref(total), device), 'cuDeviceTotalMem')
            major, minor = C.c_int(), C.c_int()
            self._check(self.driver.cuDeviceGetAttribute(C.byref(major), 75, device), 'compute capability major')
            self._check(self.driver.cuDeviceGetAttribute(C.byref(minor), 76, device), 'compute capability minor')
            if (major.value, minor.value) < (8, 6):
                raise CudaError('this audited PTX requires compute capability 8.6 or newer')
            self.device = {'ordinal': device_ordinal, 'name': label.value.decode('utf-8'),
                           'compute_capability': f'{major.value}.{minor.value}', 'memory_bytes': total.value}
            self._check(self.driver.cuCtxCreate_v2(C.byref(self.context), 0, device), 'cuCtxCreate')
            source = C.create_string_buffer(PTX.encode('ascii') + b'\0')
            self._check(self.driver.cuModuleLoadDataEx(C.byref(self.module), C.cast(source, C.c_void_p), 0, None, None), 'cuModuleLoadDataEx PTX')
            self.validate, self.extrema = C.c_void_p(), C.c_void_p()
            self._check(self.driver.cuModuleGetFunction(C.byref(self.validate), self.module, b'validate_ohlcv'), 'load validation kernel')
            self._check(self.driver.cuModuleGetFunction(C.byref(self.extrema), self.module, b'session_extrema'), 'load extrema kernel')
            self.startup_ms = (time.perf_counter() - started) * 1000
        except BaseException:
            self.close()
            raise

    def _configure(self):
        pointer = C.c_void_p
        signatures = {
            'cuInit': [C.c_uint], 'cuDeviceGet': [C.POINTER(C.c_int), C.c_int],
            'cuDeviceGetName': [pointer, C.c_int, C.c_int],
            'cuDeviceTotalMem_v2': [C.POINTER(C.c_size_t), C.c_int],
            'cuDeviceGetAttribute': [C.POINTER(C.c_int), C.c_int, C.c_int],
            'cuCtxCreate_v2': [C.POINTER(pointer), C.c_uint, C.c_int],
            'cuCtxDestroy_v2': [pointer], 'cuCtxSetCurrent': [pointer], 'cuCtxSynchronize': [],
            'cuModuleLoadDataEx': [C.POINTER(pointer), pointer, C.c_uint, pointer, pointer],
            'cuModuleGetFunction': [C.POINTER(pointer), pointer, C.c_char_p], 'cuModuleUnload': [pointer],
            'cuMemAlloc_v2': [C.POINTER(C.c_ulonglong), C.c_size_t], 'cuMemFree_v2': [C.c_ulonglong],
            'cuMemcpyHtoD_v2': [C.c_ulonglong, pointer, C.c_size_t],
            'cuMemcpyDtoH_v2': [pointer, C.c_ulonglong, C.c_size_t],
            'cuLaunchKernel': [pointer] + [C.c_uint] * 7 + [pointer, pointer, pointer],
            'cuEventCreate': [C.POINTER(pointer), C.c_uint], 'cuEventRecord': [pointer, pointer],
            'cuEventSynchronize': [pointer], 'cuEventElapsedTime': [C.POINTER(C.c_float), pointer, pointer],
            'cuEventDestroy_v2': [pointer], 'cuGetErrorString': [C.c_int, C.POINTER(C.c_char_p)]}
        for name, args in signatures.items():
            function = getattr(self.driver, name)
            function.argtypes, function.restype = args, C.c_int

    def _check(self, code, action):
        if code:
            description = C.c_char_p()
            self.driver.cuGetErrorString(code, C.byref(description))
            raise CudaError(f'{action}: CUDA {code}: {(description.value or b"unknown").decode("utf-8", errors="replace")}')

    def close(self):
        if getattr(self, 'module', None) and self.module.value:
            self.driver.cuModuleUnload(self.module)
            self.module = C.c_void_p()
        if getattr(self, 'context', None) and self.context.value:
            self.driver.cuCtxDestroy_v2(self.context)
            self.context = C.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _launch(self, function, count, arguments):
        params = (C.c_void_p * len(arguments))(*(C.cast(C.byref(value), C.c_void_p) for value in arguments))
        self._check(self.driver.cuLaunchKernel(function, (count + 127) // 128, 1, 1, 128, 1, 1, 0, None, params, None), 'cuLaunchKernel')

    def audit(self, rows, sessions=None, verify_cpu=True):
        started = time.perf_counter()
        rows, sessions = prepare_rows(rows, sessions)
        if not self.context.value:
            raise CudaError('auditor is closed')
        self._check(self.driver.cuCtxSetCurrent(self.context), 'cuCtxSetCurrent')
        count, groups = len(rows), len(sessions)
        allocations, events = [], []
        transfer_in_ms = transfer_out_ms = kernel_ms = 0.
        def alloc(size):
            value = C.c_ulonglong()
            self._check(self.driver.cuMemAlloc_v2(C.byref(value), max(1, size)), 'cuMemAlloc')
            allocations.append(value)
            return value
        def upload(device, host):
            self._check(self.driver.cuMemcpyHtoD_v2(device, C.cast(host, C.c_void_p), C.sizeof(host)), 'cuMemcpyHtoD')
        try:
            host_rows = (C.c_double * max(1, count * 5))(*(value for row in rows for value in row))
            host_ranges = (C.c_uint * max(1, groups * 2))(*(value for pair in sessions for value in pair))
            host_flags = (C.c_uint * max(1, count))()
            host_lows, host_highs = (C.c_double * max(1, groups))(), (C.c_double * max(1, groups))()
            host_finite = (C.c_uint * max(1, groups))()
            device_rows, device_ranges = alloc(C.sizeof(host_rows)), alloc(C.sizeof(host_ranges))
            device_flags, device_lows = alloc(C.sizeof(host_flags)), alloc(C.sizeof(host_lows))
            device_highs, device_finite = alloc(C.sizeof(host_highs)), alloc(C.sizeof(host_finite))
            timer = time.perf_counter()
            upload(device_rows, host_rows); upload(device_ranges, host_ranges)
            transfer_in_ms = (time.perf_counter() - timer) * 1000
            before, after = C.c_void_p(), C.c_void_p()
            self._check(self.driver.cuEventCreate(C.byref(before), 0), 'cuEventCreate'); events.append(before)
            self._check(self.driver.cuEventCreate(C.byref(after), 0), 'cuEventCreate'); events.append(after)
            self._check(self.driver.cuEventRecord(before, None), 'cuEventRecord')
            if count:
                self._launch(self.validate, count, [device_rows, C.c_uint(count), device_flags])
            if groups:
                self._launch(self.extrema, groups, [device_rows, device_ranges, C.c_uint(groups), device_lows, device_highs, device_finite])
            self._check(self.driver.cuEventRecord(after, None), 'cuEventRecord')
            self._check(self.driver.cuEventSynchronize(after), 'cuEventSynchronize')
            elapsed = C.c_float()
            self._check(self.driver.cuEventElapsedTime(C.byref(elapsed), before, after), 'cuEventElapsedTime')
            kernel_ms = elapsed.value
            timer = time.perf_counter()
            for host, device in ((host_flags, device_flags), (host_lows, device_lows), (host_highs, device_highs), (host_finite, device_finite)):
                self._check(self.driver.cuMemcpyDtoH_v2(C.cast(host, C.c_void_p), device, C.sizeof(host)), 'cuMemcpyDtoH')
            transfer_out_ms = (time.perf_counter() - timer) * 1000
            result = {'flags': list(host_flags)[:count], 'sessions': [
                {'start': start, 'end': end, 'count': end-start, 'finite_extrema_rows': host_finite[i],
                 'low': host_lows[i] if host_finite[i] else None, 'high': host_highs[i] if host_finite[i] else None}
                for i, (start, end) in enumerate(sessions)]}
            gpu_total_ms = (time.perf_counter() - started) * 1000
            verified = None
            cpu_ms = None
            if verify_cpu:
                timer = time.perf_counter()
                expected = cpu_oracle(rows, sessions)
                cpu_ms = (time.perf_counter() - timer) * 1000
                verified = result == expected
                if not verified:
                    raise CudaError('GPU audit output differs from independent CPU oracle')
            result.update(device=self.device, backend='cuda_driver_ptx_float64', verified_cpu=verified,
                          invalid_rows=sum(bool(flags) for flags in result['flags']),
                          timings_ms={'context_module_startup': self.startup_ms, 'h2d': transfer_in_ms,
                                      'gpu_kernels': kernel_ms, 'd2h': transfer_out_ms,
                                      'gpu_path_total': gpu_total_ms, 'independent_cpu_oracle': cpu_ms})
            return result
        finally:
            for event in reversed(events):
                self.driver.cuEventDestroy_v2(event)
            for device in reversed(allocations):
                self.driver.cuMemFree_v2(device)


def audit_rows(rows, sessions=None, verify_cpu=True, device_ordinal=0):
    with CudaAuditor(device_ordinal) as auditor:
        return auditor.audit(rows, sessions, verify_cpu)
