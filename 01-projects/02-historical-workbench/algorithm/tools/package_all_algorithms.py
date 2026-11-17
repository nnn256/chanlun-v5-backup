"""Build a portable complete algorithm bundle, then test it after extraction."""
import argparse
from datetime import datetime
import difflib
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.tdx_data import CN,atomic_json,normalize_daily,cache_history
from chanmodel.tdx_intraday import normalize_intraday,cache_intraday
from workbench.store import connect,initialize,STATE


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)


def tree(source,target,exclude=()):
    for p in source.rglob('*'):
        relative=p.relative_to(source)
        if not p.is_file() or any(part in {'.git','__pycache__','node_modules','.venv',*exclude} for part in relative.parts):continue
        copy(p,target/relative)


VERIFY='''import argparse,hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--all',action='store_true');a=p.parse_args()
manifest=json.loads((root/'MANIFEST.json').read_text(encoding='utf-8'))
errors=[];checked=0;skipped=0
for row in manifest['files']:
    if row.get('mutable') and not a.all:skipped+=1;continue
    path=(root/row['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():errors.append(row['path']+': missing');continue
    if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:errors.append(row['path']+': hash mismatch')
    checked+=1
print(json.dumps({'status':'pass' if not errors else 'failed','checked':checked,'mutable_runtime_skipped':skipped,'errors':errors},ensure_ascii=False))
raise SystemExit(bool(errors))
'''


