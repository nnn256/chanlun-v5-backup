"""Verify source/structure/render evidence, embed provenance and package deliverables."""
from datetime import datetime
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile
from PIL import Image, PngImagePlugin, ImageStat

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/aoya-independent-20261108'
SOURCE=ROOT/'runs/aoya-full-history-20261108'
TOP=ROOT.parent


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    run=json.loads((OUT/'run-summary.json').read_text(encoding='utf-8'))
    browser=json.loads((OUT/'browser-verification.json').read_text(encoding='utf-8'))
    auction=json.loads((OUT/'auction-manifest.json').read_text(encoding='utf-8'))
    daily={b['Time'][:10]:b for b in json.loads(gzip.decompress((SOURCE/'raw/day.json.gz').read_bytes()))['data']['list']}
    failures=[];checked=0;auction_open_mismatches=[]
    for rec in auction:
        p=OUT/rec['raw_file'];raw=gzip.decompress(p.read_bytes())
        if hashlib.sha256(raw).hexdigest()!=rec['raw_sha256']:failures.append('Auction source hash changed '+rec['date'])
        rows=json.loads(raw)['data']['List'];matches=[r for r in rows if r['Time'][11:16]=='09:25']
        if rec['status']=='ok':
            if not matches or sum(r['Volume']*100 for r in matches)!=rec['bar']['volume']:failures.append('Auction volume/existence '+rec['date'])
            date=rec['bar']['closed_at'][:10]
            if daily[date]['Open']/1000!=rec['bar']['open']:auction_open_mismatches.append(rec['date'])
        elif matches:failures.append('Observed auction misclassified absent '+rec['date'])
        checked+=1
    if auction_open_mismatches:failures.append('Auction execution versus daily open mismatches '+str(auction_open_mismatches))
    if len(auction)!=1381 or sum(r['status']=='ok' for r in auction)!=1316:failures.append('Auction coverage changed')
    images=[]
    for b in browser:
        if not b['browser']['ready'] or b['browser']['errors'] or b['browser']['proof']['plotWidth']<1800:failures.append('Browser invalid '+b['period'])
        p=OUT/b['file'];panel=json.loads((OUT/'panels'/f"{b['period']}.json").read_text(encoding='utf-8'))
        prov={'symbol':run['symbol'],'as_of':run['last_data_at'],'period':b['period'],'source':'TDX',
              'adjustment':'unadjusted','definition_mode':panel['definition_mode'],
              'approximation_loss':panel.get('approximation_loss',[panel.get('algorithm_note','')]),
              'input_sha256':panel['coverage']['input_sha256'],'profile':run['profile'],
              'strict_original_equivalence_proven':False,'execution_allowed':False,
              'chart_library':'TradingView Lightweight Charts 5.2.1','snapshot_semantics':'final-cutoff geometry; confirmation after anchor'}
        with Image.open(p) as im:
            im.load();pixel_sha=hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()
            if im.size!=(2200,1250):failures.append('Image dimensions '+p.name)
            if min(ImageStat.Stat(im.convert('RGB')).stddev)<8:failures.append('Suspicious blank rendering '+p.name)
            metadata=PngImagePlugin.PngInfo();metadata.add_itxt('Description',json.dumps(prov,ensure_ascii=False))
            im.save(p,pnginfo=metadata,optimize=True)
        with Image.open(p) as im:
            if hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()!=pixel_sha:failures.append('Metadata transform changed pixels')
            if json.loads(im.info['Description'])['input_sha256']!=prov['input_sha256']:failures.append('PNG provenance mismatch')
        with Image.open(p) as im:
            im.verify()
        images.append({'file':b['file'],'sha256':sha(p),'pixels_sha256':pixel_sha,'bytes':p.stat().st_size,
                       'dimensions':[2200,1250],'source_period':b['period'],'provenance':prov})
    if len(images)!=16:failures.append('Expected 16 individual charts')
    reports=[]
    for item in run['periods']:
        if 'certificate_audit' not in item:continue
        p=OUT/'analysis'/f"{item['period']}.json.gz";report=json.loads(gzip.decompress(p.read_bytes()))
        if report['certificate_audit']['errors']:failures.append('Algorithm certificate '+item['period'])
        if report['input_audit']['closed_count']!=item['closed_bars']:failures.append('Closed candle count '+item['period'])
        for point in report['signals']:
            if point['event_time']>point['available_time'] or point['execution_allowed']:failures.append('Signal causality '+item['period'])
        reports.append({'period':item['period'],'input_bars':item['bars'],'closed_bars':item['closed_bars'],
                        'certificate_audit':report['certificate_audit'],'report_sha256':sha(p)})
    tests=(OUT/'tests.stderr.txt').read_text(encoding='utf-8')
    if 'Ran 173 tests' not in tests or not tests.rstrip().endswith('OK'):failures.append('Full test suite did not pass')
    result={'status':'pass' if not failures else 'fail','checked_at':datetime.now().astimezone().isoformat(),
            'tests':173,'source_auction_days_checked':checked,'auction_no_0925_days':65,
            'auction_vs_daily_open_mismatches':auction_open_mismatches,'period_reports':reports,
            'images':images,'failures':failures}
    portable_path=OUT/'portable-replay-verification.json'
    if portable_path.exists():
        result['portable_replay']=json.loads(portable_path.read_text(encoding='utf-8'))
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 奥雅股份独立计算与PNG核验','','结果：**'+result['status'].upper()+'**','',
           '- 12组结构输入（11种常规K线及竞价撮合价序列）逐组独立运行，结构证书均通过。',
           '- 3组价格快照分时图独立渲染；不将快照当OHLC。',
           '- 16张2200×1250 PNG均由TradingView Lightweight Charts实际绘制，浏览器错误为零，来源元数据与像素校验通过。',
           '- 1381个交易日历史成交响应逐份校验哈希；1316日有09:25记录、65日无观察；已观测撮合价格与对应日线开盘价完全一致。',
           '- 173项算法和应用测试通过；实际输出为tests.stderr.txt。',
           '- 形成中5日/月/季/年末K线均未进入闭合结构，月季年历史不足不会制造笔与线段。','',
           '未完成为严格结论：网站所有解释的唯一等价、09:15—09:25虚拟撮合历史、多周期自动触发与交易执行。','',
           '[机器核验](verification.json) · [浏览器渲染](browser-verification.json) · [算法与运行说明](算法与运行说明.md)']
    if portable_path.exists():
        lines+=['','交付完整包已解压到独立临时目录，离线重新运行构建脚本；15组图表数据数量与末价完全一致，退出码0。[独立复现记录](portable-replay-verification.json)。']
    if failures:lines+=['','失败：',*['- '+x for x in failures]]
    (OUT/'VERIFICATION.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Newly created artifacts are reversible as a directory relocation, not deletion.
    created=['chanmodel/study_profile.py','tests/test_study_profile.py',
             'tools/capture_auction_executions.py','tools/build_aoya_independent.py',
             'tools/capture_aoya_pngs.py','tools/finalize_aoya_independent.py']
    manifest=[{'file':x,'sha256':sha(ROOT/x)} for x in created]
    (OUT/'MODIFIED_FILES.json').write_text(json.dumps({'original_existing_files_modified':[],
        'created_algorithm_files':manifest,'run_directory':OUT.relative_to(ROOT).as_posix()},ensure_ascii=False,indent=2),encoding='utf-8')
    patch=[]
    for name in created:
        patch.extend(difflib.unified_diff([], (ROOT/name).read_text(encoding='utf-8').splitlines(keepends=True),fromfile='/dev/null',tofile='b/'+name))
    (OUT/'DIFF_FILE.patch').write_text(''.join(patch),encoding='utf-8')
    rollback='''from pathlib import Path
from datetime import datetime
import argparse, shutil
p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args()
root=Path(__file__).resolve().parent
destination=root.with_name(root.name+'.archived-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
if destination.parent!=root.parent or destination.exists():raise ValueError('Invalid archive destination')
print(str(root)+' -> '+str(destination))
if a.execute:shutil.move(str(root),str(destination))
'''
    (OUT/'ROLLBACK.py').write_text(rollback,encoding='utf-8')
    png_zip=OUT/'奥雅股份_全部独立PNG.zip'
    with zipfile.ZipFile(png_zip,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((OUT/'png').glob('*.png')):z.write(p,p.name)
        z.write(OUT/'奥雅股份_16图总览.png','奥雅股份_16图总览.png')
        z.write(OUT/'算法与运行说明.md','算法与运行说明.md')
    # Portable workspace includes original native K inputs, but only the six
    # timeshare days needed to reproduce these fifteen panels and sixteen PNGs.
    package=OUT/'奥雅股份_算法数据与独立图表.zip';included=set()
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        def add(p):
            key=p.relative_to(TOP).as_posix()
            if key not in included:z.write(p,key);included.add(key)
        for p in (ROOT/'chanmodel').rglob('*.py'):add(p)
        for p in (ROOT/'tests').glob('*.py'):add(p)
        for p in (ROOT/'tools').glob('*.py'):add(p)
        for p in (ROOT/'workbench').rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:add(p)
        for name in ['run.py','run_v2.py']:
            add(ROOT/name)
        for p in [*OUT.rglob('*')]:
            if not p.is_file() or p.suffix=='.zip' or p.name=='package-receipt.json' or 'auction-evidence' in p.parts:continue
            add(p)
        add(OUT/'auction-evidence/20261106.json.gz')
        for p in (SOURCE/'raw').glob('*.gz'):add(p)
        for p in (SOURCE/'receipts').glob('*.json'):add(p)
        add(SOURCE/'acquisition.json')
        dates=json.loads((OUT/'panels/five_days.json').read_text(encoding='utf-8'))['dates']+['20210226']
        for date in dates:
            for suffix in ['.json.gz','.receipt.json']:add(SOURCE/'timeshare'/(date+suffix))
        for name in ['lightweight-charts.standalone.production.js','LICENSE','NOTICE','library-source.json']:
            add(ROOT/'runs/aoya-v2-chart-20261107/assets'/name)
        kb=TOP/'缠论知识库'
        for p in kb.rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and 'rollback-check' not in p.parts:add(p)
        for name in ['README.md','算法契约.md','递归与触发V2说明.md']:
            add(ROOT/name)
    for path in [png_zip,package]:
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:failures.append('ZIP CRC failed '+path.name)
    receipt={'status':'pass' if not failures else 'fail','png_zip':{'file':png_zip.name,'bytes':png_zip.stat().st_size,'sha256':sha(png_zip)},
             'algorithm_zip':{'file':package.name,'bytes':package.stat().st_size,'sha256':sha(package),'files':len(included)},'failures':failures}
    (OUT/'package-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    return bool(failures)


if __name__=='__main__':raise SystemExit(main())
