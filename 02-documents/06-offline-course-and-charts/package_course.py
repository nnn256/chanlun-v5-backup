"""Build and verify the final offline ZIP without including temp caches."""
from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from verify_complete_bundle import verify

HERE=Path(__file__).resolve().parent
OUTPUT=HERE.parent/'缠论完整课程与算法全链-最终离线包.zip'
proof=verify()
(HERE/'FINAL_VERIFICATION.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
workspace_root=HERE.parents[1]
source_root=workspace_root/'缠论算法'/'chanmodel'
portable_root=HERE/'engine'/'chanmodel'
source_rows=[]
for original in sorted(source_root.rglob('*.py')):
    relative=original.relative_to(source_root)
    portable=portable_root/relative
    if portable.is_file():
        left=hashlib.sha256(original.read_bytes()).hexdigest()
        right=hashlib.sha256(portable.read_bytes()).hexdigest()
        source_rows.append({'path':str(Path('engine/chanmodel')/relative),'source_sha256':left,
                            'bundled_sha256':right,'byte_identical':left==right})
source_receipt={'source':'workspace chanlun-algorithm/chanmodel',
                'identical_files':sum(row['byte_identical'] for row in source_rows),
                'files':source_rows,
                'note':'Bundled engine modules are traceable to workspace source; local entrypoints and view adapters are listed separately.'}
(HERE/'SOURCE_PROVENANCE.json').write_text(json.dumps(source_receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
exclude_parts={'__pycache__','media-baseline','frames','full-study','profile-rebuild'}
exclude_names={'analysis_cli_smoke.json','multiframe_report.json',
               'data-rebuilt.js',
               'preview-full.png','preview-recursive.png','preview-pdf-1.png','preview-pdf-2.png','preview-pdf-3.png','preview-pdf-4.png'}
files=[]
for path in HERE.rglob('*'):
    if not path.is_file():continue
    rel=path.relative_to(HERE)
    if any(part in exclude_parts for part in rel.parts) or path.name in exclude_names:continue
    if path.suffix.lower() in {'.pyc','.pyo'}:continue
    files.append(path)
if OUTPUT.exists():OUTPUT.unlink()
with zipfile.ZipFile(OUTPUT,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
    for path in sorted(files):bundle.write(path,Path('chanlun-complete')/path.relative_to(HERE))
with zipfile.ZipFile(OUTPUT) as bundle:
    assert bundle.testzip() is None
    with tempfile.TemporaryDirectory(prefix='chanlun-final-') as temp:
        bundle.extractall(temp)
        extracted=Path(temp)/'chanlun-complete'
        result=subprocess.run([sys.executable,str(extracted/'verify_complete_bundle.py')],cwd=extracted,capture_output=True,text=True,encoding='utf-8')
        if result.returncode:raise RuntimeError(result.stderr or result.stdout)
print(json.dumps({'zip':str(OUTPUT.resolve()),'files':len(files),'bytes':OUTPUT.stat().st_size,'archive_checked':True,'isolated_verification':True},ensure_ascii=False))
