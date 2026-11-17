"""Preflight directory inventories in the background instead of blocking HTTP."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import threading
import time
from . import history_archive

LOCK=threading.RLock();POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='history-inventory')
JOBS=OrderedDict()


def request_inventory(period='day',symbol=None,offset=0,limit=200):
    history_archive._period(period);history_archive._symbol(symbol)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=1000:
        raise ValueError('历史目录分页参数无效')
    ident=hashlib.sha256(json.dumps([period,symbol,offset,limit]).encode()).hexdigest()
    with LOCK:
        prior=JOBS.get(ident)
        if prior is None or prior.get('state')!='building' and time.monotonic()-prior['at']>120:
            JOBS[ident]={'state':'building','period':period,'symbol':symbol,'at':time.monotonic()}
            POOL.submit(_run,ident,period,symbol,offset,limit)
        while len(JOBS)>32:
            old=next((k for k,v in JOBS.items() if v['state']!='building'),None)
            if old is None:break
            JOBS.pop(old)
    return status(ident)


def _run(ident,period,symbol,offset,limit):
    try:
        value=history_archive.history_inventory(period,symbol,offset=offset,limit=limit)
        with LOCK:JOBS[ident].update(state='ready',value=value,at=time.monotonic())
    except Exception as exc:
        with LOCK:JOBS[ident].update(state='failed',error=f'{type(exc).__name__}: {exc}',at=time.monotonic())


def status(ident):
    if not re.fullmatch('[0-9a-f]{64}',ident):raise ValueError('历史清单任务标识无效')
    with LOCK:task=dict(JOBS.get(ident) or {})
    if not task:raise ValueError('历史清单任务不存在')
    if task['state']=='ready':return {'state':'ready',**task['value']}
    task.pop('at',None)
    return {**task,'id':ident,'status_url':'/api/history/inventory/status/'+ident}
