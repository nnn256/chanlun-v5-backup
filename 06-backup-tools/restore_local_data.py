"""Restore selected logical trees from the local content-addressed backup."""
import argparse,hashlib,json,shutil
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,default=Path(__file__).resolve().parent.parent/'local-data')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prefix',default='')
    args=parser.parse_args();root=args.backup.resolve();target=args.output.resolve()
    if target.exists() and any(target.iterdir()):raise SystemExit('restore output must be empty')
    latest={}
    for line in (root/'file-manifest.jsonl').open(encoding='utf-8'):
        row=json.loads(line)
        if row['path'].startswith(args.prefix):latest[row['path']]=row
    total=0
    for name,row in sorted(latest.items()):
        source=(root/row['object']).resolve();dest=(target/name).resolve()
        if not source.is_relative_to(root/'objects') or not dest.is_relative_to(target):raise ValueError('invalid backup path')
        digest=hashlib.sha256()
        with source.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        if digest.hexdigest()!=row['sha256']:raise ValueError('corrupt object for '+name)
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest);total+=1
    print(json.dumps({'status':'pass','restored_files':total,'output':str(target)},ensure_ascii=False))

if __name__=='__main__':main()
