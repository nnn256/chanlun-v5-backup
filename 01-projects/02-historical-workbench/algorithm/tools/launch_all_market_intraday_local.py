"""Launch only this local frozen market run; preserve production and prior runs."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--base-url',default='http://127.0.0.1:65004')
    p.add_argument('--cutoff',default='2026-11-13T15:00:00+08:00')
    p.add_argument('--resume',action='store_true')
    a=p.parse_args();root=a.root.resolve();code=root/'frozen-code'
    source=root/'source-universe/universe.json'
    if not code.is_dir() or not source.is_file():raise ValueError('frozen source/universe missing')
    receipt=root/'launch-receipt.json'
    if receipt.exists() and not a.resume:raise ValueError('launch already recorded; use --resume only after prior processes exit')
    if a.resume and receipt.exists():
        old=json.loads(receipt.read_text(encoding='utf-8'))
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            kernel.OpenProcess.restype=wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            for part in old['processes']:
                if part['name']=='progress':continue
                handle=kernel.OpenProcess(0x1000,False,part['pid'])
                if handle:
                    exit_code=wintypes.DWORD()
                    try:
                        if kernel.GetExitCodeProcess(handle,ctypes.byref(exit_code)) and exit_code.value==259:
                            raise ValueError(f"recorded {part['name']} process is still running; use status page")
                    finally:kernel.CloseHandle(handle)
    logs=root/'logs';logs.mkdir(exist_ok=True)
    capture=[sys.executable,'-u',str(code/'tools/capture_market_intraday.py'),
             '--universe',str(source),'--output',str(root/'acquisition'),
             '--cutoff',a.cutoff,'--base-url',a.base_url,'--workers','1',
             '--min-free-gb','10','--quarantine-zero-activity']
    replay=[sys.executable,'-u',str(code/'tools/run_all_market_intraday.py'),
            '--universe',str(source),'--cache',str(root/'acquisition/market_data'),
            '--output',str(root/'analysis'),'--cutoff',a.cutoff,'--workers','1',
            '--periods','1m','5m','--min-free-gb','10','--min-free-memory-mb','512',
            '--follow-cache','--source-status',str(root/'acquisition/acquisition-summary.json')]
    if a.resume:replay+=['--resume','--retry-failed']
    progress=[sys.executable,'-u',str(code/'tools/serve_intraday_market_progress.py'),
              '--root',str(root),'--port','8798']
    processes=[];env=os.environ.copy()
    env['PYTHONIOENCODING']='utf-8';env['CHANLUN_TDX_BASE_URL']=a.base_url
    for name,command in [('capture',capture),('replay',replay),('progress',progress)]:
        with (logs/(name+'.stdout.log')).open('ab') as out,(logs/(name+'.stderr.log')).open('ab') as err:
            process=subprocess.Popen(command,cwd=code,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        processes.append({'name':name,'pid':process.pid,'command':command,
                          'stdout':str(logs/(name+'.stdout.log')),'stderr':str(logs/(name+'.stderr.log'))})
    value={'created_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'root':str(root),
           'cutoff':a.cutoff,'source_universe_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
           'processes':processes,'uploaded':False,'execution_allowed':False,
           'history_semantics':'all observations actually returned by provider, every input prefix retained',
           'universe_semantics':'fixed current listed A shares, historical delisted membership not included'}
    receipt.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(value,ensure_ascii=False))


if __name__=='__main__':main()
