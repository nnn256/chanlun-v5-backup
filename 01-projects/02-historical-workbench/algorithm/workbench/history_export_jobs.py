"""Background local history ZIP jobs with bounded browser polling metadata."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import threading
from collections import OrderedDict

from . import history_archive

LOCK=threading.RLock();POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='history-export')
JOBS=OrderedDict()


def start(body):
    scope=body.get('scope','all');period=body.get('period','day');symbol=body.get('symbol')
    if scope not in {'all','stock'}:raise ValueError('历史导出范围仅支持全部或单股')
    history_archive._period(period);history_archive._symbol(symbol)
    if scope=='stock' and symbol is None:raise ValueError('单股导出需提供股票代码')
    if scope=='all' and symbol is not None:raise ValueError('全部导出不能同时限定单股')
    ident=hashlib.sha256(json.dumps([scope,period,symbol]).encode()).hexdigest()
    with LOCK:
        prior=JOBS.get(ident)
        if prior and prior['state']=='building':return status(ident)
        JOBS[ident]={'id':ident,'state':'building','scope':scope,'period':period,'symbol':symbol}
        POOL.submit(_run,ident,scope,period,symbol)
        while len(JOBS)>32:
            old=next((k for k,v in JOBS.items() if v['state']!='building'),None)
            if old is None:break
            JOBS.pop(old)
    return status(ident)


def _run(ident,scope,period,symbol):
    try:
        def progress(value):
            with LOCK:JOBS[ident]['progress']=value
        receipt=history_archive.create_export(scope,period,symbol,progress=progress)
        with LOCK:JOBS[ident].update(receipt)
    except Exception as exc:
        with LOCK:JOBS[ident].update(state='failed',error=f'{type(exc).__name__}: {exc}')


def status(ident):
    if not re.fullmatch('[0-9a-f]{64}',ident):raise ValueError('历史导出任务标识无效')
    with LOCK:value=dict(JOBS.get(ident) or {})
    if not value:raise ValueError('历史导出任务不存在')
    value.pop('path',None);value['id']=ident;value['status_url']='/api/history/exports/'+ident
    if value['state'] in {'ready','partial'}:value['download_url']='/api/history/exports/'+ident+'/download'
    return value


def download_path(ident):
    value=status(ident)
    if value['state'] not in {'ready','partial'}:raise ValueError('历史ZIP尚未生成完成')
    return history_archive.export_download_path(value['name'])
