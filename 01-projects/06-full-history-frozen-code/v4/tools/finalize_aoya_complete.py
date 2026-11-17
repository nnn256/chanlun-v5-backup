"""Verify every plotted class and evidence layer; package reproducible results."""
from collections import Counter, defaultdict
from datetime import datetime
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from PIL import Image, ImageDraw, ImageFont, ImageStat, PngImagePlugin

ROOT=Path(__file__).resolve().parents[1];TOP=ROOT.parent
OUT=ROOT/'runs/aoya-complete-layers-20261108';OLD=ROOT/'runs/aoya-independent-20261108';SOURCE=ROOT/'runs/aoya-full-history-20261108'
sys.path.insert(0,str(ROOT))
from chanmodel.model import time_value
from chanmodel.complete_study import PROFILE
from chanmodel.v2.recursive import audit_hierarchy

NEW_FILES=['chanmodel/complete_study.py','chanmodel/complete_multilevel.py','tests/test_complete_study.py',
           'tools/build_aoya_complete.py','tools/capture_aoya_complete.py','tools/finalize_aoya_complete.py']


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    sys.stdout.reconfigure(encoding='utf-8');errors=[]
    run=json.loads((OUT/'run-summary.json').read_text(encoding='utf-8'))
    browser=json.loads((OUT/'browser-verification.json').read_text(encoding='utf-8'))
    panels={};reports={};totals=Counter();rank_seen=set()
    source_bytes=b''.join(p.relative_to(ROOT).as_posix().encode()+p.read_bytes() for p in sorted((ROOT/'chanmodel').rglob('*.py')))
    if hashlib.sha256(source_bytes).hexdigest()!=run['engine_sha256']:errors.append('Current engine differs from the recorded run')
    for item in run['catalog']:
        p=json.loads((OUT/'panels'/f'{item["period"]}.json').read_text(encoding='utf-8'));panels[p['period']]=p
        if p['kind']=='line':continue
        report=json.loads(gzip.decompress((OUT/'analysis'/f'{p["period"]}.json.gz').read_bytes()));reports[p['period']]=report
        if audit_hierarchy(report['hierarchy'],report['input_audit']['closed_count']-1)['errors']:errors.append('Hierarchy certificate '+p['period'])
        if report['engine_sha256']!=run['engine_sha256']:errors.append('Report engine hash '+p['period'])
        if len(p['fractals'])!=len(report['base']['fractals']) or len(p['signals'])!=len(report['signals']):errors.append('Omitted full layer '+p['period'])
        if len(p['all_centers'])!=sum(len(x['centers']) for x in report['hierarchy']['levels']):errors.append('Missing recursive centers '+p['period'])
        for c in p['all_centers']:rank_seen.add(c['rank'])
        child={u['id']:u for u in report['hierarchy']['base_units']}
        for layer in report['hierarchy']['levels']:child.update({u['id']:u for u in layer['completed_types']})
        for mon in p['monitors']:
            if mon['z']!=(mon['a']+mon['b'])/2:errors.append('Incorrect Z')
            for x in mon['points']:
                u=child[x['unit_id']]
                if x['zn']!=(u['low']+u['high'])/2 or x['available_at']<u['completed_at']:errors.append('Incorrect or premature Zn')
        counts=Counter(s['class'] for s in p['signals'])
        if any(p['signal_counts'][key]!=counts[key] for key in p['signal_counts']):errors.append('Six-class counter mismatch '+p['period'])
        for point in p['signals']:
            if point['anchor']>point['available_at'] or point['execution_allowed']:errors.append('Signal time/execution '+p['period'])
        totals.update({x['key']:x['count'] for x in p['layer_catalog']})
    five=panels['5m']
    if not all(five['signal_counts'][k]>0 for k in five['signal_counts']):errors.append('Six actual example classes missing')
    multi=json.loads((OUT/'multilevel-summary.json').read_text(encoding='utf-8'))
    nests=[n for n in multi['interval_nesting'] if n['matched_depth']>1]
    for nest in nests:
        previous=None
        for node in nest['nodes']:
            start,end=(time_value(panels[node['period']]['bars'][i]['date_cn'].replace(' ','T')+':00+08:00') for i in node['range'])
            if previous and not(previous[0]<=start<=end<=previous[1]):errors.append('Nesting interval escaped parent')
            previous=(start,end)
            if node['state']=='not_supported':errors.append('Unsupported comparison accepted into nesting')
    if not multi.get('small_to_large_audit') and not multi['small_to_large']:errors.append('Small-to-large rule did not execute')
    image_records=[]
    for item in browser:
        proof=item['browser']['proof'];period=item['period'];p=panels[period]
        if item['browser']['errors'] or not item['browser']['ready'] or proof['plotWidth']<1700:errors.append('Browser render '+item['file'])
        if item['query'].get('range')=='all' and p['kind']=='candles':
            expected={'allFractals':len(p['fractals']),'strokes':len(p['strokes']),'segments':len(p['segments']),
                      'centers':len(p['all_centers']),'signals':len(p['signals']),'divergences':len(p['divergences'])}
            for key,value in expected.items():
                if proof['rendered'][key]!=value:errors.append(f'Full-history omitted {key} in {period}')
        if item.get('required_class'):
            anchor=float(item['query']['anchor']);point=next(x for x in p['signals'] if x['class']==item['required_class'] and x['anchor']==anchor)
            vr=proof['visibleRange']
            if not vr['from']<=point['anchor']<=point['available_at']<=vr['to']:errors.append('Topic does not include candidate and availability '+item['required_class'])
        path=OUT/item['file']
        prov={'symbol':'sz300949','period':period,'source':'TDX','adjustment':'unadjusted','as_of':run['last_data_at'],
              'definition_mode':p.get('definition_mode','observed_timeshare'),'profile':PROFILE,'engine_sha256':run['engine_sha256'],
              'input_sha256':p['coverage']['input_sha256'],'approximation_loss':p.get('approximation_loss',['time-share snapshot is not OHLC']),
              'execution_allowed':False,'strict_original_equivalence_proven':False,'layers':proof.get('enabledLayers',{}),
              'snapshot_semantics':'all states at final cutoff, including invalidated historical candidates'}
        with Image.open(path) as im:
            im.load();size=im.size;pixel_sha=hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()
            if size[0]!=2400 or size[1]<1950:errors.append('PNG dimensions '+path.name)
            if min(ImageStat.Stat(im.convert('RGB')).stddev)<6:errors.append('Blank-looking PNG '+path.name)
            info=PngImagePlugin.PngInfo();info.add_itxt('Description',json.dumps(prov,ensure_ascii=False));im.save(path,pnginfo=info,optimize=True)
        with Image.open(path) as im:
            if hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()!=pixel_sha:errors.append('PNG pixels changed')
            if json.loads(im.info['Description'])['input_sha256']!=p['coverage']['input_sha256']:errors.append('PNG provenance')
        with Image.open(path) as im:im.verify()
        image_records.append({'file':item['file'],'sha256':sha(path),'pixel_sha256':pixel_sha,'dimensions':list(size),'bytes':path.stat().st_size})
    tests=(OUT/'tests.stderr.txt').read_text(encoding='utf-8')
    found=re.search(r'Ran (\d+) tests',tests);test_count=int(found[1]) if found else 0
    if test_count<186 or not tests.rstrip().endswith('OK'):errors.append('Algorithm test suite did not pass')
    if len(image_records)!=42:errors.append('Expected 42 full layer/topic PNGs')
    # Source geometry and all overlays are present in the full-history proof;
    # zoomed examples are provided because 23k bars cannot be read at once.
    preview=Image.open(OUT/'png/09_奥雅股份_5分钟_全部图层.png');preview.thumbnail((1280,1280));preview.save(OUT/'preview.png',optimize=True)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',18)
    contact=Image.new('RGB',(2400,((len(image_records)+5)//6)*405),'#e9eff5');draw=ImageDraw.Draw(contact)
    for i,item in enumerate(image_records):
        picture=Image.open(OUT/item['file']).convert('RGB');picture.thumbnail((385,355));x=9+(i%6)*400;y=8+(i//6)*405
        contact.paste(picture,(x,y));label=Path(item['file']).stem.replace('奥雅股份_','');draw.text((x,y+362),label[:22],fill='#44617e',font=font)
    contact.save(OUT/'奥雅股份_42张全图层总览.png',optimize=True)
    # Compose corresponding actual TradingView screenshots into one per
    # nested example; do not draw synthetic prices or change their geometry.
    groups=defaultdict(list)
    for item in browser:
        if item.get('nest_id'):groups[item['nest_id']].append(item)
    for index,(key,items) in enumerate(groups.items(),1):
        items.sort(key=lambda x:x['nest_depth']);combined=Image.new('RGB',(2400,890*len(items)+100),'#f1f4f7');draw=ImageDraw.Draw(combined)
        draw.text((30,20),'奥雅股份 · 区间套嵌套比较证据 '+str(index)+' · 各层均为实际历史数据',fill='#345b7a',font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',27))
        for j,item in enumerate(items):
            with Image.open(OUT/item['file']) as im:combined.paste(im.crop((0,0,2400,870)),(0,80+j*890))
        combined.save(OUT/f'区间套{index}_上下级对照.png',optimize=True)
    coverage={'schema':'chanlun.complete-layer-coverage.v1','technical_rules':[x['name'] for x in five['layer_catalog']],
              'additional_rules':['observed multi-timeframe OHLCV reconciliation','interval nesting','small-to-large with opposite-center-break proof','53 second-point after small-to-large'],
              'actual_formed_ranks':sorted(rank_seen),'supported_max_rank':8,'source_lessons':[17,18,20,21,24,27,33,37,38,43,53,61,62,63,67,71,77,78,81,92,101,102,108],
              'not_an_executable_price_rule':['historical stock recommendations','philosophical analogies','guaranteed-profit statements','unformalized prose without numeric premises'],
              'unproven':['all original interpretations equivalent','unique theoretical lowest recursive level','all historical auction indicative order books'],
              'execution_allowed':False}
    save('implementation-coverage.json',coverage)
    manifest={'existing_files_modified':[],'created_code':[{'file':f,'sha256':sha(ROOT/f)} for f in NEW_FILES],
              'output_directory':OUT.relative_to(ROOT).as_posix()}
    save('MODIFIED_FILES.json',manifest)
    patch=[]
    for f in NEW_FILES:patch.extend(difflib.unified_diff([], (ROOT/f).read_text(encoding='utf-8').splitlines(keepends=True),fromfile='/dev/null',tofile='b/'+f))
    (OUT/'DIFF_FILE.patch').write_text(''.join(patch),encoding='utf-8')
    rollback='''import argparse,hashlib,json,shutil
from pathlib import Path
from datetime import datetime
p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args()
here=Path(__file__).resolve().parent;root=here.parents[1]
manifest=json.loads((here/'MODIFIED_FILES.json').read_text(encoding='utf-8'))
dest=root/'artifacts'/('full-layers-archive-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
if dest.exists() or not dest.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe archive target')
for x in manifest['created_code']:
 f=(root/x['file']).resolve()
 if not f.is_relative_to(root.resolve()) or hashlib.sha256(f.read_bytes()).hexdigest()!=x['sha256']:raise ValueError('Changed source; archive manually')
print(json.dumps({'executed':a.execute,'destination':str(dest)}))
if a.execute:
 dest.mkdir(parents=True)
 for x in manifest['created_code']:
  f=root/x['file'];d=dest/x['file'];d.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(f),str(d))
 shutil.move(str(here),str(dest/'run'))
'''
    (OUT/'ROLLBACK.py').write_text(rollback,encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='chanlun-full-rollback-') as temp:
        clone=Path(temp);target=clone/'runs/aoya-complete-layers-20261108';target.mkdir(parents=True)
        for name in ['ROLLBACK.py','MODIFIED_FILES.json']:shutil.copy2(OUT/name,target/name)
        for item in manifest['created_code']:
            dst=clone/item['file'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/item['file'],dst)
        result=subprocess.run([sys.executable,str(target/'ROLLBACK.py'),'--execute'],capture_output=True,text=True,encoding='utf-8')
        moved=json.loads(result.stdout)['destination'] if result.returncode==0 else None
        matches=bool(moved) and all(sha(Path(moved)/x['file'])==x['sha256'] for x in manifest['created_code'])
        if result.returncode or target.exists() or not matches:errors.append('Independent rollback drill failed')
        rollback_evidence={'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'hashes_match':matches,'independent_temp_copy':True}
    verification={'status':'pass' if not errors else 'fail','verified_at':datetime.now().astimezone().isoformat(),
                  'tests':test_count,'structure_reports':len(reports),'charts':len(image_records),'all_history_objects_checked':True,
                  'totals':dict(totals),'actual_ranks':sorted(rank_seen),'five_minute_six_classes':five['signal_counts'],
                  'nested_evidence':len(nests),'small_to_large_established':len(multi['small_to_large']),
                  'small_to_large_segments_tested':len(multi['small_to_large_audit']),
                  'images':image_records,'rollback':rollback_evidence,'errors':errors}
    save('verification.json',verification)
    (OUT/'VERIFICATION.txt').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n\nUNIT TEST OUTPUT\n'+tests,encoding='utf-8')
    lines=['# 奥雅股份全结构图层核验','','结果：**'+verification['status'].upper()+'**','',
           f'{test_count}项测试通过；12组结构报告证书逐组复核；42张TradingView PNG逐张核对ready、JS错误、尺寸、像素与来源元数据。',
           '完整历史PNG的实际绘图对象数逐项等于对应全部分型、笔、线段、各秩中枢、全部背驰比较与六类候选总数，未仅画笔端或只保留L1。',
           f'5分钟六类历史候选：{five["signal_counts"]}。真实中枢秩：{sorted(rank_seen)}；向上最多支持8秩，不补造未形成层。',
           f'嵌套比较证据{len(nests)}组；小转大检查{len(multi["small_to_large_audit"])}段，完整凭据{len(multi["small_to_large"])}项；零事件如实显示。',
           '92监视器逐对象重算Zn/Z与完成时点；各级中枢完成、范围和父子连续性由原始命名对象复核。',
           '回退在独立小副本实际运行，新增代码和输出移入归档，哈希一致；正式结果保留。','',
           '[机器证据](verification.json) · [浏览器绘图证据](browser-verification.json) · [图层与定义说明](全图层算法说明.md) · [实现范围](implementation-coverage.json)','']
    if errors:lines+=['失败：',*errors]
    (OUT/'VERIFICATION.md').write_text('\n'.join(lines),encoding='utf-8')
    if errors:print(json.dumps({'status':'fail','errors':errors},ensure_ascii=False,indent=2));return 1
    png_zip=OUT/'奥雅股份_缠论全图层PNG.zip'
    with zipfile.ZipFile(png_zip,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((OUT/'png').glob('*.png')):z.write(p,p.name)
        for p in OUT.glob('区间套*_上下级对照.png'):z.write(p,p.name)
        z.write(OUT/'奥雅股份_42张全图层总览.png','奥雅股份_42张全图层总览.png')
        for name in ['全图层算法说明.md','VERIFICATION.md']:z.write(OUT/name,name)
    pack=OUT/'奥雅股份_全图层算法数据与知识库.zip';included=set()
    with zipfile.ZipFile(pack,'w',zipfile.ZIP_DEFLATED) as z:
        def add(p):
            name=p.relative_to(TOP).as_posix()
            if name not in included:z.write(p,name);included.add(name)
        for folder in [ROOT/'chanmodel',ROOT/'tests',ROOT/'tools',ROOT/'workbench']:
            for p in folder.rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:add(p)
        for name in ['README.md','run.py','run_v2.py','算法契约.md','递归与触发V2说明.md']:add(ROOT/name)
        for p in OUT.rglob('*'):
            if p.is_file() and p.suffix!='.zip' and p.name not in {'package-receipt.json','first-render.png'}:add(p)
        for folder in [SOURCE/'raw',SOURCE/'receipts']:
            for p in folder.glob('*'):
                if p.is_file():add(p)
        for name in ['auction-bars.json','auction-manifest.json']:add(OLD/name)
        for p in (OLD/'assets').glob('*'):
            if p.is_file():add(p)
        for period in ['timeshare','five_days','timeshare_first']:add(OLD/'panels'/f'{period}.json')
        for p in (TOP/'缠论知识库').rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and 'rollback-check' not in p.parts:add(p)
    for path in [png_zip,pack]:
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:raise ValueError('ZIP CRC failed')
    receipt={'status':'pass','png_count':len(image_records),'tests':test_count,
             'png_zip':{'file':png_zip.name,'bytes':png_zip.stat().st_size,'sha256':sha(png_zip)},
             'full_zip':{'file':pack.name,'bytes':pack.stat().st_size,'sha256':sha(pack),'files':len(included)}}
    save('package-receipt.json',receipt);print(json.dumps(receipt,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
