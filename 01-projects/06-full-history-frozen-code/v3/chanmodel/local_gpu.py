"""Optional exact integer resampling totals on an installed OpenCL GPU.

No driver or Python package is installed here. Sequential Chan structures stay
on CPU; only independent bootstrap sums enter this kernel. Memory and integer
bounds are checked before touching the device.
"""
from __future__ import annotations

from array import array
import ctypes as ct
import ctypes.util
import math
import os
import time

MAX_BUFFER_BYTES=32*1024*1024
UINT_MAX=2**32-1


class GPUUnavailable(RuntimeError):
    pass


class OpenCLError(RuntimeError):
    pass


def _checked(code,operation):
    if code!=0:raise OpenCLError(f'{operation} failed with OpenCL status {code}')


class _API:
    def __init__(self):
        library='OpenCL.dll' if os.name=='nt' else ctypes.util.find_library('OpenCL')
        if not library:raise GPUUnavailable('OpenCL loader is not installed')
        try:self.lib=(ct.WinDLL if os.name=='nt' else ct.CDLL)(library)
        except OSError as error:raise GPUUnavailable('OpenCL loader unavailable: '+str(error)) from error
        P=ct.c_void_p;U=ct.c_uint32;I=ct.c_int32;S=ct.c_size_t;B=ct.c_uint64
        def bind(name,result,args):
            function=getattr(self.lib,name);function.restype=result;function.argtypes=args
            setattr(self,name,function)
        bind('clGetPlatformIDs',I,[U,ct.POINTER(P),ct.POINTER(U)])
        bind('clGetPlatformInfo',I,[P,U,S,P,ct.POINTER(S)])
        bind('clGetDeviceIDs',I,[P,B,U,ct.POINTER(P),ct.POINTER(U)])
        bind('clGetDeviceInfo',I,[P,U,S,P,ct.POINTER(S)])
        bind('clCreateContext',P,[P,U,ct.POINTER(P),P,P,ct.POINTER(I)])
        bind('clCreateCommandQueue',P,[P,P,B,ct.POINTER(I)])
        bind('clCreateProgramWithSource',P,[P,U,ct.POINTER(ct.c_char_p),ct.POINTER(S),ct.POINTER(I)])
        bind('clBuildProgram',I,[P,U,ct.POINTER(P),ct.c_char_p,P,P])
        bind('clGetProgramBuildInfo',I,[P,P,U,S,P,ct.POINTER(S)])
        bind('clCreateKernel',P,[P,ct.c_char_p,ct.POINTER(I)])
        bind('clCreateBuffer',P,[P,B,S,P,ct.POINTER(I)])
        bind('clSetKernelArg',I,[P,U,S,P])
        bind('clEnqueueNDRangeKernel',I,[P,P,U,ct.POINTER(S),ct.POINTER(S),ct.POINTER(S),U,ct.POINTER(P),ct.POINTER(P)])
        bind('clEnqueueReadBuffer',I,[P,P,U,S,S,P,U,ct.POINTER(P),ct.POINTER(P)])
        bind('clFinish',I,[P])
        bind('clGetEventProfilingInfo',I,[P,U,S,P,ct.POINTER(S)])
        for kind in ('MemObject','Kernel','Program','CommandQueue','Context','Event'):
            bind('clRelease'+kind,I,[P])

    def info(self,handle,key,platform=False):
        call=self.clGetPlatformInfo if platform else self.clGetDeviceInfo
        size=ct.c_size_t();_checked(call(handle,key,0,None,ct.byref(size)),'query info length')
        if not 0<size.value<=1024*1024:raise OpenCLError('invalid driver information length')
        result=ct.create_string_buffer(size.value)
        _checked(call(handle,key,size,result,None),'query info')
        return result.value.decode('utf-8',errors='replace')

    def scalar(self,device,key,kind):
        value=kind();_checked(self.clGetDeviceInfo(device,key,ct.sizeof(value),ct.byref(value),None),'query device property')
        return value.value

    def devices(self):
        count=ct.c_uint32();status=self.clGetPlatformIDs(0,None,ct.byref(count))
        if status==-1001:return []
        _checked(status,'enumerate platforms')
        if count.value>256:raise OpenCLError('unexpected platform count')
        if not count.value:return []
        platforms=(ct.c_void_p*count.value)()
        _checked(self.clGetPlatformIDs(count,platforms,None),'read platforms')
        result=[]
        for platform in platforms:
            n=ct.c_uint32();status=self.clGetDeviceIDs(platform,4,0,None,ct.byref(n))
            if status==-1:continue
            _checked(status,'enumerate GPU devices')
            if not 0<n.value<=256:continue
            devices=(ct.c_void_p*n.value)()
            _checked(self.clGetDeviceIDs(platform,4,n,devices,None),'read GPU devices')
            for device in devices:
                metadata={'backend':'opencl','platform':self.info(platform,0x0902,True),
                    'name':self.info(device,0x102B),'vendor':self.info(device,0x102C),
                    'driver_version':self.info(device,0x102D),'opencl_version':self.info(device,0x102F),
                    'global_memory_bytes':self.scalar(device,0x101F,ct.c_uint64),
                    'max_allocation_bytes':self.scalar(device,0x1010,ct.c_uint64),
                    'available':bool(self.scalar(device,0x1027,ct.c_uint32)),
                    'compiler_available':bool(self.scalar(device,0x1028,ct.c_uint32)),
                    'little_endian':bool(self.scalar(device,0x1026,ct.c_uint32))}
                result.append((device,metadata))
        return sorted(result,key=lambda item:('nvidia' not in item[1]['vendor'].lower(),item[1]['name']))


