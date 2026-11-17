"""Seal all scoped staged files without importing running project code."""
import datetime,hashlib,json,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent/'staging'
TARGET=ROOT/'05-backup-manifests/SNAPSHOT-MANIFEST.json'

def main():
    rows=[]
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file() or '.git' in path.relative_to(ROOT).parts or path==TARGET:continue
        body=path.read_bytes()
        rows.append({'path':path.relative_to(ROOT).as_posix(),'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()})
    TARGET.write_text(json.dumps({'sealed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'files':rows,'file_count':len(rows),'total_bytes':sum(row['bytes'] for row in rows),
        'scope':'ordered project source/docs/selected-thread visible export/validation; local data separately archived'},
        ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'sealed','files':len(rows),'bytes':sum(row['bytes'] for row in rows)},ensure_ascii=False))

if __name__=='__main__':main()
