"""Bounded optional indicator batches; recursive structures remain on CPU."""
import threading
import time

from chanmodel.gpu_macd import batch_macd,CudaUnavailable

_LOCK=threading.Lock()


def compute(payload):
    if not isinstance(payload,dict):raise ValueError('request must be an object')
    unknown=set(payload)-{'prices','backend','fast','slow','signal','multiplier'}
    if unknown:raise ValueError('unsupported batch indicator fields')
    values=payload.get('prices')
    if not isinstance(values,list) or any(not isinstance(row,list) for row in values):
        raise ValueError('prices must be a rectangular list of series')
    if len(values)>1024 or sum(len(row) for row in values)>262144:
        raise ValueError('batch exceeds 1024 series or 262144 observations')
    if not _LOCK.acquire(blocking=False):raise ValueError('another batch indicator calculation is active')
    try:
        start=time.perf_counter()
        value=batch_macd(values,backend=payload.get('backend','auto'),max_elements=262144,
            **{key:payload[key] for key in ['fast','slow','signal','multiplier'] if key in payload})
        value['values']=list(value['values']);value['elapsed_seconds']=round(time.perf_counter()-start,6)
        return value
    finally:_LOCK.release()