def probe_gpu():
    try:
        devices=_API().devices()
        usable=[m for _,m in devices if m['available'] and m['compiler_available'] and m['little_endian']]
        if not usable:return {'supported':False,'backend':'opencl','reason':'no available GPU with OpenCL compiler','devices':[m for _,m in devices]}
        return {'supported':True,**usable[0],'devices':[m for _,m in devices],
            'maximum_buffer_bytes':MAX_BUFFER_BYTES,'operation':'uint32 bootstrap totals only'}
    except (GPUUnavailable,OpenCLError,AttributeError,OSError) as error:
        return {'supported':False,'backend':'opencl','reason':str(error),'devices':[]}


def recommend_backend(cpu_wall_ms,gpu_wall_ms,minimum_speedup=1.10):
    """Choose a backend only from measured end-to-end timings for this workload."""
    values=(cpu_wall_ms,gpu_wall_ms,minimum_speedup)
    if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) for value in values):
        raise ValueError('timings and speedup threshold must be finite numbers')
    if cpu_wall_ms<=0 or gpu_wall_ms<0 or minimum_speedup<1:
        raise ValueError('CPU time must be positive, GPU time nonnegative, speedup threshold >=1')
    speedup=cpu_wall_ms/gpu_wall_ms if gpu_wall_ms>0 else math.inf
    return {'backend':'opencl' if speedup>=minimum_speedup else 'cpu',
            'cpu_wall_ms':float(cpu_wall_ms),'gpu_wall_ms':float(gpu_wall_ms),
            'measured_speedup':speedup,'minimum_speedup':float(minimum_speedup),
            'basis':'measured end-to-end timing including host conversion and transfers'}


def _validate(counts,selections):
    if not isinstance(counts,(list,tuple)) or not counts:raise ValueError('counts must be a nonempty row sequence')
    if not isinstance(selections,(list,tuple)) or not selections:raise ValueError('selections must be a nonempty row sequence')
    if not isinstance(counts[0],(list,tuple)) or not counts[0]:raise ValueError('counts need at least one metric')
    if not isinstance(selections[0],(list,tuple)) or not selections[0]:raise ValueError('each selection needs at least one index')
    symbols=len(counts);metrics=len(counts[0]);reps=len(selections);draws=len(selections[0])
    if max(symbols,metrics,reps,draws)>UINT_MAX or reps*metrics>UINT_MAX:raise ValueError('dimensions exceed uint32')
    size=4*(symbols*metrics+reps*draws+reps*metrics)
    if size>MAX_BUFFER_BYTES:raise ValueError('combined GPU buffers exceed 32 MiB limit')
    maxima=[0]*metrics
    for row in counts:
        if not isinstance(row,(list,tuple)) or len(row)!=metrics:raise ValueError('counts must be rectangular')
        for i,value in enumerate(row):
            if type(value) is not int or not 0<=value<=UINT_MAX:raise ValueError('counts require uint32 integers; booleans are rejected')
            maxima[i]=max(maxima[i],value)
    if any(value*draws>UINT_MAX for value in maxima):raise ValueError('possible uint32 sum overflow')
    for row in selections:
        if not isinstance(row,(list,tuple)) or len(row)!=draws:raise ValueError('selections must be rectangular')
        if any(type(index) is not int or not 0<=index<symbols for index in row):raise ValueError('selection index outside count rows')
    return symbols,metrics,reps,draws,size


KERNEL=b'''
__kernel void bootstrap_totals(__global const uint *counts,
    __global const uint *selections, __global uint *output,
    const uint metrics, const uint draws) {
    const size_t id=get_global_id(0);
    const size_t rep=id/metrics;
    const uint metric=id%metrics;
    uint total=0;
    for (uint j=0;j<draws;j++) {
        const uint symbol=selections[rep*draws+j];
        total+=counts[(size_t)symbol*metrics+metric];
    }
    output[id]=total;
}
'''


