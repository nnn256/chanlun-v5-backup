"""Verify the portable package's source and data against MANIFEST.json."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--all',action='store_true',help='also verify the database before its first run')
    args=parser.parse_args()
    root=args.root.resolve()
    manifest=json.loads((root/'MANIFEST.json').read_text(encoding='utf-8'))
    errors=[];checked=skipped=0
    for row in manifest['files']:
        if row.get('mutable') and not args.all:
            skipped+=1;continue
        path=(root/row['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            errors.append(row['path']+': missing');continue
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        if path.stat().st_size!=row['bytes'] or digest.hexdigest()!=row['sha256']:
            errors.append(row['path']+': hash mismatch')
        checked+=1
    print(json.dumps({'status':'pass' if not errors else 'failed','checked':checked,'mutable_skipped':skipped,'errors':errors},ensure_ascii=False))
    return int(bool(errors))


if __name__=='__main__':raise SystemExit(main())
