"""Optional double-precision batch MACD through the installed CUDA driver.

No toolkit, Torch or CuPy is required. Each stock has a separate CUDA thread;
its time axis remains sequential. This module computes indicators only and
does not replace any recursive Chan structure or signal confirmation rule.
"""
from __future__ import annotations

from array import array
import ctypes
import math
import os
import threading


class CudaUnavailable(RuntimeError):
    pass


PTX=r'''
.version 6.0
.target sm_52
.address_size 64
.visible .entry batch_macd(
    .param .u64 input_ptr, .param .u64 output_ptr,
    .param .u32 series_count, .param .u32 bar_count,
    .param .f64 alpha_fast, .param .f64 alpha_slow,
    .param .f64 alpha_signal, .param .f64 multiplier)
{
    .reg .pred %p<3>;
    .reg .b32 %r<10>;
    .reg .b64 %rd<16>;
    .reg .f64 %fd<18>;
    ld.param.u64 %rd1, [input_ptr];
    ld.param.u64 %rd2, [output_ptr];
    ld.param.u32 %r1, [series_count];
    ld.param.u32 %r2, [bar_count];
    ld.param.f64 %fd1, [alpha_fast];
    ld.param.f64 %fd2, [alpha_slow];
    ld.param.f64 %fd3, [alpha_signal];
    ld.param.f64 %fd4, [multiplier];
    mov.u32 %r3, %ctaid.x;
    mov.u32 %r4, %ntid.x;
    mov.u32 %r5, %tid.x;
    mad.lo.u32 %r6, %r3, %r4, %r5;
    setp.ge.u32 %p1, %r6, %r1;
    @%p1 bra DONE;
    mul.wide.u32 %rd3, %r6, %r2;
    shl.b64 %rd4, %rd3, 3;
    add.u64 %rd5, %rd1, %rd4;
    mul.lo.u64 %rd6, %rd4, 3;
    add.u64 %rd7, %rd2, %rd6;
    ld.global.f64 %fd5, [%rd5];
    mov.f64 %fd6, %fd5;
    mov.f64 %fd7, 0d0000000000000000;
    mov.u32 %r7, 0;
LOOP:
    ld.global.f64 %fd8, [%rd5];
    sub.rn.f64 %fd9, %fd8, %fd5;
    mul.rn.f64 %fd9, %fd1, %fd9;
    add.rn.f64 %fd5, %fd5, %fd9;
    sub.rn.f64 %fd10, %fd8, %fd6;
    mul.rn.f64 %fd10, %fd2, %fd10;
    add.rn.f64 %fd6, %fd6, %fd10;
    sub.rn.f64 %fd11, %fd5, %fd6;
    sub.rn.f64 %fd12, %fd11, %fd7;
    mul.rn.f64 %fd12, %fd3, %fd12;
    add.rn.f64 %fd7, %fd7, %fd12;
    sub.rn.f64 %fd13, %fd11, %fd7;
    mul.rn.f64 %fd13, %fd4, %fd13;
    st.global.f64 [%rd7], %fd11;
    st.global.f64 [%rd7+8], %fd7;
    st.global.f64 [%rd7+16], %fd13;
    add.u64 %rd5, %rd5, 8;
    add.u64 %rd7, %rd7, 24;
    add.u32 %r7, %r7, 1;
    setp.lt.u32 %p2, %r7, %r2;
    @%p2 bra LOOP;
DONE:
    ret;
}
'''


def _parameters(fast,slow,signal,multiplier):
    if (any(isinstance(v,bool) or not isinstance(v,int) for v in (fast,slow,signal)) or
            not 0<fast<slow or signal<1):
        raise ValueError('require integer periods 0 < fast < slow, signal >= 1')
    if isinstance(multiplier,bool) or not isinstance(multiplier,(int,float)) or not math.isfinite(multiplier) or multiplier<=0:
        raise ValueError('multiplier must be finite and positive')
    return 2/(fast+1),2/(slow+1),2/(signal+1),float(multiplier)


