#!/usr/bin/env python3
"""Recover interrupted intraday writes after the 2026-11-06 reboot.

No network requests or production-code edits. A dry inventory is written before
quarantine; --apply backs up every affected file before moving it. The SQLite
backup and old rows are retained, and summaries use the saved run fingerprint.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import gzip
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from chanmodel.tdx_data import atomic_json,now_iso,sha256
from intraday_scan import export


def inside(path,root):
    resolved=path.resolve()
    if resolved!=root.resolve() and root.resolve() not in resolved.parents:
        raise ValueError('Path escaped intended project: '+str(resolved))
    return resolved


def triplet(cache,period,code):
    folder=cache/'tdx'/period
    return {'metadata':folder/'metadata'/f'{code}.json','raw':folder/'raw'/f'{code}.json.gz','csv':folder/'ohlcv'/f'{code}.csv.gz'}


def inspect(triple):
    errors=[]
    for name,path in triple.items():
        if not path.is_file():errors.append(f'missing {name}')
    if errors:return errors
    try:
        metadata=json.loads(triple['metadata'].read_text(encoding='utf-8'))
        if not isinstance(metadata,dict):raise ValueError('metadata is not a JSON object')
        compressed=triple['raw'].read_bytes()
        if sha256(compressed)!=metadata['raw_storage_sha256']:raise ValueError('raw storage hash mismatch')
        raw=gzip.decompress(compressed)
        if sha256(raw)!=metadata['response_sha256']:raise ValueError('raw response hash mismatch')
        response=json.loads(raw)
        if not isinstance(response,dict) or response.get('code')!=0 or not isinstance(response.get('data'),dict):
            raise ValueError('raw response has invalid success envelope')
        csv_compressed=triple['csv'].read_bytes()
        if sha256(csv_compressed)!=metadata['csv_storage_sha256']:raise ValueError('CSV storage hash mismatch')
        if sha256(gzip.decompress(csv_compressed))!=metadata['csv_sha256']:raise ValueError('CSV body hash mismatch')
    except Exception as exc:errors.append(f'{type(exc).__name__}: {exc}')
    return errors


def stored_sources_valid(result):
    errors=[]
    for level,metadata in result.get('sources',{}).items():
        try:
            raw=Path(metadata['raw_path']);csv=Path(metadata['csv_path'])
            if not raw.is_file() or not csv.is_file():raise ValueError('source files missing')
            compressed=raw.read_bytes()
            if sha256(compressed)!=metadata['raw_storage_sha256']:raise ValueError('recorded raw storage hash mismatch')
            if sha256(gzip.decompress(compressed))!=metadata['response_sha256']:raise ValueError('recorded raw body hash mismatch')
            expected=metadata['csv_sha256'] if level=='day' else metadata['csv_storage_sha256']
            current=csv.read_bytes()
            if sha256(current)!=expected:raise ValueError('recorded CSV storage hash mismatch')
            if level!='day' and sha256(gzip.decompress(current))!=metadata['csv_sha256']:
                raise ValueError('recorded CSV body hash mismatch')
        except Exception as exc:errors.append(f'{level}: {type(exc).__name__}: {exc}')
    if set(result.get('sources',{}))!={'day','30m','5m'}:errors.append('sources do not cover day/30m/5m')
    return errors


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,default=ROOT/'runs/tdx-intraday-all-a-20261106')
    parser.add_argument('--cache-dir',type=Path,default=ROOT/'market_data')
    parser.add_argument('--recovery-dir',type=Path,default=ROOT/'artifacts/tdx-integration/reboot-20261106-031949')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();root=ROOT.resolve();run=inside(args.run_dir,root);cache=inside(args.cache_dir,root);recovery=inside(args.recovery_dir,root)
    recovery.mkdir(parents=True,exist_ok=True)
    metadata=json.loads((run/'run.json').read_text(encoding='utf-8'));bad=[];valid=0;counts={}
    for period in ['minute30','minute5']:
        folder=cache/'tdx'/period
        symbols=set(path.stem for path in (folder/'metadata').glob('*.json'))
        symbols.update(path.name.removesuffix('.json.gz') for path in (folder/'raw').glob('*.json.gz'))
        symbols.update(path.name.removesuffix('.csv.gz') for path in (folder/'ohlcv').glob('*.csv.gz'))
        counts[period]={'inventory_symbols':len(symbols),'invalid':0}
        for index,code in enumerate(sorted(symbols),1):
            files=triplet(cache,period,code);errors=inspect(files)
            if errors:
                counts[period]['invalid']+=1
                bad.append({'symbol':code,'period':period,'errors':errors,'files':{key:str(path) for key,path in files.items() if path.exists()}})
            else:valid+=1
            if index%250==0:print(json.dumps({'event':'inventory','period':period,'checked':index,'invalid':counts[period]['invalid']}),flush=True)
    plan={'inventoried_at':now_iso(),'run_dir':str(run),'cache_dir':str(cache),'saved_engine_sha256':metadata['settings']['engine_sha256'],
          'period_counts':counts,'valid_triplets':valid,'bad_triplets':bad,'apply':args.apply}
    atomic_json(recovery/'cache-plan.json',plan)
    print(json.dumps({'event':'plan','valid_triplets':valid,'bad_triplets':len(bad),'counts':counts},ensure_ascii=False),flush=True)
    if not args.apply:return 0

    backups=recovery/'before';quarantine=recovery/'quarantine';actions=[]
    def backup(path):
        source=inside(path,root);relative=source.relative_to(root);destination=inside(backups/relative,root)
        if source.is_file() and not destination.exists():
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
            if sha256(source.read_bytes())!=sha256(destination.read_bytes()):raise ValueError('Backup hash mismatch')
        return destination
    def isolate(path):
        source=inside(path,root)
        if not source.is_file():return
        saved=backup(source);destination=inside(quarantine/source.relative_to(root),root)
        if destination.exists():raise ValueError('Quarantine destination exists; refusing overwrite: '+str(destination))
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(source),str(destination))
        if sha256(saved.read_bytes())!=sha256(destination.read_bytes()):raise ValueError('Quarantine hash mismatch')
        actions.append({'action':'backed_up_and_quarantined','source':str(source),'backup':str(saved),'quarantine':str(destination),'sha256':sha256(destination.read_bytes())})
    for item in bad:
        for path in item['files'].values():isolate(Path(path))

    database=run/'checkpoint.sqlite3';db=sqlite3.connect(database)
    integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity!='ok':raise ValueError('SQLite integrity check failed: '+integrity)
    destination=backups/database.relative_to(root);destination.parent.mkdir(parents=True,exist_ok=True)
    if not destination.exists():
        saved_db=sqlite3.connect(destination);db.backup(saved_db);saved_db.close()
    rows=db.execute('SELECT symbol,status,engine_sha256,result,updated_at FROM stocks ORDER BY symbol').fetchall()
    recovered=[];failed=[];unchanged=0;old_rows=[]
    for code,status,engine,result_raw,updated_at in rows:
        if status!='success':continue
        result=json.loads(result_raw);errors=stored_sources_valid(result)
        stock_path=run/'stocks'/f'{code}.json'
        file_valid=False
        try:file_valid=json.loads(stock_path.read_text(encoding='utf-8'))==result
        except (OSError,ValueError):pass
        if errors:
            old_rows.append({'symbol':code,'status':status,'engine_sha256':engine,'result':result,'updated_at':updated_at})
            if stock_path.exists():isolate(stock_path)
            failure={key:result.get(key) for key in ['symbol','name','exchange','code']}
            failure.update(status='failed',engine_sha256=engine,error='reboot cache integrity: '+'; '.join(errors),
                           recovery_observed_at=now_iso(),prior_success=True,recovery_evidence=str(recovery/'cache-plan.json'))
            db.execute('UPDATE stocks SET status=?,result=?,updated_at=? WHERE symbol=?',('failed',json.dumps(failure,ensure_ascii=False,allow_nan=False),now_iso(),code))
            atomic_json(stock_path,failure);failed.append({'symbol':code,'errors':errors})
        elif not file_valid:
            if stock_path.exists():isolate(stock_path)
            atomic_json(stock_path,result);recovered.append(code)
        else:unchanged+=1
    db.commit()
    atomic_json(recovery/'old-checkpoint-rows.json',old_rows)
    for path in [run/'summary.json',run/'failures.jsonl']:
        if path.exists():backup(path)
    summary=export(db,run,metadata);db.close()
    report={'recovered_at':now_iso(),'sqlite_integrity':integrity,'stored_engine_sha256':metadata['settings']['engine_sha256'],
            'production_fingerprint_changed':False,'network_requests':0,'scan_started':False,
            'valid_triplets':valid,'quarantined_triplets':len(bad),'quarantined_files':len(actions),
            'recovered_stock_json':recovered,'checkpoint_successes_downgraded':failed,'unchanged_valid_successes':unchanged,
            'actions':actions,'summary':summary,
            'resume_command':f'python intraday_scan.py --run-dir "{run}" --cache-dir "{cache}" --daily-cache-dir "{cache}" --workers 8 --resume'}
    atomic_json(recovery/'recovery-result.json',report)
    print(json.dumps({key:report[key] for key in ['sqlite_integrity','quarantined_triplets','quarantined_files','recovered_stock_json','checkpoint_successes_downgraded','unchanged_valid_successes']},ensure_ascii=False),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
