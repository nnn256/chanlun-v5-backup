"""Copy scoped project source and documents into a numbered backup repository."""
from __future__ import annotations
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

WORK=Path('C:/Users/li/Documents/ChatGPT/缠学习')
SOURCE=Path('D:/缠论V5/algorithm')
ROOT=Path(__file__).resolve().parent.parent
STAGE=ROOT/'staging'
PRUNE={'.git','__pycache__','node_modules','.venv','.wix','runtime','runs','artifacts','market_data','data','dist','build','pyinstaller-work'}
BAD={'.pyc','.pyo','.exe','.dll','.pyd','.rar','.zip','.7z','.sqlite','.sqlite3','.db','.wal','.pem','.key'}
KEEP_EXT={'.py','.js','.cjs','.mjs','.ts','.tsx','.css','.html','.json','.md','.txt','.toml','.yaml','.yml','.mod','.sum','.go','.sh','.cmd','.bat','.ps1','.wxs','.iss','.spec','.in','.png','.jpg','.jpeg','.svg','.webp','.pdf','.woff','.woff2','.ico','.c','.h','.cu'}
KEEP_NAMES={'LICENSE','NOTICE','Dockerfile','Makefile','CMakeLists.txt','.gitignore','.dockerignore','.gitattributes'}
POLICIES=[]

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def copy_one(source,target,group):
    if not source.is_file():return
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    POLICIES.append({'group':group,'source':str(source),'path':target.relative_to(STAGE).as_posix(),'bytes':target.stat().st_size,'sha256':sha(target)})

def source_tree(source,target,group,docs_only=False):
    if not source.exists():return
    for base,dirs,files in os.walk(source):
        dirs[:]=sorted(name for name in dirs if name not in PRUNE)
        for name in sorted(files):
            path=Path(base)/name
            if path.suffix.lower() in BAD or path.name in {'.env','auth.json','config.toml','credentials.json'}:continue
            if docs_only and path.suffix.lower() not in {'.md','.pdf','.txt'}:continue
            if path.suffix.lower() not in KEEP_EXT and path.name not in KEEP_NAMES:continue
            if path.stat().st_size>20*1024*1024:continue
            copy_one(path,target/path.relative_to(source),group)

def main():
    STAGE.mkdir(parents=True,exist_ok=True)
    current=STAGE/'01-projects'/'01-chanlun-v5'/'algorithm'
    for folder in ('chanmodel','workbench','tests','tools','public_web','third_party','installer','examples','examples-final'):
        source_tree(SOURCE/folder,current/folder,'current-v5')
    for path in sorted(SOURCE.iterdir()):
        if not path.is_file():continue
        if path.suffix.lower()=='.md':
            category='03-v5' if path.name in {'README-V5.md','自动计算资源说明.md'} or path.name.startswith('V5') else '04-history-version-docs'
            copy_one(path,STAGE/'02-documents'/category/path.name,'version-docs')
            copy_one(path,current/path.name,'current-v5')
        elif path.suffix.lower() in KEEP_EXT or path.name in KEEP_NAMES:
            copy_one(path,current/path.name,'current-v5')
    source_tree(SOURCE/'vendor'/'tdx-api',current/'vendor'/'tdx-api','tdx-provider-source')
    old=WORK/'缠论算法'
    history=STAGE/'01-projects'/'02-historical-workbench'/'algorithm'
    for folder in ('chanmodel','workbench','tests','tools','public_web','third_party','installer','examples','examples-final'):
        source_tree(old/folder,history/folder,'history-source')
    for path in sorted(old.iterdir()):
        if path.is_file() and (path.suffix.lower() in KEEP_EXT or path.name in KEEP_NAMES):
            copy_one(path,history/path.name,'history-source')
    early=STAGE/'01-projects'/'03-early-learning-engine'
    for path in sorted(WORK.iterdir()):
        if not path.is_file():continue
        if path.suffix.lower()=='.md':copy_one(path,STAGE/'02-documents'/'01-workspace-notes'/path.name,'workspace-notes')
        elif path.suffix.lower()=='.py':copy_one(path,early/path.name,'early-engine')
        elif path.name in {'video_transcript.txt','video_transcript_review.txt'}:copy_one(path,STAGE/'02-documents'/'02-course-transcripts'/path.name,'course-transcript')
    source_tree(WORK/'缠论知识库',STAGE/'02-documents'/'05-course-knowledge-base','knowledge-base')
    output=WORK/'output'/'chanlun-complete'
    source_tree(output,STAGE/'02-documents'/'06-offline-course-and-charts','offline-course')
    for path in (WORK/'output').rglob('*.pdf'):
        if any(part in PRUNE for part in path.relative_to(WORK/'output').parts):continue
        copy_one(path,STAGE/'02-documents'/'07-pdf'/path.relative_to(WORK/'output'),'pdf')
    intraday=Path('F:/ChanlunAlgorithmTests/2026-11-15-all-market-intraday')
    source_tree(intraday/'frozen-code',STAGE/'01-projects'/'04-intraday-frozen-engine','frozen-intraday')
    for folder in ('acceleration-20261117','operations-20261117','performance','source-repair-20261117'):
        src=intraday/folder;dst=STAGE/'01-projects'/'05-intraday-runtime-tools'/folder
        if not src.exists():continue
        # Runtime scripts and measured summaries only, never per-stock results.
        for path in src.iterdir():
            if path.is_file() and path.suffix in {'.py','.md','.json','.txt','.png'} and path.stat().st_size<5*1024*1024:
                copy_one(path,dst/path.name,'intraday-tools')
    daily=Path('D:/ChanlunFullHistory-20261117')
    source_tree(daily/'code',STAGE/'01-projects'/'06-full-history-frozen-code','frozen-daily')
    for path in (Path('D:/缠论V5/artifacts/auto-resources-20261117')).iterdir():
        if path.is_file() and path.suffix in {'.json','.png','.log'}:
            copy_one(path,STAGE/'04-verification'/'auto-resources-20261117'/path.name,'verification')
    for name in ('package-receipt.json','verification/extracted-tests.stderr.log'):
        src=Path('D:/缠论V5/releases/20261115')/name
        if src.is_file():copy_one(src,STAGE/'04-verification'/'full-package-20261115'/name,'verification')
    target=STAGE/'05-backup-manifests';target.mkdir(parents=True,exist_ok=True)
    (target/'source-copy-manifest.json').write_text(json.dumps({'files':POLICIES,'excluded':'runtime, market data, generated runs, databases, installers, nested git and credentials are backed up locally or inventoried separately'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    groups=collections.Counter(row['group'] for row in POLICIES)
    print(json.dumps({'files':len(POLICIES),'bytes':sum(row['bytes'] for row in POLICIES),'groups':groups,'stage':str(STAGE)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