def _matrix(values,max_elements):
    if isinstance(max_elements,bool) or not isinstance(max_elements,int) or max_elements<1:
        raise ValueError('max_elements must be positive')
    rows=len(values)
    if rows==0:return array('d'),0,0
    cols=len(values[0])
    if cols==0:raise ValueError('each series must contain at least one observation')
    if rows*cols>max_elements:raise ValueError('batch exceeds configured element budget; use smaller chunks')
    result=array('d')
    for row in values:
        if len(row)!=cols:raise ValueError('batch must be rectangular; never pad missing history')
        for price in row:
            if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:
                raise ValueError('prices must be finite positive numbers')
            result.append(price)
    return result,rows,cols


def _cpu_flat(values,rows,cols,params):
    a,b,c,multiplier=params
    out=array('d',[0.0])*(rows*cols*3)
    for row in range(rows):
        fast=slow=values[row*cols];dea=0.0
        for col in range(cols):
            price=values[row*cols+col]
            fast+=a*(price-fast);slow+=b*(price-slow)
            dif=fast-slow;dea+=c*(dif-dea)
            offset=(row*cols+col)*3
            out[offset]=dif;out[offset+1]=dea;out[offset+2]=multiplier*(dif-dea)
    return out


class CudaMacd:
    """One bounded device context; calls serialize on this instance."""
    def __init__(self):
        self.context=None;self.module=None;self.function=None;self.lock=threading.RLock()
        try:
            driver=ctypes.WinDLL('nvcuda.dll') if os.name=='nt' else ctypes.CDLL('libcuda.so.1')
        except OSError as exc:raise CudaUnavailable('NVIDIA CUDA driver is not installed') from exc
        self.driver=driver
        u=ctypes.c_uint;i=ctypes.c_int;v=ctypes.c_void_p;p=ctypes.POINTER;s=ctypes.c_size_t
        signatures={
            'cuInit':[u], 'cuDeviceGet':[p(i),i],
            'cuDeviceGetName':[v,i,i],
            'cuCtxCreate_v2':[p(v),u,i], 'cuCtxSetCurrent':[v], 'cuCtxDestroy_v2':[v],
            'cuModuleLoadData':[p(v),v], 'cuModuleUnload':[v],
            'cuModuleGetFunction':[p(v),v,ctypes.c_char_p],
            'cuMemAlloc_v2':[p(ctypes.c_uint64),s], 'cuMemFree_v2':[ctypes.c_uint64],
            'cuMemGetInfo_v2':[p(s),p(s)],
            'cuMemcpyHtoD_v2':[ctypes.c_uint64,v,s],
            'cuMemcpyDtoH_v2':[v,ctypes.c_uint64,s],
            'cuLaunchKernel':[v,u,u,u,u,u,u,u,v,p(v),v], 'cuCtxSynchronize':[],
        }
        try:
            for name,args in signatures.items():
                function=getattr(driver,name);function.argtypes=args;function.restype=i
            self._call('cuInit',0)
            device=i();self._call('cuDeviceGet',ctypes.byref(device),0)
            name=ctypes.create_string_buffer(256);self._call('cuDeviceGetName',name,256,device)
            self.device_name=name.value.decode('utf-8',errors='replace')
            ctx=v();self._call('cuCtxCreate_v2',ctypes.byref(ctx),0,device);self.context=ctx
            module=v();source=ctypes.create_string_buffer(PTX.encode())
            self._call('cuModuleLoadData',ctypes.byref(module),source);self.module=module
            function=v();self._call('cuModuleGetFunction',ctypes.byref(function),module,b'batch_macd')
            self.function=function
        except AttributeError as exc:
            self.close()
            raise CudaUnavailable('installed CUDA driver lacks required entry points') from exc
        except Exception:
            self.close();raise

    def _call(self,name,*args):
        result=getattr(self.driver,name)(*args)
        if result:raise CudaUnavailable(f'{name} failed with CUDA status {result}')

    def close(self):
        with self.lock:
            if self.context:
                self.driver.cuCtxSetCurrent(self.context)
                if self.module:self.driver.cuModuleUnload(self.module);self.module=None
                self.driver.cuCtxDestroy_v2(self.context);self.context=None

    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def compute(self,values,rows,cols,params):
        if (any(isinstance(n,bool) or not isinstance(n,int) or not 0<=n<2**32 for n in (rows,cols)) or
                rows and cols==0 or not isinstance(values,array) or values.typecode!='d' or
                len(values)!=rows*cols or len(params)!=4):
            raise ValueError('CUDA input must be a complete float64 rectangular batch')
        if any(not math.isfinite(v) or v<=0 for v in params):raise ValueError('invalid MACD parameters')
        if not rows:return array('d')
        with self.lock:
            if not self.context:raise CudaUnavailable('CUDA context is closed')
            self._call('cuCtxSetCurrent',self.context)
            available=ctypes.c_size_t();total=ctypes.c_size_t()
            self._call('cuMemGetInfo_v2',ctypes.byref(available),ctypes.byref(total))
            needed=len(values)*8*4
            if needed>max(0,available.value-128*1024**2):
                raise CudaUnavailable('not enough free VRAM for bounded input/output buffers')
            input_ptr=ctypes.c_uint64();output_ptr=ctypes.c_uint64()
            result=array('d',[0.0])*(rows*cols*3)
            host_input=(ctypes.c_double*len(values)).from_buffer(values)
            host_output=(ctypes.c_double*len(result)).from_buffer(result)
            try:
                self._call('cuMemAlloc_v2',ctypes.byref(input_ptr),len(values)*8)
                self._call('cuMemAlloc_v2',ctypes.byref(output_ptr),len(result)*8)
                self._call('cuMemcpyHtoD_v2',input_ptr,host_input,len(values)*8)
                args=[input_ptr,output_ptr,ctypes.c_uint(rows),ctypes.c_uint(cols),
                      *(ctypes.c_double(number) for number in params)]
                pointers=(ctypes.c_void_p*len(args))(*(ctypes.cast(ctypes.byref(arg),ctypes.c_void_p) for arg in args))
                self._call('cuLaunchKernel',self.function,(rows+127)//128,1,1,128,1,1,0,None,pointers,None)
                self._call('cuCtxSynchronize')
                self._call('cuMemcpyDtoH_v2',host_output,output_ptr,len(result)*8)
                return result
            finally:
                if output_ptr.value:self.driver.cuMemFree_v2(output_ptr)
                if input_ptr.value:self.driver.cuMemFree_v2(input_ptr)


def batch_macd(values,*,backend='auto',fast=12,slow=26,signal=9,multiplier=1.0,
               max_elements=2_000_000,context=None,minimum_gpu_elements=65_536):
    """Return flat [series,bar,(dif,dea,histogram)] and actual backend metadata.

    Auto uses CPU for small batches and records a CUDA failure before CPU
    recovery. Explicit ``gpu`` requires a successful device calculation.
    """
    if backend not in {'auto','cpu','gpu'}:raise ValueError('backend must be auto, cpu or gpu')
    params=_parameters(fast,slow,signal,multiplier)
    data,rows,cols=_matrix(values,max_elements)
    used='cpu';reason='empty_batch' if not rows else 'small_batch' if backend=='auto' else 'requested_cpu'
    if rows and (backend=='gpu' or backend=='auto' and rows>=128 and rows*cols>=minimum_gpu_elements):
        try:
            if context is None:
                with CudaMacd() as gpu:
                    result=gpu.compute(data,rows,cols,params);device=gpu.device_name
            else:result=context.compute(data,rows,cols,params);device=context.device_name
            used='cuda';reason='requested_gpu' if backend=='gpu' else 'compatible_batch'
        except CudaUnavailable as exc:
            if backend=='gpu':raise
            reason=f'cuda_unavailable: {exc}'
            result=_cpu_flat(data,rows,cols,params);device=None
    else:result=_cpu_flat(data,rows,cols,params);device=None
    if not all(math.isfinite(value) for value in result):raise ValueError('MACD arithmetic overflowed; result is not finite')
    return {'values':result,'shape':(rows,cols,3),'backend':used,'device':device,'reason':reason,
            'dtype':'float64','gpu_kernel_active':used=='cuda','execution_allowed':False,
            'scope':'batch MACD indicator only; recursive structures and trading rules unchanged'}
