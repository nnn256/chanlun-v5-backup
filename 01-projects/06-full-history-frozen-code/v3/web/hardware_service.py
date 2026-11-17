"""Bounded CPU/GPU indicator calls shared by the local research and quote APIs."""
import threading
import time

from core.hardware_compute import hardware_status,resource_plan
from core.gpu_macd import batch_macd,CudaUnavailable

_BATCH_LOCK=threading.Lock()


def resources():
    state=hardware_status(include_gpu=True)
    return {'hardware':state,'plan':resource_plan(status=state),
        'gpu_indicator_adapter':'cuda_driver_float64_macd_v1',
        'gpu_kernel_active':False,'structure_backend':'cpu',
        'network_accelerated_by_gpu':False,
        'scope':'CUDA is used only for compatible batch MACD calls; structural rules are unchanged'}


def compute(payload):
    if not isinstance(payload,dict):raise ValueError('request must be an object')
    unknown=set(payload)-{'prices','backend','fast','slow','signal','multiplier'}
    if unknown:raise ValueError('unsupported indicator fields: '+','.join(sorted(unknown)))
    values=payload.get('prices')
    if not isinstance(values,list) or any(not isinstance(row,list) for row in values):
        raise ValueError('prices must be a rectangular array of price series')
    if len(values)>1024 or sum(len(row) for row in values)>262144:
        raise ValueError('indicator request exceeds 1024 series or 262144 price observations')
    if not _BATCH_LOCK.acquire(blocking=False):raise RuntimeError('another batch indicator call is running')
    try:
        started=time.perf_counter()
        result=batch_macd(values,backend=payload.get('backend','auto'),
            fast=payload.get('fast',12),slow=payload.get('slow',26),
            signal=payload.get('signal',9),multiplier=payload.get('multiplier',1),max_elements=262144)
        result['values']=list(result['values'])
        result['elapsed_seconds']=round(time.perf_counter()-started,6)
        return result
    finally:_BATCH_LOCK.release()
