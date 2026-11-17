"""Use the isolated agent-browser session to render each actual chart to PNG."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/aoya-independent-20261108'
SESSION='aoya-png-4cb45af50456'
CLI=shutil.which('agent-browser')
if CLI and CLI.lower().endswith(('.cmd', '.bat')):
    # Avoid cmd.exe interpreting query-string '&' as another command.
    native=Path(CLI).parent/'node_modules/agent-browser/bin/agent-browser-win32-x64.exe'
    if native.exists():CLI=str(native)


def call(*args):
    cmd=[CLI,'--session',SESSION,*map(str,args)]
    r=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=50)
    if r.returncode:
        raise RuntimeError(json.dumps({'command':cmd,'stdout':r.stdout,'stderr':r.stderr},ensure_ascii=False))
    return r.stdout


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    run=json.loads((OUT/'run-summary.json').read_text(encoding='utf-8'))
    entries=run['catalog']+[{'period':'day','label':'日K线_完整历史','kind':'candles','range':'all'}]
    call('set','viewport','2200','1250')
    results=[]
    for number,item in enumerate(entries,1):
        period=item['period'];params='period='+period+'&capture=1'+('&range=all' if item.get('range')=='all' else '')
        url='http://127.0.0.1:8808/?'+params
        call('open',url)
        call('wait','--fn','window.chartReady === true')
        raw=call('eval','JSON.stringify({ready:window.chartReady,errors:window.chartErrors,proof:window.chartProof,canvases:document.querySelectorAll("canvas").length,width:document.documentElement.scrollWidth})')
        payload=json.loads(raw)
        if isinstance(payload,str):payload=json.loads(payload)
        if not payload['ready'] or payload['errors'] or payload['proof']['plotWidth']<1800:
            raise ValueError('Browser render did not pass: '+str(payload))
        path=OUT/'png'/f'{number:02d}_奥雅股份_{item["label"]}.png'
        call('screenshot',path,'--full')
        results.append({'period':period,'label':item['label'],'url':url,'file':path.relative_to(OUT).as_posix(),
                        'browser':payload,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        (OUT/'browser-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'png':path.name,'proof':payload['proof']},ensure_ascii=False),flush=True)
    print(json.dumps({'rendered_pngs':len(results),'browser_errors':0},ensure_ascii=False))


if __name__=='__main__':
    main()
