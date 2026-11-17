"""Copy reviewed source to an isolated F-drive workbench; never alter production."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target',type=Path,required=True)
    p.add_argument('--cache',type=Path,required=True)
    a=p.parse_args();target=a.target.resolve();target.mkdir(parents=True,exist_ok=True)
    files={}
    for directory in ['chanmodel','workbench','third_party/chanpy']:
        for source in sorted((ROOT/directory).rglob('*')):
            if not source.is_file() or '__pycache__' in source.parts:
                continue
            if source.suffix not in {'.py','.js','.html','.css','.json','.md','.txt'} and source.name not in {'LICENSE','NOTICE'}:
                continue
            relative=source.relative_to(ROOT)
            dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,dest)
            files[relative.as_posix()]=hashlib.sha256(dest.read_bytes()).hexdigest()
    for relative in ['runs/tdx-all-a-20261106/universe.json',
                     'runs/aoya-v2-chart-20261107/assets/lightweight-charts.standalone.production.js',
                     'runs/aoya-v2-chart-20261107/assets/LICENSE',
                     'runs/aoya-v2-chart-20261107/assets/NOTICE',
                     'runs/aoya-v2-chart-20261107/assets/library-source.json']:
        source=ROOT/relative;dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest);files[relative]=hashlib.sha256(dest.read_bytes()).hexdigest()
    shutil.copytree(a.cache,target/'market_data',dirs_exist_ok=True)
    (target/'deployment.json').write_text(json.dumps({'schema':1,'source':str(ROOT),
        'target':str(target),'files_sha256':files,'cache':str(a.cache.resolve()),
        'production_database_modified':False,'uploaded':False,'execution_allowed':False},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'target':str(target),'code_files':len(files),'uploaded':False}))


if __name__=='__main__':main()
