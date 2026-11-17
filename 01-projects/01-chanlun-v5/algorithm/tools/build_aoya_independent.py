"""Run the source-audited profile independently for each requested Aoya chart."""
from collections import Counter
from datetime import datetime
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chanmodel.model import Candle
from chanmodel.signals import macd
from chanmodel.study_profile import analyze_period, CONFIG, PROFILE
from chanmodel.tdx_data import CN, atomic_json, atomic_bytes, now_iso
from workbench.history import NATIVE, LABELS, normalize, five_day, build_panel

SOURCE = ROOT / 'runs/aoya-full-history-20261108'
OUT = ROOT / 'runs/aoya-independent-20261108'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save_panel(panel):
    path = OUT / 'panels' / (panel['period'] + '.json')
    atomic_json(path, panel)
    (path.with_suffix('.js')).write_text('window.PANEL=' + json.dumps(panel, ensure_ascii=False, separators=(',', ':')) + ';', encoding='utf-8')


def line_panel(dates, period, label, title_note):
    points, source_hashes = [], {}
    for date in dates:
        path = SOURCE / 'timeshare' / (date + '.json.gz')
        raw = gzip.decompress(path.read_bytes())
        receipt = json.loads((SOURCE / 'timeshare' / (date + '.receipt.json')).read_text(encoding='utf-8'))
        if digest(raw) != receipt['receipt']['response_sha256']:
            raise ValueError('Time-share response hash changed')
        payload = json.loads(raw)['data']
        if payload.get('date') != date:
            raise ValueError('Historical time-share identity mismatch')
        source_hashes[date] = digest(raw)
        for row in payload['List']:
            point = datetime.strptime(date + ' ' + row['Time'], '%Y%m%d %H:%M').replace(tzinfo=CN)
            price = row['Price'] / 1000
            points.append({'time': int(point.timestamp()) + 8*3600, 'source_index': len(points),
                           'date_cn': point.strftime('%Y-%m-%d %H:%M'), 'value': price, 'volume': row['Number']*100})
    raw_hash = digest(json.dumps(source_hashes, sort_keys=True).encode())
    panel = {'period': period, 'label': label, 'kind': 'line', 'points': points, 'dates': dates,
             'coverage': {'count': len(points), 'first': points[0]['date_cn'], 'last': points[-1]['date_cn'],
                          'source': 'TDX历史分时价格快照', 'input_sha256': raw_hash, 'days': len(dates)},
             'note': title_note, 'algorithm_note': '只有价格快照和分时量，不能恢复分钟OHLC，未据此独立构造缠论K线结构。',
             'definition_mode': 'observed_timeshare_only', 'execution_allowed': False, 'source_hashes': source_hashes}
    save_panel(panel)
    return panel


