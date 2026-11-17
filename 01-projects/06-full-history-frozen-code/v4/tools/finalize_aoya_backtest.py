"""Assemble checked backtest tables, PNG provenance, source/rule evidence and ZIPs."""
from collections import Counter
from datetime import datetime
import difflib,gzip,hashlib,json,re,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageStat,PngImagePlugin

ROOT=Path(__file__).resolve().parents[1];TOP=ROOT.parent;OUT=ROOT/'runs/aoya-backtest-abcd-20261108';OLD=ROOT/'runs/aoya-independent-20261108'
sys.path.insert(0,str(ROOT))
from chanmodel.tdx_data import CN,atomic_json

NEW=['chanmodel/causal_replay.py','chanmodel/causal_portfolio.py','tests/test_causal_backtest.py',
     'tools/run_aoya_confirmed_backtest.py','tools/refresh_aoya_simulations.py','tools/build_aoya_abcd_charts.py',
     'tools/capture_aoya_backtest.py','tools/verify_aoya_backtest.py','tools/finalize_aoya_backtest.py']


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def pct(x):return '—' if x is None else f'{x*100:.2f}%'


def main():
    sys.stdout.reconfigure(encoding='utf-8');errors=[]
    run=json.loads((OUT/'run-summary.json').read_text(encoding='utf-8'))
    verified=json.loads((OUT/'backtest-verification.json').read_text(encoding='utf-8'))
    if verified['status']!='pass':raise ValueError('Backtest validation did not pass')
    browser=json.loads((OUT/'browser-verification.json').read_text(encoding='utf-8'));images=[];original_pages=0;confirmed_topics=0
    panels={item['period']:json.loads((OUT/'panels'/f'{item["period"]}.json').read_text(encoding='utf-8')) for item in run['catalog']}
    for b in browser:
        proof=b['browser']['proof'];p=panels[b['period']]
        if b['browser']['errors'] or not b['browser']['ready']:errors.append('Browser failed '+b['file'])
        if b.get('expect_original_labels'):
            if set(proof['abcd']['originalLabels'])!=set('aAbBcd'):errors.append('Original formula labels missing')
            original_pages+=1
        if b.get('confirmation_id'):
            if proof['abcd']['confirmedMarkers']<1:errors.append('Confirmed marker absent')
            confirmed_topics+=1
        path=OUT/b['file']
        metadata={'symbol':'sz300949','period':b['period'],'as_of':run['last_data_at'],'source':'TDX',
                  'profile':run['profile'],'definition_mode':p.get('definition_mode'),
                  'analysis_adjustment':'causal_forward_1.45_split_from_2026-05-29','execution_prices':'raw_unadjusted',
                  'input_sha256':p['coverage']['input_sha256'],'execution_allowed':False,
                  'strict_original_equivalence_proven':False,
                  'confirmation_semantics':'first observed source-clause pass in every-bar prefix replay, may later invalidate or withdraw',
                  'abcd_modes':['four_consecutive_same_rank','a+A+b+B+c with observed continuation d'],
                  'portfolio_metrics':p.get('portfolio_metrics')}
        with Image.open(path) as im:
            im.load();pixel_hash=hashlib.sha256(im.convert('RGB').tobytes()).hexdigest();size=im.size
            if size[0]!=2400 or size[1]<2500:errors.append('PNG dimension '+path.name)
            if min(ImageStat.Stat(im.convert('RGB')).stddev)<6:errors.append('Blank PNG '+path.name)
            info=PngImagePlugin.PngInfo();info.add_itxt('Description',json.dumps(metadata,ensure_ascii=False));im.save(path,pnginfo=info,optimize=True)
        with Image.open(path) as im:
            if hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()!=pixel_hash:errors.append('Pixel transform altered data')
        with Image.open(path) as im:im.verify()
        images.append({'file':b['file'],'size':list(size),'bytes':path.stat().st_size,'sha256':sha(path),'pixels_sha256':pixel_hash})
    if confirmed_topics!=run['confirmation_count']:errors.append('Not all confirmation events received a topic PNG')
    if original_pages<1:errors.append('No complete original formula displayed')
    summary=run['backtests'];labels={'day':'日线','60m':'60分钟','30m':'30分钟','15m':'15分钟','5m':'5分钟','1m':'1分钟'}
    lines=['# 奥雅股份：原文条款确认回测与双ABCD','','日期：2026-11-08。实际行情截至2026-11-06。',
        f'完成{run["actual_replayed_bars"]:,}根闭合K线的逐根因果回放，共{run["confirmation_count"]}个原文条款门控确认事件、{sum(x["metrics"]["completed_trades"] for x in summary)}笔已平仓模拟交易。','',
        '每个周期使用独立10万元现金账户；下表不能相加。确认是当前规范下的结构事实，不是未来盈利保证。', '',
        '| 周期 | 数据起点 | K线数 | 确认事件 | 已平仓 | 交易胜率 | 组合净收益 | 最大回撤 | 费用/元 |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for s in summary:
        m=s['metrics'];lines.append(f'| {labels[s["period"]]} | {s["first"][:10]} | {s["bars"]:,} | {s["confirmed"]} | {m["completed_trades"]} | {pct(m["win_rate"])} | {pct(m["total_return"])} | {pct(m["max_drawdown"])} | {m["total_fees"]:.2f} |')
    profit_rows=[]
    for s in summary:
        pf=json.loads(gzip.decompress((OUT/s['period']/'portfolio.json.gz').read_bytes()))
        realized=sum(t['net_profit'] for t in pf['trades']);last=pf['equity'][-1];position=pf['open_position']
        unrealized=0 if not position else last['shares']*last['close']+position['sale_proceeds']-position['entry_cost']
        if abs(100000+realized+unrealized-last['equity'])>1e-6:errors.append('Realized/open profit reconciliation failed')
        profit_rows.append({'period':s['period'],'realized_net_profit':realized,'open_position_mark_profit':unrealized,
                            'ending_shares':last['shares'],'ending_equity':last['equity'],'reconciles':True})
    atomic_json(OUT/'realized-and-open-profit.json',profit_rows)
    lines+=['','## 已平仓与期末持仓分开看','','| 周期 | 已实现净损益/元 | 未平仓浮动损益/元 | 期末持股 |','| --- | ---: | ---: | ---: |']
    for row in profit_rows:lines.append(f'| {labels[row["period"]]} | {row["realized_net_profit"]:.2f} | {row["open_position_mark_profit"]:.2f} | {row["ending_shares"]:g} |')
    lines+=['','1分钟账户的正净值变化包含未平仓浮盈，已平仓交易合计亏损；不能把总净值增长全部称为已实现收益。逐账户满足初始现金+已实现净损益+期末浮动损益=期末权益。']
    lines+=['','确认的类型与限制：本次通过门控的事件全部属于第三类买卖点。第一、第二类及L1线段代理没有为了增加交易而放宽；未满足条件的信号保留候选/失效状态。',
            '回测基准已预先固定：T+1、100股买入、上一根成交量1%上限、下一根开盘、单边5bp滑点、佣金万三最低5元、分日期印花税/过户费、20%开盘涨跌停阻挡、结构失效或20交易日退出。不是每笔都把十万元全仓投入。','',
            '## 固定敏感性对照','','| 周期 | 基础净收益 | 再延迟一根 | 滑点10bp |','| --- | ---: | ---: | ---: |']
    for s in summary:lines.append(f'| {labels[s["period"]]} | {pct(s["sensitivities"]["base"]["total_return"])} | {pct(s["sensitivities"]["one_bar_extra_latency"]["total_return"])} | {pct(s["sensitivities"]["ten_bps_slippage"]["total_return"])} |')
    lines+=['','没有根据结果调整参数来提高收益。只有一个标的、样本数量有限，不作样本外或稳定收益结论。','',
            '## 原文对应与确定信号','','新增确认门会重新检查真实次级别走势类型、中心交集、第一次回试、不触边、末段真实极值和反向次级边界。确认时刻由当时前缀首次满足得到。买卖点位置按整个回试段真实极值修正，分解终点另存，参见53课。',
            '严格原文所有解释等价尚未证明。基础线段L0和同级切分是声明的形式化约定；本版确认不把L1线段代理当成完整下级走势类型。等待额外反向完成边界是保守约定，会让确认明显滞后。详见[规则与ABCD说明](原文确认规则与ABCD说明.md)。','',
            '## 两种ABCD已显示','','小写a/b/c/d显示连续四个同级对象；原文a+A+b+B+c保留大写中枢A/B，并附已观察后续段d。缺段显示缺项，不制造原文没有的结构。',
            f'交付{len(images)}张PNG，包括各周期、完整回测历史、每个真实确认事件及完整字母公式专题；[离线交互图表](index.html)可切换字母秩、原文实例和确认记录。','',
            '## 已执行核验','',
            f'- 全套{verified["tests"]}项测试通过：流式/批量每根前缀一致、未来尾部不改过去事件、确认后失效/撤回保留、T+1、涨跌停、费用、转增和跳空失效取消。',
            f'- {run["confirmation_count"]}个确认逐个在确认时刻重新批量构造结构，检查全部原文门控、真实极值和时间；不采用最终图的历史状态。',
            '- 所有模拟成交都有对应确认；成交K线晚于确认K线，权益=现金+股数×原始末价；转增生效前价格不被未来因子重写。',
            '- 全部PNG核对浏览器ready、错误列表、字母/确认实际绘制、尺寸、像素与来源元数据。','',
            '[回测机器证据](backtest-verification.json) · [浏览器证据](browser-verification.json) · [统计JSON](backtest-summary.json) · [费用与运行设置](settings.json) · [除权证据](corporate-actions.json)','',
            '各周期子目录提供confirmed-signals.csv、trades.csv、portfolio.json.gz和signal-ledger.json.gz。模拟成交时间已按下一根开盘时刻记录；K线时间标签为收盘时刻，二者分列。']
    (OUT/'回测报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Summary figure complements the full TradingView screenshots with readable
    # per-period numbers. It contains results, not synthetic market prices.
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',24);smallfont=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',19);bigfont=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',37)
    image=Image.new('RGB',(1700,990),'#f1f5f8');draw=ImageDraw.Draw(image)
    draw.text((48,35),'奥雅股份 · 原文条款确认回测',font=bigfont,fill='#244765')
    draw.text((50,97),f'61,181 根逐根回放  /  {run["confirmation_count"]} 个确认事件  /  各周期独立10万元账户  /  截至2026-11-06',font=smallfont,fill='#6a8196')
    headers=['周期','确认','平仓','胜率','净收益','最大回撤','费用/元'];xs=[55,255,410,565,770,1020,1300]
    for x,t in zip(xs,headers):draw.text((x,162),t,font=font,fill='#486a87')
    for i,s in enumerate(summary):
        m=s['metrics'];y=219+i*85;draw.rounded_rectangle((40,y-9,1645,y+61),radius=5,fill='#ffffff')
        vals=[labels[s['period']],str(s['confirmed']),str(m['completed_trades']),pct(m['win_rate']),pct(m['total_return']),pct(m['max_drawdown']),f'{m["total_fees"]:.2f}']
        for j,(x,t) in enumerate(zip(xs,vals)):draw.text((x,y),t,font=font,fill=('#ad4b59' if m['total_return']>0 else '#298775') if j==4 else '#355775')
    draw.text((50,775),'确认 ≠ 盈利保证；确认时间晚于价格锚点。L0与同级切分仍采用声明规范。',font=smallfont,fill='#657f95')
    draw.text((50,817),'成本 / T+1 / 限价与流动性限制 / 10转4.5股处理均已纳入。',font=smallfont,fill='#657f95')
    draw.text((50,859),'ABCD同时显示：连续 a/b/c/d + 原文 a+A+b+B+c（附实际后续d）。',font=smallfont,fill='#657f95')
    one=next(x for x in profit_rows if x['period']=='1m')
    draw.text((50,901),f'1分钟期末持股{one["ending_shares"]:g}股：已实现 {one["realized_net_profit"]:.2f}元 / 未平仓浮盈 {one["open_position_mark_profit"]:.2f}元。',font=smallfont,fill='#657f95')
    image.save(OUT/'奥雅股份_确认回测汇总.png',optimize=True)
    topic=next((b for b in browser if b['period']=='1m' and b.get('confirmation_id')),None) or browser[0]
    preview=Image.open(OUT/topic['file']);preview.thumbnail((1280,1280));preview.save(OUT/'preview.png',optimize=True)
    manifest={'existing_files_modified':[],'created_files':[{'file':n,'sha256':sha(ROOT/n)} for n in NEW],
              'chart_template_origin':'runs/aoya-complete-layers-20261108','output_directory':OUT.relative_to(ROOT).as_posix()}
    atomic_json(OUT/'MODIFIED_FILES.json',manifest);patch=[]
    for n in NEW:patch.extend(difflib.unified_diff([], (ROOT/n).read_text(encoding='utf-8').splitlines(keepends=True),fromfile='/dev/null',tofile='b/'+n))
    (OUT/'DIFF_FILE.patch').write_text(''.join(patch),encoding='utf-8')
    rollback='''from pathlib import Path
from datetime import datetime
import argparse,shutil,json,hashlib
p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args()
here=Path(__file__).resolve().parent;root=here.parents[1]
manifest=json.loads((here/'MODIFIED_FILES.json').read_text(encoding='utf-8'))
dest=root/'artifacts'/('backtest-abcd-archive-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
if dest.exists() or not dest.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe archive path')
for row in manifest['created_files']:
 f=(root/row['file']).resolve()
 if not f.is_relative_to(root.resolve()) or hashlib.sha256(f.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Source changed; refusing overwrite')
print(json.dumps({'executed':a.execute,'destination':str(dest)}))
if a.execute:
 dest.mkdir(parents=True)
 for row in manifest['created_files']:
  f=root/row['file'];target=dest/row['file'];target.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(f),str(target))
 shutil.move(str(here),str(dest/'run'))
'''
    (OUT/'ROLLBACK.py').write_text(rollback,encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='aoya-abcd-rollback-') as folder:
        clone=Path(folder);target=clone/'runs/aoya-backtest-abcd-20261108';target.mkdir(parents=True)
        for n in ['ROLLBACK.py','MODIFIED_FILES.json']:shutil.copy2(OUT/n,target/n)
        for row in manifest['created_files']:
            p=clone/row['file'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/row['file'],p)
        proc=subprocess.run([sys.executable,str(target/'ROLLBACK.py'),'--execute'],capture_output=True,text=True,encoding='utf-8')
        moved=Path(json.loads(proc.stdout)['destination']) if proc.returncode==0 else None
        okay=bool(moved) and not target.exists() and all(sha(moved/row['file'])==row['sha256'] for row in manifest['created_files'])
        if not okay:errors.append('Independent rollback failed')
        roll={'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr,'hashes_match':okay,'independent_copy':True}
    result={'status':'pass' if not errors else 'fail','verified_at':datetime.now(CN).isoformat(),'backtest':verified,
            'png_count':len(images),'confirmed_topics':confirmed_topics,'complete_original_formula_topics':original_pages,
            'images':images,'rollback':roll,'errors':errors}
    atomic_json(OUT/'verification.json',result)
    (OUT/'VERIFICATION.txt').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n\n'+(OUT/'tests.stderr.txt').read_text(encoding='utf-8'),encoding='utf-8')
    if errors:print(json.dumps({'status':'fail','errors':errors},ensure_ascii=False));return 1
    pngzip=OUT/'奥雅股份_确认回测与ABCD图.zip'
    with zipfile.ZipFile(pngzip,'w',zipfile.ZIP_DEFLATED) as z:
        for p in (OUT/'png').glob('*.png'):z.write(p,p.name)
        for n in ['奥雅股份_确认回测汇总.png','回测报告.md','原文确认规则与ABCD说明.md']:z.write(OUT/n,n)
    package=OUT/'奥雅股份_因果回测算法数据完整包.zip';included=set()
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        def add(p):
            name=p.relative_to(TOP).as_posix()
            if name not in included:z.write(p,name);included.add(name)
        for folder in ['chanmodel','tools','tests','workbench']:
            for p in (ROOT/folder).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:add(p)
        for n in ['README.md','run.py','run_v2.py','算法契约.md','递归与触发V2说明.md']:add(ROOT/n)
        for p in OUT.rglob('*'):
            if p.is_file() and p.suffix!='.zip' and p.name not in {'package-receipt.json','first-render.png'}:add(p)
        for p in (OLD/'csv').glob('*.csv'):add(p)
        add(OLD/'auction-bars.json')
        full=ROOT/'runs/aoya-complete-layers-20261108';add(full/'run-summary.json')
        for p in (full/'panels').glob('*.json'):add(p)
        for p in (TOP/'缠论知识库').rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and 'rollback-check' not in p.parts:add(p)
    for path in [pngzip,package]:
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:raise ValueError('Archive CRC failure')
    receipt={'status':'pass','png_count':len(images),'tests':verified['tests'],'confirmed':run['confirmation_count'],
             'png_zip':{'file':pngzip.name,'bytes':pngzip.stat().st_size,'sha256':sha(pngzip)},
             'full_zip':{'file':package.name,'bytes':package.stat().st_size,'sha256':sha(package),'files':len(included)}}
    atomic_json(OUT/'package-receipt.json',receipt);print(json.dumps(receipt,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
