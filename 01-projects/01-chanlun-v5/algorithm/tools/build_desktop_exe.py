"""Reproducible self-contained Windows EXE build, with portable seed data."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('CHANLUN_EXE_BUILD_DIR',ROOT/'artifacts/exe-build-20261108'))


def main():
    resources=OUT/'resources';resources.mkdir(parents=True,exist_ok=True)
    seed=resources/'project-seed.zip'
    # Use the independent, verified portable data snapshot; do not package
    # this machine's running jobs or unrelated newer experiment modules.
    source=ROOT/'artifacts/desktop-launch-fix-20261108/release/Chanlun-Full-2.1.0-20261108/project'
    if not source.exists():raise FileNotFoundError('verified portable project is required')
    selected=[]
    for p in source.rglob('*'):
        if not p.is_file() or '__pycache__' in p.parts:continue
        name=p.relative_to(source).as_posix()
        if name.startswith(('vendor/','artifacts/','examples','tests/')) or name.endswith('.log'):continue
        selected.append((p,name))
    patches=[p.relative_to(ROOT).as_posix() for p in (ROOT/'workbench').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    patches+=['chanmodel/tdx_data.py','tools/capture_full_stock.py']
    with zipfile.ZipFile(seed,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p,name in selected:
            if name in patches:continue
            z.write(p,name)
        for name in patches:z.write(ROOT/name,name)
    build={'version':'2.1.2-exe','created_at':datetime.now().astimezone().isoformat(),
           'payload_sha256':hashlib.sha256(seed.read_bytes()).hexdigest(),'seed_files':len(selected)+1,
           'architecture':'Windows x64','requires_system_python':False,'execution_allowed':False}
    (resources/'build-info.json').write_text(json.dumps(build,ensure_ascii=False,indent=2),encoding='utf-8')
    from PIL import Image,ImageDraw
    im=Image.new('RGBA',(256,256),'#243f57');d=ImageDraw.Draw(im)
    d.rounded_rectangle((18,18,238,238),radius=35,fill='#294f70')
    d.line([(43,177),(81,135),(115,152),(155,93),(183,111),(216,58)],fill='#ffffff',width=12)
    for x,y in [(81,135),(155,93),(216,58)]:d.ellipse((x-8,y-8,x+8,y+8),fill='#7ecebd')
    icon=resources/'app.ico';im.save(icon,format='ICO',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    py=ROOT/'artifacts/exe-build-20261108/build-env/Scripts/python.exe'
    if not py.exists():raise FileNotFoundError('build environment not installed')
    args=[str(py),'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed','--name','ChanlunWorkbench',
          '--distpath',str(OUT/'dist'),'--workpath',str(OUT/'pyinstaller-work'),'--specpath',str(OUT),
          '--paths',str(ROOT),'--icon',str(icon),'--add-data',str(seed)+';.',
          '--add-data',str(resources/'build-info.json')+';.',
          '--collect-submodules','chanmodel','--collect-submodules','workbench',
          '--hidden-import','tools.capture_full_stock','--hidden-import','tkinter',
          '--hidden-import','tkinter.ttk','--hidden-import','tkinter.messagebox',str(ROOT/'desktop_app.py')]
    with (OUT/'build.stdout.log').open('w',encoding='utf-8') as out,(OUT/'build.stderr.log').open('w',encoding='utf-8') as err:
        result=subprocess.run(args,cwd=ROOT,stdout=out,stderr=err)
    if result.returncode:raise RuntimeError('EXE build failed; inspect build.stderr.log')
    exe=OUT/'dist/ChanlunWorkbench.exe'
    receipt={**build,'exe':str(exe),'bytes':exe.stat().st_size,'sha256':hashlib.sha256(exe.read_bytes()).hexdigest()}
    (OUT/'build-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