def source_registry():
    kb = ROOT.parent / '缠论知识库'
    manifest = json.loads((kb / 'sources/chanlunzhan/manifest.json').read_text(encoding='utf-8'))
    modules = {
        'kline-basics': ('data_contract', ['chanmodel/model.py','workbench/history.py']),
        'worldview': ('research_constraints', ['chanmodel/v2/recursive.py','chanmodel/study_profile.py']),
        'fenxing-bi': ('implemented_under_profile', ['chanmodel/structure.py','chanmodel/study_profile.py']),
        'xianduan': ('implemented_with_boundary_conventions', ['chanmodel/segments.py']),
        'zhongshu': ('recursive_predicates_with_base_boundary', ['chanmodel/v2/recursive.py']),
        'beichi': ('structure_gated_indicator_proxy', ['chanmodel/v2/divergence.py','chanmodel/signals.py']),
        'maimaidian': ('candidate_only_lower_confirmation_missing', ['chanmodel/v2/divergence.py','chanmodel/study_profile.py']),
        'recursion': ('declared_decomposition_not_universal_equivalence', ['chanmodel/v2/recursive.py','chanmodel/v2/engine.py']),
    }
    cards = []
    for rec in manifest:
        if rec['category'] != 'lesson':
            continue
        stage = rec['url'].split('/')[4]
        state, files = modules[stage]
        cards.append({'title': rec['title'], 'source_url': rec['url'], 'source_sha256': rec['sha256'],
                      'original_refs': rec['original_refs'], 'coverage_status': state,
                      'modules': [{'file': f, 'sha256': digest((ROOT/f).read_bytes())} for f in files]})
    registry = {'profile': PROFILE, 'lessons': cards, 'lesson_count': len(cards),
                'glossary_count': sum(r['category']=='glossary' for r in manifest),
                'static_source_count': len(manifest), 'all_source_definitions_proven': False,
                'review_document': '缠论知识库/notes/15-缠论站口径差异与原文核对.md',
                'differences': ['strict merged-bar spacing rather than legacy loose original-bar spacing',
                               'conservative second-type: exclude force-only weak_retest_101',
                               'MACD displayed as 2*(DIF-DEA)',
                               'keep inherited initialization rather than silently copying site default-up',
                               'do not copy first-trend-entering-versus-last-leaving simplification',
                               'theoretical level remains separate from chart sampling timeframe']}
    atomic_json(OUT/'knowledge-rule-registry.json', registry)
    return registry


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    OUT.mkdir(parents=True, exist_ok=True)
    for sub in ['panels','analysis','csv','assets','png']:
        (OUT/sub).mkdir(exist_ok=True)
    cutoff = now_iso()
    catalog, summary, allbars = [], [], {}
    for period, raw_period in NATIVE.items():
        raw = gzip.decompress((SOURCE/'raw'/f'{raw_period}.json.gz').read_bytes())
        receipt = json.loads((SOURCE/'receipts'/f'{raw_period}.json').read_text(encoding='utf-8'))
        if digest(raw) != receipt['response_sha256']:
            raise ValueError('Native source response changed')
        bars = normalize(json.loads(raw)['data'], period, cutoff)
        allbars[period] = (bars, digest(raw), 'TDX原生周期')
    five = five_day(allbars['day'][0])
    allbars['5d'] = (five, digest(json.dumps([[b.closed_at,b.open,b.high,b.low,b.close,b.volume] for b in five]).encode()),
                     '从2021-02-26起每5个已观测交易日聚合；不等于周线')
    auction_json = json.loads((OUT/'auction-bars.json').read_text(encoding='utf-8'))
    auctions = tuple(Candle(i,b['open'],b['high'],b['low'],b['close'],b['closed_at'],b['volume']) for i,b in enumerate(auction_json))
    allbars['auction'] = (auctions, digest((OUT/'auction-bars.json').read_bytes()), 'TDX每日09:25实际撮合成交；65日未观察到09:25记录')
    order = ['auction','day','5d','1m','5m','15m','30m','60m','week','month','quarter','year']
    for period in order:
        bars, sha, origin = allbars[period]
        report = analyze_period('sz300949', period, bars, cutoff, sha)
        raw = json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        atomic_bytes(OUT/'analysis'/f'{period}.json.gz', gzip.compress(raw, compresslevel=3, mtime=0))
        panel = build_panel(period, bars, report, sha, origin)
        panel.update(kind='candles', label='历史竞价成交K线' if period=='auction' else LABELS[period],
                     profile=PROFILE, definition_mode=report['definition_mode'],
                     config=report['config'], approximation_loss=report['approximation_loss'],
                     as_of=cutoff, execution_allowed=False,
                     macd=[dict(time=panel['bars'][i]['time'],**h) for i,h in enumerate(report['macd'])],
                     fractals=report['base']['fractals'],
                     audit=report['certificate_audit'], strict_original_equivalence_proven=False)
        if period=='auction':
            panel['note']='每根为一日09:25撮合结果，O=H=L=C；不包含09:15—09:25虚拟撮合过程'
            panel['foot']='1316个撮合记录日 / 1381个请求日；65日缺少09:25观察。结构仅为成交价序列代理。'
        panel['default_visible']=min(len(bars), 320 if period in {'day','1m','5m','15m','30m','60m','auction'} else 300)
        save_panel(panel)
        item={'period':period, 'label':panel['label'], 'kind':'candles', 'bars':len(bars),
              'closed_bars':sum(b.closed for b in bars), 'first':bars[0].closed_at, 'last':bars[-1].closed_at,
              'strokes':len(report['base']['strokes']), 'segments':len(report['base']['segments']),
              'rank1_centers':len(panel['centers']), 'signals':len(report['signals']),
              'active_candidates':sum(s['state']!='invalidated' for s in report['signals']),
              'certificate_audit':report['certificate_audit'], 'input_sha256':sha,
              'forming_excluded':report['input_audit']['forming_excluded']}
        old_path=SOURCE/'analysis'/f'{period}.json'
        if old_path.exists():
            old=json.loads(old_path.read_text(encoding='utf-8'))
            item['legacy_loose_comparison']={'strokes':len(old['base']['strokes']), 'segments':len(old['base']['segments']),
                                             'signals':len(old['signals'])}
        with (OUT/'csv'/f'{period}.csv').open('w',encoding='utf-8',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['closed_at','open','high','low','close','volume','is_closed'])
            for b in bars:writer.writerow([b.closed_at,b.open,b.high,b.low,b.close,b.volume,b.closed])
        summary.append(item);catalog.append({'period':period,'label':panel['label'],'kind':'candles'})
        print(json.dumps({'analyzed':period,'bars':len(bars),'strokes':item['strokes'],'segments':item['segments'],'certificates':item['certificate_audit']['state']},ensure_ascii=False),flush=True)
    acquisition=json.loads((SOURCE/'acquisition.json').read_text(encoding='utf-8'))
    dates=[r['date'] for r in acquisition['time_share_history']['dates'] if r['status']=='received']
    for date_group,period,label,note in [([dates[-1]],'timeshare','历史分时','2026-11-06 · 每分钟最后价格快照'),
                                       (dates[-5:],'five_days','五日分时','最近5个交易日的价格快照，独立于5日K线'),
                                       ([dates[0]],'timeshare_first','上市首日历史分时','2021-02-26 · 早期历史样例；盘中零成交快照原样保留')]:
        p=line_panel(date_group,period,label,note)
        catalog.append({'period':period,'label':label,'kind':'line'})
        summary.append({'period':period,'label':label,**p['coverage']})
    registry=source_registry()
    source_assets=ROOT/'runs/aoya-v2-chart-20261107/assets'
    for name in ['lightweight-charts.standalone.production.js','LICENSE','NOTICE','library-source.json']:
        shutil.copy2(source_assets/name,OUT/'assets'/name)
    latest=allbars['day'][0][-1];previous=allbars['day'][0][-2]
    run={'symbol':'sz300949','name':'奥雅股份','cutoff':cutoff,'last_data_at':latest.closed_at,
         'price':latest.close,'change_pct':100*(latest.close/previous.close-1),
         'source':'TDX','adjustment':'unadjusted','profile':PROFILE,'periods':summary,'catalog':catalog,
         'execution_allowed':False,'strict_original_equivalence_proven':False,
         'auction_coverage':{'requested_days':1381,'observed_days':len(auctions),'missing_0925_days':1381-len(auctions),
                             'indicative_snapshots_available':False},'source_registry':{'lessons':registry['lesson_count'],'glossary':registry['glossary_count']}}
    atomic_json(OUT/'run-summary.json',run)
    (OUT/'run-info.js').write_text('window.RUN='+json.dumps(run,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
    print(json.dumps({'ready':True,'periods':len(catalog),'last_data_at':latest.closed_at,'profile':PROFILE},ensure_ascii=False))


if __name__=='__main__':
    main()
