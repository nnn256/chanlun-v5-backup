"""Republish the verified V5 payload with the stale-browser worker fix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from package_v5_release import RELEASE,digest,inventory,verify_extracted,verify_manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',type=Path,default=ROOT.parent/'releases/20261115'/RELEASE)
    parser.add_argument('--output',type=Path,default=ROOT.parent/'releases/20261115-worker-fix')
    parser.add_argument('--python',default=sys.executable)
    args=parser.parse_args()
    stage=args.stage.resolve();output=args.output.resolve()
    if not stage.is_dir():raise SystemExit(f'missing validated release stage: {stage}')
    if output.exists() and any(output.iterdir()):raise SystemExit(f'output is not empty: {output}')
    output.mkdir(parents=True,exist_ok=True)

    source_map={
        'algorithm/workbench/backtests.py':ROOT/'workbench/backtests.py',
        'algorithm/workbench/web/app.js':ROOT/'workbench/web/app.js',
        'algorithm/workbench/web/index.html':ROOT/'workbench/web/index.html',
        'algorithm/tests/test_native_backtest_service.py':ROOT/'tests/test_native_backtest_service.py',
    }
    for relative,source in source_map.items():shutil.copy2(source,stage/relative)
    info_path=stage/'PACKAGE_INFO.json'
    info=json.loads(info_path.read_text(encoding='utf-8'))
    info['build_revision']='r1-worker-normalization-20261115'
    info['patches']=['backtest workers accept integer JSON numbers or decimal integer strings; invalid values are rejected','cache-busted backtest UI validates and reports the requested concurrency']
    info_path.write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    rows=inventory(stage)
    (stage/'MANIFEST.json').write_text(json.dumps({'release':RELEASE,'file_count':len(rows),'files':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    archive=output/'ChanlunV5-20261115-FULL-r1.zip'
    with zipfile.ZipFile(archive,'w',allowZip64=True) as target:
        for row in [*rows,{'path':'MANIFEST.json'}]:
            source=stage/row['path'];suffix=source.suffix.lower()
            compression=zipfile.ZIP_STORED if suffix in {'.gz','.exe','.sqlite3'} else zipfile.ZIP_DEFLATED
            target.write(source,(Path(RELEASE)/row['path']).as_posix(),compress_type=compression,
                         compresslevel=4 if compression==zipfile.ZIP_DEFLATED else None)
    with zipfile.ZipFile(archive) as target:
        bad=target.testzip()
        if bad:raise RuntimeError(f'ZIP CRC failure: {bad}')
    extraction=output/'extracted-verification'
    with zipfile.ZipFile(archive) as target:target.extractall(extraction)
    extracted=extraction/RELEASE
    verify_manifest(extracted,rows)
    smoke=verify_extracted(extracted,args.python,output/'verification')
    receipt={'status':'pass','revision':'r1-worker-normalization-20261115','archive':str(archive),
             'archive_bytes':archive.stat().st_size,'archive_sha256':digest(archive),
             'file_count':len(rows),'zip_crc':'pass','source_manifest_verified_after_extraction':True,
             'isolated_extracted_verification':smoke,'excluded_workspace_backups':True,
             'contains_powershell_files':False}
    (output/'package-receipt-r1.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
