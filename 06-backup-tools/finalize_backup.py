"""Finalize local recovery receipts and prove several restore paths."""
import hashlib,json,os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
STAGE=ROOT/'staging'
LOCAL=ROOT/'local-data'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def main():
    latest={};lines=0
    for line in (LOCAL/'file-manifest.jsonl').open(encoding='utf-8'):
        row=json.loads(line);latest[row['path']]=row;lines+=1
    objects={row['object']:row for row in latest.values()}
    missing=[];size_different=[]
    for name,row in objects.items():
        path=LOCAL/name
        if not path.is_file():missing.append(name)
        elif path.stat().st_size!=row['bytes']:size_different.append(name)
    status=json.loads((LOCAL/'status.json').read_text(encoding='utf-8'))
    status.update(logical_paths=len(latest),unique_objects=len(objects),unique_object_bytes=sum(row['bytes'] for row in objects.values()),
                  manifest_rows=lines,missing_objects=len(missing),object_size_mismatches=len(size_different))
    # The one volatile stdout log is documented as such, never called immutable.
    unstable=[row['path'] for row in latest.values() if row.get('source_changed_during_read') and not row.get('database_online_snapshot')]
    status['volatile_log_paths']=unstable
    status['user_visible_conversation']=json.loads((STAGE/'03-conversation/export-audit.json').read_text(encoding='utf-8'))['exported_items']
    status['credential_configs_copied']=False
    paths=['runtime/tdx-api-revised.exe','active-f-workbench/workbench.sqlite3']
    paths += [name for name in sorted(latest) if name.startswith('input-videos/')][:1]
    paths += [name for name in sorted(latest) if name.startswith('v5-d-data/') and '/ohlcv/' in name][:1]
    paths += [name for name in sorted(latest) if name.startswith('intraday-batch/') and '/ohlcv/' in name][:1]
    proofs=[]
    for name in paths:
        row=latest[name];source=LOCAL/row['object']
        assert digest(source)==row['sha256']
        if row.get('database_online_snapshot'):
            db=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)
            try:quick=db.execute('PRAGMA quick_check').fetchone()[0]
            finally:db.close()
            assert quick=='ok'
        proofs.append({'path':name,'sha256_checked':True,'bytes':row['bytes'],
                       'sqlite_quick_check':'ok' if row.get('database_online_snapshot') else None})
    restore=ROOT/'restore-smoke'
    check=subprocess.run([sys.executable,str(ROOT/'tools/restore_local_data.py'),'--backup',str(LOCAL),'--output',str(restore),'--prefix','runtime/'],capture_output=True,text=True,encoding='utf-8')
    if check.returncode:raise RuntimeError(check.stderr)
    if missing or size_different:raise RuntimeError('local object existence verification failed')
    status.update(state='completed',verification={'all_objects_exist_and_match_sizes':True,'sample_full_hash_verifications':proofs,
                   'restore_smoke':json.loads(check.stdout),'full_rehash_performed':False})
    target=STAGE/'05-backup-manifests';target.mkdir(exist_ok=True)
    (target/'local-backup-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (ROOT/'BACKUP-COMPLETION.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
