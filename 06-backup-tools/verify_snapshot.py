"""Verify an ordered source/document/conversation snapshot by SHA-256."""
import argparse,hashlib,json
from pathlib import Path

def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    args=parser.parse_args();root=args.root.resolve()
    manifest=json.loads((root/'05-backup-manifests/SNAPSHOT-MANIFEST.json').read_text(encoding='utf-8'))
    errors=[]
    for row in manifest['files']:
        path=(root/row['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():errors.append(row['path']+':missing')
        elif path.stat().st_size!=row['bytes'] or digest(path)!=row['sha256']:errors.append(row['path']+':hash_changed')
    output={'status':'pass' if not errors else 'failed','files_checked':len(manifest['files']),'errors':errors}
    print(json.dumps(output,ensure_ascii=False))
    return int(bool(errors))

if __name__=='__main__':raise SystemExit(main())