class OpenCLBootstrap:
    def __init__(self):
        self.api=None;self.device=None;self.context=None;self.queue=None;self.program=None;self.kernel=None
        self.metadata=None;self.last_timing=None;self.closed=False

    def _initialize(self):
        if self.closed:raise RuntimeError('GPU session is closed')
        if self.kernel:return
        self.api=_API();devices=[x for x in self.api.devices() if x[1]['available'] and x[1]['compiler_available'] and x[1]['little_endian']]
        if not devices:raise GPUUnavailable('no supported OpenCL GPU')
        self.device,self.metadata=devices[0];device=ct.c_void_p(self.device);error=ct.c_int32()
        try:
            self.context=self.api.clCreateContext(None,1,ct.byref(device),None,None,ct.byref(error));_checked(error.value,'create context')
            self.queue=self.api.clCreateCommandQueue(self.context,device,2,ct.byref(error));_checked(error.value,'create queue')
            source=ct.c_char_p(KERNEL);size=ct.c_size_t(len(KERNEL))
            self.program=self.api.clCreateProgramWithSource(self.context,1,ct.byref(source),ct.byref(size),ct.byref(error));_checked(error.value,'create program')
            status=self.api.clBuildProgram(self.program,1,ct.byref(device),None,None,None)
            if status:
                n=ct.c_size_t();self.api.clGetProgramBuildInfo(self.program,device,0x1183,0,None,ct.byref(n))
                log=ct.create_string_buffer(min(n.value,1024*1024) or 1)
                self.api.clGetProgramBuildInfo(self.program,device,0x1183,len(log),log,None)
                raise OpenCLError(f'build kernel failed ({status}): '+log.value.decode(errors='replace'))
            self.kernel=self.api.clCreateKernel(self.program,b'bootstrap_totals',ct.byref(error));_checked(error.value,'create kernel')
        except BaseException:
            self.close();raise

    def totals(self,counts,selections):
        symbols,metrics,reps,draws,size=_validate(counts,selections)
        started=time.perf_counter();self._initialize()
        flattened=array('I',(x for row in counts for x in row));indices=array('I',(x for row in selections for x in row));output=array('I',[0])*(reps*metrics)
        if flattened.itemsize!=4:raise RuntimeError('host uint32 layout unavailable')
        handles=[];event=ct.c_void_p();error=ct.c_int32();a=self.api
        try:
            for values,flags in ((flattened,4|32),(indices,4|32),(output,2)):
                nbytes=len(values)*4
                if nbytes>self.metadata['max_allocation_bytes']:raise ValueError('buffer exceeds GPU allocation limit')
                host=(ct.c_uint32*len(values)).from_buffer(values)
                handle=a.clCreateBuffer(self.context,flags,nbytes,ct.cast(host,ct.c_void_p) if flags&32 else None,ct.byref(error))
                _checked(error.value,'create buffer');handles.append(handle)
            args=[ct.c_void_p(h) for h in handles]+[ct.c_uint32(metrics),ct.c_uint32(draws)]
            for i,value in enumerate(args):_checked(a.clSetKernelArg(self.kernel,i,ct.sizeof(value),ct.byref(value)),'set kernel argument')
            work=ct.c_size_t(reps*metrics)
            _checked(a.clEnqueueNDRangeKernel(self.queue,self.kernel,1,None,ct.byref(work),None,0,None,ct.byref(event)),'enqueue kernel')
            target=(ct.c_uint32*len(output)).from_buffer(output)
            _checked(a.clEnqueueReadBuffer(self.queue,handles[2],1,0,len(output)*4,target,0,None,None),'read result')
            begin=ct.c_uint64();end=ct.c_uint64();kernel_ms=None
            if (a.clGetEventProfilingInfo(event,0x1282,8,ct.byref(begin),None)==0 and
                a.clGetEventProfilingInfo(event,0x1283,8,ct.byref(end),None)==0):kernel_ms=(end.value-begin.value)/1e6
            result=[list(output[i*metrics:(i+1)*metrics]) for i in range(reps)]
            self.last_timing={'wall_ms':(time.perf_counter()-started)*1000,'kernel_ms':kernel_ms,
                'combined_buffer_bytes':size,'replicates':reps,'symbols':symbols,'draws_per_replicate':draws,'metrics':metrics}
            return result
        finally:
            if event.value:a.clReleaseEvent(event)
            for handle in reversed(handles):a.clReleaseMemObject(handle)

    def close(self):
        if self.api:
            for attr,kind in (('kernel','Kernel'),('program','Program'),('queue','CommandQueue'),('context','Context')):
                handle=getattr(self,attr)
                if handle:getattr(self.api,'clRelease'+kind)(handle);setattr(self,attr,None)
        self.closed=True

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
