"""One shared allocation budget for research, previews and replay workers."""
from collections import OrderedDict
from contextlib import contextmanager
from functools import wraps
import ctypes,gc,os,threading,time
from fastapi import HTTPException

_gate=threading.Lock();_condition=threading.Condition();_local=threading.local();_state_guard=threading.Lock()
_state={'active':None,'started':None,'rejected':0,'active_count':0}
_external_reservations={}


def release_memory():
    gc.collect()
    if os.name=='posix':
        try:ctypes.CDLL(None).malloc_trim(0)
        except (AttributeError,OSError):pass


def status():
    with _state_guard:snapshot={**_state}
    try:
        from web.local_resources import inspect
        plan=inspect()
    except Exception as error:
        plan={'profile':'hosted_serial','automatic':False,'workers':1,'max_workers':1,'gpu':{'detected':[]},'memory':{'pressure':'unknown'}}
        plan['error']=f'{type(error).__name__}: {error}'
    snapshot.update(concurrency_limit=plan['workers'],resources=plan)
    return snapshot


def _record_acquire(label):
    with _state_guard:
        _state['active_count']+=1
        _state.update(active=label if _state['active_count']==1 else 'local_parallel_compute',
                      started=_state['started'] or time.monotonic())


def _record_release():
    with _state_guard:
        _state['active_count']=max(0,_state['active_count']-1)
        if not _state['active_count']:_state.update(active=None,started=None)


def reserve_local_allocation(label):
    """Reserve one parent-owned slot for work running in a child process."""
    try:
        from web.local_resources import inspect
        plan=inspect()
    except Exception:
        return None
    if plan['automatic']:
        with _condition:
            try:plan=inspect()
            except Exception:return None
            if not plan['automatic'] or plan['workers']<=0:return None
            with _state_guard:active_count=_state['active_count']
            if active_count>=plan['workers']:return None
            token=object();_external_reservations[token]='local'
            _record_acquire(label)
            return token
    if plan.get('hosting') not in {'local-research','local'} or not _gate.acquire(blocking=False):
        return None
    token=object()
    with _condition:
        _external_reservations[token]='gate'
        _record_acquire(label)
    return token


def release_local_allocation(token):
    """Release a child-process slot exactly once and wake waiting requests."""
    if token is None:return False
    with _condition:
        reservation=_external_reservations.pop(token,None)
        if reservation is None:return False
        _record_release()
        if reservation=='gate':_gate.release()
        _condition.notify_all()
    return True


@contextmanager
def budget(label,*,wait=False):
    if getattr(_local,'depth',0):
        _local.depth+=1
        try:yield
        finally:_local.depth-=1
        return
    local_auto=False
    try:
        from web.local_resources import inspect
        plan=inspect();local_auto=plan['automatic'];limit=plan['workers']
    except Exception:limit=1
    reserved_local_slot=False
    if not local_auto:
        if not _gate.acquire(timeout=120 if wait else .1):
            with _state_guard:_state['rejected']+=1
            raise HTTPException(429,'结构计算正在处理其他请求，请稍后自动重试',headers={'Retry-After':'10'})
    else:
        deadline=time.monotonic()+(120 if wait else .1)
        with _condition:
            while True:
                try:
                    from web.local_resources import inspect
                    plan=inspect()
                except Exception:plan={'workers':1,'automatic':False}
                if not plan['automatic']:
                    if not _gate.acquire(blocking=False):
                        remaining=deadline-time.monotonic()
                        if remaining<=0:
                            with _state_guard:_state['rejected']+=1
                            raise HTTPException(429,'结构计算正在处理其他请求，请稍后自动重试',headers={'Retry-After':'10'})
                        _condition.wait(timeout=min(.1,remaining));continue
                    break
                limit=plan['workers']
                with _state_guard:active_count=_state['active_count']
                if active_count<limit:
                    with _state_guard:_state['active_count']+=1
                    reserved_local_slot=True
                    break
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    with _state_guard:_state['rejected']+=1
                    raise HTTPException(429,'本机自动算力预算已满；任务已排队等待空槽',headers={'Retry-After':'2'})
                _condition.wait(timeout=min(.1,remaining))
    _local.depth=1
    if not reserved_local_slot:_record_acquire(label)
    try:yield
    finally:
        _local.depth=0
        _record_release()
        release_memory()
        if reserved_local_slot:
            with _condition:_condition.notify_all()
        else:
            _gate.release()
            with _condition:_condition.notify_all()


def bounded(label,*,wait=False):
    def decorate(function):
        @wraps(function)
        def call(*args,**kwargs):
            with budget(label,wait=wait):return function(*args,**kwargs)
        return call
    return decorate


class ByteCache:
    """Hold only compressed immutable payloads, evicting before insertion."""
    def __init__(self,max_bytes=8*1024*1024,max_entries=2):
        self.max_bytes=max_bytes;self.max_entries=max_entries;self.bytes=0;self.items=OrderedDict();self.lock=threading.RLock()
    def clear(self):
        with self.lock:self.items.clear();self.bytes=0
    def get(self,key):
        with self.lock:
            if key not in self.items:return None
            self.items.move_to_end(key);return self.items[key]
    def put(self,key,value):
        if not isinstance(value,bytes):raise TypeError('Cache accepts immutable bytes only')
        with self.lock:
            previous=self.items.pop(key,None)
            if previous is not None:self.bytes-=len(previous)
            if len(value)>self.max_bytes:return
            while self.items and (self.bytes+len(value)>self.max_bytes or len(self.items)>=self.max_entries):
                _,old=self.items.popitem(last=False);self.bytes-=len(old)
            self.items[key]=value;self.bytes+=len(value)
