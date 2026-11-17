"""Stream a scoped, deduplicated local data backup while jobs continue running."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time

BASE=Path(__file__).resolve().parent.parent
OUT=BASE/'local-data'
SKIP={'.git','node_modules','__pycache__','.venv','before','extracted-verification','pyinstaller-work'}
SOURCES={
    'active-f-workbench':Path('F:/ChanlunV5-20261115/workbench-data-8895'),
    'v5-d-data':Path('D:/缠论V5/data'),
    'v5-d-runs':Path('D:/缠论V5/runs'),
    'v5-d-workbench':Path('D:/缠论V5/workbench-data-8895'),
    'intraday-batch':Path('F:/ChanlunAlgorithmTests/2026-11-15-all-market-intraday'),
    'daily-batch':Path('D:/ChanlunFullHistory-20261117'),
    'course-output':Path('C:/Users/li/Documents/ChatGPT/缠学习/output'),
}
EXTRA={
    'release/ChanlunV5-20261115-FULL.zip':Path('D:/缠论V5/releases/20261115/ChanlunV5-20261115-FULL.zip'),
    'release/ChanlunV5-AutoResources-20261117.zip':Path('D:/缠论V5/releases/auto-resources-20261117/ChanlunV5-AutoResources-20261117.zip'),
    'runtime/tdx-api-revised.exe':Path('D:/缠论V5/algorithm/runtime/tdx-api-revised.exe'),
}
VIDEOS=['缠论是啥t.mp4','k线合并.mp4','顶底分型教学.mp4','笔教学.mp4','第五课缠论线段.mp4',
        '第六课缠论中枢正式版.mp4','第七课走势类型.mp4','缠论背驰完整版.mp4','缠论最后一课：买卖点.mp4']

def files():
    for label,root in SOURCES.items():
        for base,dirs,names in os.walk(root):
            dirs[:]=sorted(name for name in dirs if name not in SKIP)
            for name in sorted(names):
                if name.endswith(('-wal','-shm','.lock','.tmp','.incomplete')) or '.tmp-' in name:continue
                path=Path(base)/name
                yield label+'/'+path.relative_to(root).as_posix(),path
    for relative,path in EXTRA.items():
        if path.is_file():yield relative,path
    for name in VIDEOS:
        path=Path('D:/NeatDM/Video')/name
        if path.is_file():yield 'input-videos/'+name,path

def main():
    OUT.mkdir(parents=True,exist_ok=True);objects=OUT/'objects';objects.mkdir(exist_ok=True)
    manifest=OUT/'file-manifest.jsonl';events=OUT/'errors.jsonl';started=time.time()
    existing={}
    if manifest.is_file():
        for line in manifest.open(encoding='utf-8'):
            row=json.loads(line);existing[row['path']]=row
    seen=set();count=stored=logical=unstable=failed=0
    with manifest.open('a',encoding='utf-8') as ledger,events.open('a',encoding='utf-8') as errors:
        for relative,path in files():
            if relative in seen:continue
            seen.add(relative)
            try:
                before=path.stat()
                old=existing.get(relative)
                if old and old['source_bytes']==before.st_size and old['mtime_ns']==before.st_mtime_ns and (OUT/old['object']).is_file():
                    count+=1;logical+=old['bytes'];continue
                if shutil.disk_usage(OUT).free<12*1024**3:raise RuntimeError('stop: local backup disk reserve below 12GiB')
                temporary=OUT/f'.object-{os.getpid()}.tmp'
                if temporary.exists():temporary.unlink()
                database=False
                if path.suffix in {'.sqlite','.sqlite3','.db'}:
                    with path.open('rb') as header:database=header.read(16)==b'SQLite format 3\x00'
                copied_snapshot=False
                if database:
                    src=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
                    dest=sqlite3.connect(temporary)
                    try:src.backup(dest,pages=512,sleep=.025);copied_snapshot=True
                    finally:dest.close();src.close()
                digest=hashlib.sha256();size=0
                source=temporary if copied_snapshot else path
                with source.open('rb') as input_stream:
                    target=None if copied_snapshot else temporary.open('wb')
                    try:
                        for chunk in iter(lambda:input_stream.read(1024*1024),b''):
                            digest.update(chunk);size+=len(chunk)
                            if target:target.write(chunk)
                    finally:
                        if target:target.close()
                after=path.stat();changed=(before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns)
                if changed and not database:
                    unstable+=1
                value=digest.hexdigest();folder=objects/value[:2];folder.mkdir(exist_ok=True);obj=folder/value
                if obj.exists():temporary.unlink()
                else:temporary.replace(obj);stored+=size
                row={'path':relative,'source':str(path),'object':obj.relative_to(OUT).as_posix(),
                     'sha256':value,'bytes':size,'source_bytes':before.st_size,'mtime_ns':before.st_mtime_ns,
                     'database_online_snapshot':database,'source_changed_during_read':changed,
                     'snapshot_at':time.time()}
                ledger.write(json.dumps(row,ensure_ascii=False)+'\n');ledger.flush();count+=1;logical+=size
                if count%1000==0:
                    progress={'state':'running','files':count,'logical_bytes':logical,'new_object_bytes':stored,
                              'unstable_files':unstable,'failed_files':failed,'seconds':round(time.time()-started,1)}
                    (OUT/'status.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                    print(json.dumps(progress),flush=True)
            except Exception as exc:
                failed+=1;errors.write(json.dumps({'path':relative,'error':f'{type(exc).__name__}: {exc}'},ensure_ascii=False)+'\n');errors.flush()
                if isinstance(exc,RuntimeError) and str(exc).startswith('stop:'):raise
    status={'state':'completed','files':count,'logical_bytes':logical,'new_object_bytes':stored,
            'unstable_files':unstable,'failed_files':failed,'seconds':round(time.time()-started,1),
            'snapshot_scope':'per-file bounded-time snapshots; running batches continue; SQLite copied with online backup API',
            'missing_input_videos':[name for name in VIDEOS if not (Path('D:/NeatDM/Video')/name).is_file()]}
    (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
