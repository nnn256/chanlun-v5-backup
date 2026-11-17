"""Build a small integrity-preserving overlay for the V5 stale-tab fix."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


ROOT=Path(__file__).resolve().parents[1]
RELEASE='ChanlunV5-20261115'
FILES=(
    'algorithm/workbench/backtests.py',
    'algorithm/workbench/web/app.js',
    'algorithm/workbench/web/index.html',
    'algorithm/tests/test_native_backtest_service.py',
)
HOTFIX_TEXT=(
    '缠论V5回测并行数兼容修复\n\n'
    '将本覆盖包解压到完整V5包的根目录，允许替换文件。然后刷新工作台页面后再启动回测。\n'
    '后端接受整数JSON和十进制整数字符串（如16和"16"），范围仍为1到16；布尔、小数和越界值拒绝。\n'
    '并发任务使用数据库原子入队，同时页面提交期间会禁用按钮以避免重复启动。\n'
    '本覆盖包包含更新后的MANIFEST.json和PACKAGE_INFO.json。覆盖后在包根运行：\n'
    '  py -3 verify_package.py --all\n'
)


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,default=ROOT.parent/'releases/20261115/extracted-verification'/RELEASE)
    parser.add_argument('--output',type=Path,default=ROOT.parent/'releases/20261115-worker-fix')
    args=parser.parse_args();base=args.base.resolve();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    manifest_path=base/'MANIFEST.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    rows={row['path']:row for row in manifest['files']}
    overlay={}
    for rel in FILES:
        source=ROOT/Path(rel).relative_to('algorithm');row=rows.get(rel)
        if row is None:raise ValueError('base manifest does not contain '+rel)
        row['bytes']=source.stat().st_size;row['sha256']=sha(source);overlay[rel]=source
    note='HOTFIX-README.txt';note_path=output/'HOTFIX-README.txt';note_path.write_text(HOTFIX_TEXT,encoding='utf-8')
    rows[note]={'path':note,'bytes':note_path.stat().st_size,'sha256':sha(note_path)}
    manifest['file_count']=len(rows);manifest['files']=sorted(rows.values(),key=lambda row:row['path'])
    manifest_tmp=output/'MANIFEST.json';manifest_tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    info=json.loads((base/'PACKAGE_INFO.json').read_text(encoding='utf-8'))
    info['build_revision']='r1-worker-normalization-20261115'
    info.setdefault('patches',[]).extend([
        'stale browser worker-count strings normalize to integer values in range 1..16',
        'backtest queue reservation is atomic across simultaneous requests',
        'backtest submit button is disabled while the request is pending',
    ])
    info_tmp=output/'PACKAGE_INFO.json';info_tmp.write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    archive=output/f'{RELEASE}-WORKERS-HOTFIX.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as target:
        target.write(manifest_tmp,'MANIFEST.json')
        target.write(info_tmp,'PACKAGE_INFO.json')
        target.write(note_path,note)
        for rel,source in overlay.items():target.write(source,rel)
    with zipfile.ZipFile(archive) as target:
        if target.testzip():raise RuntimeError('hotfix ZIP CRC verification failed')
        files=set(target.namelist())
        if files!={'MANIFEST.json','PACKAGE_INFO.json',note,*FILES}:raise RuntimeError('unexpected hotfix contents')
    receipt={'status':'pass','overlay':str(archive),'bytes':archive.stat().st_size,
             'sha256':sha(archive),'file_count':len(files),'base_manifest_entries':len(rows),
             'target_full_package':RELEASE,'excluded_workspace_backups':True}
    (output/'hotfix-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