def build(stage):
    project=stage/'project';project.mkdir(parents=True)
    for directory in ('chanmodel','workbench','tools','tests','examples','examples-final'):
        tree(ROOT/directory,project/directory)
    for p in ROOT.iterdir():
        if p.is_file() and p.suffix in ('.py','.ps1','.cmd','.md','.json'):
            if p.name.startswith('RECOVERY'):continue
            copy(p,project/p.name)
    for p in (ROOT/'vendor/tdx-api').rglob('*'):
        rel=p.relative_to(ROOT/'vendor/tdx-api')
        if not p.is_file() or any(x in {'.git','__pycache__','node_modules'} for x in rel.parts) or p.suffix.lower() in {'.exe','.rar','.zip','.db','.sqlite','.sqlite3','.log','.pyc'}:continue
        copy(p,project/'vendor/tdx-api'/rel)
    copy(ROOT/'runtime/tdx-api-revised.exe',project/'runtime/tdx-api-revised.exe')
    (project/'runtime/state').mkdir(parents=True,exist_ok=True)
    (project/'runtime/state/README.txt').write_text('Runtime state is created here by the local TDX service.\n',encoding='utf-8')
    copy(ROOT/'artifacts/tdx-integration/baseline/segments.py',project/'artifacts/tdx-integration/baseline/segments.py')
    for folder in ('aoya-v2-chart-20261107','junsheng-v2-chart-20261107'):
        copy(ROOT/'runs'/folder/'index.html',project/'runs'/folder/'index.html')
        tree(ROOT/'runs'/folder/'assets',project/'runs'/folder/'assets')
    tree(ROOT.parent/'缠论知识库',stage/'缠论知识库')
    # Freeze the stock universe and a single proven demo; no active job state.
    with connect() as db:
        universe=[dict(r) for r in db.execute('SELECT symbol,code,name,exchange,active FROM universe ORDER BY symbol')]
        row=db.execute("SELECT artifact FROM results WHERE symbol='sz300949' AND mode='full'").fetchone()
    bundle=json.loads(gzip.decompress((STATE/row['artifact']).read_bytes()))
    history_source=(ROOT/bundle['history_root']).resolve()
    history_relative=Path('runs/demo-sz300949-history')
    tree(history_source,project/history_relative)
    bundle['history_root']=history_relative.as_posix()
    if bundle['summary'].get('replay'):
        bundle['summary']['replay']['verified_run']='delivery/aoya-verification'
    artifact=Path('imports/sz300949-demo.json.gz')
    (project/'runtime/workbench'/artifact).parent.mkdir(parents=True,exist_ok=True)
    (project/'runtime/workbench'/artifact).write_bytes(gzip.compress(json.dumps(bundle,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    dbpath=project/'runtime/workbench/workbench.sqlite3';initialize(dbpath)
    with connect(dbpath) as db:
        db.executemany('INSERT INTO universe(symbol,code,name,exchange,active) VALUES(?,?,?,?,?)',[(r['symbol'],r['code'],r['name'],r['exchange'],r['active']) for r in universe])
        db.execute('INSERT INTO results VALUES(?,?,?,?,?,?)',('sz300949','full','bundled-demo',datetime.now(CN).isoformat(),json.dumps(bundle['summary'],ensure_ascii=False),artifact.as_posix()))
    # The stock-universe fallback is a runtime dependency of seed().
    atomic_json(project/'runs/tdx-all-a-20261106/universe.json',{'records':[{k:v for k,v in r.items() if k!='active'} for r in universe if r['active']],
        'snapshot_source':'current local workbench universe at package creation','historical_membership':False})
    cutoff=datetime.fromisoformat(bundle['summary']['as_of'])
    for period in ('day','minute5','minute30'):
        raw=gzip.decompress((history_source/'raw'/f'{period}.json.gz').read_bytes())
        data=json.loads(raw)['data'];receipt=json.loads((history_source/'receipts'/f'{period}.json').read_text(encoding='utf-8'))
        bars,rows,quality=normalize_daily(data,cutoff) if period=='day' else normalize_intraday(data,cutoff,period)
        quality['cache_run_as_of']=cutoff.isoformat()
        if period=='day':meta=cache_history(project/'market_data','sz300949','tdx',rows,raw,receipt,quality)
        else:meta=cache_intraday(project/'market_data','sz300949',period,rows,raw,receipt,quality)
        for key in ('raw_path','csv_path'):
            meta[key]=Path(meta[key]).relative_to(project).as_posix()
        atomic_json(project/'market_data/tdx'/period/'metadata/sz300949.json',meta)
    for name in ('奥雅股份_完整日线_2021至2026.png','奥雅股份_2021年日线放大.png','奥雅股份_11周期完整历史总览.png','summary.json','coverage.json','calendar-reconciliation.json','timeshare-verification.json','day-events.jsonl.gz'):
        copy(ROOT/'runs/aoya-full-history-20261108'/name,stage/'delivery/aoya-verification'/name)
    for name in ('final-tests.stderr.log','verification.json'):
        copy(ROOT/'artifacts/workbench-v2.1-20261108'/name,stage/'delivery/previous-verification'/name)
    # PowerShell 5 requires a BOM for Chinese script text. Create the service
    # working directory explicitly; original installations already had it.
    adaptations=[]
    for p in project.glob('*.ps1'):
        old=p.read_text(encoding='utf-8-sig');new=old
        if p.name=='Start-TdxApi.ps1':
            new=new.replace('$root = $PSScriptRoot','$root = $PSScriptRoot\nNew-Item -ItemType Directory -Force -Path (Join-Path $root "runtime/state") | Out-Null')
        p.write_text(new,encoding='utf-8-sig')
        adaptations.append({'path':p.relative_to(stage).as_posix(),'change':'UTF-8 BOM for Windows PowerShell 5'+('; create runtime/state' if p.name=='Start-TdxApi.ps1' else '')})
    (stage/'verify_package.py').write_text(VERIFY,encoding='utf-8')
    copy(ROOT/'tools/START-package.cmd',stage/'START.cmd')
    copy(ROOT/'tools/CREATE-DESKTOP-SHORTCUT.cmd',stage/'CREATE-DESKTOP-SHORTCUT.cmd')
    (stage/'VERIFY.cmd').write_text('@echo off\ncd /d "%~dp0"\npython verify_package.py\nif errorlevel 1 exit /b 1\ncd project\npython -m unittest discover -s tests -v\npause\n',encoding='ascii')
    (project/'requirements-optional.txt').write_text('# Only needed for Python PNG verification/finalize helpers; core and workbench use the standard library.\nPillow>=11,<13\n',encoding='ascii')
    readme='''# 全部算法与工作台 2.1 完整包

解压到任意目录。需要Python 3.11或更高版本，并能在终端执行`python`。Windows双击`START.cmd`打开工作台；演示默认是奥雅股份（300949）。浏览器导出PNG不需要安装Node或额外Python库。

包内内容：V1/V2结构引擎、完成走势类型递归、中枢证书、背驰门控、真实多周期触发、全市场扫描、逐日回放、TDX接入、11种K线与历史分时采集、工作台2.1、完整测试、规则文档与知识库。TDX Windows程序及Go源码、图表库及LICENSE/NOTICE也已包含。

## 运行

1. 在完整解压目录内双击`START.cmd`。需要桌面入口时，运行`CREATE-DESKTOP-SHORTCUT.cmd`，以后双击它创建的桌面快捷方式。不要把CMD文件单独复制到桌面；它依赖同目录的project。也可在`project`中执行`powershell -NoProfile -ExecutionPolicy Bypass -File .\\Start-Workbench.ps1 -OpenBrowser`。
2. 打开 http://127.0.0.1:8791/?symbol=sz300949 ，浏览离线示例、全历史日线和各周期。
3. 获取最新行情前，进入“数据与口径”点击“启动 / 检查行情服务”；也可在`project`运行`Start-TdxApi.ps1`。TDX监听127.0.0.1:18080，需要网络。
4. 新建全市场任务时选择“重新从TDX获取行情”。本包含当前5,580只股票名单和300949验证示例；全市场历史行情缓存需重新下载或从原项目复制`market_data`目录。

已有原工作台占用8791时，启动器会使用它。要单独测试本包，可在`project`运行`python -m workbench.server --port 8793`，然后访问8793端口。关闭网页不停止后台任务。

## 命令行

在`project`目录运行：

```powershell
python run.py demo --output-dir examples
python run_v2.py analyze --symbol sz300949 --period day --cache market_data --cutoff 2026-11-06T15:00:00+08:00 --output runs/demo-day-result.json
python run_v2.py multiframe --symbol sz300949 --cache market_data --cutoff 2026-11-06T15:00:00+08:00 --volume-tolerance-shares 100 --output runs/demo-multiframe-result.json
python -m unittest discover -s tests -v
```

`run.py`、`market_scan.py`、`intraday_scan.py`及`history_replay.py`保留原V1流程；V2使用`run_v2.py`或工作台。不会把旧批次的V1输出称作V2。`tools`中的历史批次审计和打包工具也完整保留，其针对原大型批次的操作需要相应原始批次数据。

核心与工作台仅使用Python标准库。若需使用Python辅助脚本核验/重写PNG，执行`python -m pip install -r requirements-optional.txt`。重新构建TDX程序需要Go 1.23+，在`vendor/tdx-api/web`中执行`go build -o ../../../runtime/tdx-api-revised.exe .`。Go依赖按go.mod/go.sum下载。常规Windows运行不必安装Go。

## 随包示例与范围

300949原始接口回执、10种原生K线、聚合5日K线、1,381天历史分时及算法证据随包保存；日线2021-02-26至2026-11-06，1,381根。1分钟原生K线从2026-06-22起，5/15/30/60分钟从2024-10-31起。竞价历史接口不提供。形成中的日历周期不参与结构确认。

`delivery/aoya-verification`包含完整历史PNG、11周期总览、逐日回放事件和数据覆盖核验。工作台数据库只预置该演示，不携带原机器正在运行的任务。知识库在同级`缠论知识库`目录。

`MANIFEST.json`为逐文件SHA-256清单，`python verify_package.py --all`在首次启动前验证所有文件；运行后可使用不带`--all`的方式，跳过正常变化的任务数据库。`VERIFY.cmd`同时验证文件与测试。软件及资料的来源、版本、修改见`PACKAGE_INFO.json`，第三方许可证随源文件保留。

算法仍采用明确的研究分解规范，未证明与原著全部定义等价；`execution_allowed=false`。完整的是当前工程实现与材料，不表示实现了不存在的竞价接口或突破了行情供应商的历史范围。
'''
    (stage/'先读我.md').write_text(readme,encoding='utf-8')
    (project/'README.md').write_text('# 当前完整包入口\n\n当前工作台版本2.1，最终测试数量见包内delivery/package-verification。优先阅读上级目录“先读我.md”和“工作台2.1更新说明.md”。下文保留原版本演进说明，其中测试数量与完成状态对应当时版本。\n\n'+(project/'README.md').read_text(encoding='utf-8'),encoding='utf-8')
    commit=subprocess.run(['git','-C',str(ROOT/'vendor/tdx-api'),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    core=[p for p in (ROOT/'chanmodel').rglob('*.py') if '__pycache__' not in p.parts]
    assert all(sha(p)==sha(project/p.relative_to(ROOT)) for p in core)
    info={'version':'2.1.0','launcher_revision':'20261108-desktop-fix','created_at':datetime.now(CN).isoformat(),'scope':'complete current algorithm source, workbench, knowledge base, TDX source and Windows binary, validated stock demo',
          'core_sources_copied_byte_for_byte':len(core),'tdx_repository':'https://github.com/oficcejo/tdx-api','tdx_base_commit':commit,
          'tdx_local_modifications_included':True,'tdx_binary_sha256':sha(project/'runtime/tdx-api-revised.exe'),
          'package_adaptations':adaptations,'full_market_quote_cache_included':False,'single_stock_complete_example':'sz300949',
          'runtime_jobs_copied':False,'python_minimum':'3.11','go_build_minimum':'1.23','execution_allowed':False}
    atomic_json(stage/'PACKAGE_INFO.json',info)
    print(json.dumps({'stage':str(stage),'copied_core_files':len(core),'universe':sum(r['active'] for r in universe)},ensure_ascii=False),flush=True)


def manifest(stage):
    files=[]
    for p in sorted(stage.rglob('*')):
        if not p.is_file() or p.name=='MANIFEST.json' or '__pycache__' in p.parts:continue
        files.append({'path':p.relative_to(stage).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p),'mutable':p.suffix in ('.sqlite3',)})
    atomic_json(stage/'MANIFEST.json',{'version':'2.1.0','files':files})
    return files


def archive(stage,path):
    files=manifest(stage)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:z.write(p,stage.name+'/'+p.relative_to(stage).as_posix())
    with zipfile.ZipFile(path) as z:
        bad=z.testzip()
        if bad:raise ValueError('bad ZIP entry: '+bad)
    return {'files':len(files)+1,'bytes':path.stat().st_size,'sha256':sha(path)}


def free_port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def verify_extracted(stage,output):
    project=stage/'project';output.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'PYTHONIOENCODING':'utf-8'}
    with (output/'tests.stdout.log').open('w',encoding='utf-8') as stdout,(output/'tests.stderr.log').open('w',encoding='utf-8') as stderr:
        test=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=project,env=env,stdout=stdout,stderr=stderr)
    result=(output/'tests.stderr.log').read_text(encoding='utf-8');match=re.search(r'Ran (\d+) tests in ([\d.]+)s',result)
    if test.returncode or not match or not result.rstrip().endswith('OK'):raise RuntimeError('extracted tests failed; inspect '+str(output))
    print(json.dumps({'extracted_tests':int(match[1]),'seconds':float(match[2])}),flush=True)
    before=subprocess.run([sys.executable,str(stage/'verify_package.py'),'--all'],cwd=stage,env=env,capture_output=True,text=True,encoding='utf-8')
    if before.returncode:raise RuntimeError(before.stdout+before.stderr)
    def request(port,path):
        with urllib.request.urlopen(f'http://127.0.0.1:{port}'+path,timeout=45) as response:return json.load(response)
    processes=[];handles=[];smoke={}
    try:
        web_port=free_port();web_log=(output/'workbench.log').open('wb');handles.append(web_log)
        proc=subprocess.Popen([sys.executable,'-m','workbench.server','--port',str(web_port)],cwd=project,env=env,stdout=web_log,stderr=web_log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0);processes.append(proc)
        for _ in range(25):
            if proc.poll() is not None:raise RuntimeError('extracted workbench exited')
            try:health=request(web_port,'/api/health');break
            except OSError:time.sleep(.4)
        else:raise RuntimeError('extracted workbench startup timeout')
        overview=request(web_port,'/api/overview');stock=request(web_port,'/api/stock/sz300949')
        day=next(p for p in stock['chart']['panels'] if p['period']=='day');assert len(day['bars'])==1381
        assert day['bars'][0]['date_cn'].startswith('2021-02-26')
        history=request(web_port,'/api/stock/sz300949?period=timeshare&date=2021-11-22');assert len(history['panel']['points'])==240
        minute=request(web_port,'/api/stock/sz300949?period=1m');assert len(minute['panel']['bars'])==22560
        with urllib.request.urlopen(f'http://127.0.0.1:{web_port}/assets/lightweight-charts.standalone.production.js') as r:assert len(r.read())>100000
        smoke['workbench']={'status':'pass','universe':overview['total'],'daily_bars':1381,'first_daily_bar':day['bars'][0]['date_cn'],'historical_time_share_points':240,'native_1m_bars':22560,'chart_asset_available':True,'version':overview['version']}
        cli=subprocess.run([sys.executable,'run_v2.py','multiframe','--symbol','sz300949','--cache','market_data','--cutoff','2026-11-06T15:00:00+08:00','--volume-tolerance-shares','100','--output',str(output/'cli-multiframe.json')],cwd=project,env=env,capture_output=True,text=True,encoding='utf-8')
        if cli.returncode:raise RuntimeError(cli.stdout+cli.stderr)
        analysis=json.loads((output/'cli-multiframe.json').read_text(encoding='utf-8'));assert analysis['state']=='calculated'
        smoke['cli']={'status':'pass','state':analysis['state'],'exit_code':cli.returncode}
        if os.name=='nt':
            port=free_port();log=(output/'tdx.log').open('wb');handles.append(log)
            proc=subprocess.Popen([str(project/'runtime/tdx-api-revised.exe')],cwd=project/'runtime/state',env={**env,'TDX_API_ADDR':f'127.0.0.1:{port}','TDX_API_LITE':'1','TZ':'Asia/Shanghai'},stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW);processes.append(proc)
            for _ in range(40):
                if proc.poll() is not None:raise RuntimeError('bundled TDX binary exited')
                try:q=request(port,'/api/quote?code=sz300949');break
                except OSError:time.sleep(.5)
            else:raise RuntimeError('bundled TDX quote timeout')
            assert q['code']==0 and q['data'][0]['Code']=='300949'
            smoke['tdx_binary']={'status':'pass','real_quote_received':True,'code':'300949','price':q['data'][0]['K']['Close']/1000}
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=10)
        for handle in handles:handle.close()
    receipt={'status':'pass','verified_in_separate_extracted_directory':True,'tests':{'count':int(match[1]),'exit_code':test.returncode},'source_manifest':json.loads(before.stdout),'smoke':smoke}
    atomic_json(output/'verification.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False),flush=True)
    return receipt


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);args=p.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    release='Chanlun-Full-2.1.0-20261108';stage=output/'staging'/release
    if stage.exists():raise ValueError('Use a fresh output directory')
    build(stage)
    pre=output/(release+'.candidate.zip');archive(stage,pre)
    extracted=output/'unpacked verification'
    with zipfile.ZipFile(pre) as z:z.extractall(extracted)
    verification=verify_extracted(extracted/release,output/'verification')
    tree(output/'verification',stage/'delivery/package-verification')
    archive_path=output/'缠论全部算法与工作台2.1完整包-20261108.zip';receipt=archive(stage,archive_path)
    receipt.update(archive=str(archive_path),verification=verification,zip_integrity='pass')
    atomic_json(output/'package-receipt.json',receipt)
    (output/'SHA256.txt').write_text(receipt['sha256']+'  '+archive_path.name+'\n',encoding='utf-8')
    print(json.dumps({'archive':str(archive_path),'files':receipt['files'],'MiB':round(receipt['bytes']/1024**2,2),'sha256':receipt['sha256'],'status':'pass'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
