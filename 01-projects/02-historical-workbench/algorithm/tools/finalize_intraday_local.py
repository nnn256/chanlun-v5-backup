"""Write an auditable Chinese summary for the completed local F-drive study."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime,timezone,timedelta
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
CN=timezone(timedelta(hours=8))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def local_json(url):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url,timeout=8) as response:return json.load(response)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();base=a.output.resolve()
    verifications={}
    for name in ['final-study-1m/verification-first.json','final-study-1m/verification-second.json',
                 'final-study-5m/verification-first.json']:
        value=json.loads((base/name).read_text(encoding='utf-8'))
        if value['state']!='passed':raise ValueError('cannot finalize failed replay: '+name)
        verifications[name]={'state':value['state'],'datasets':len(value['checks']),'sha256':sha(base/name)}
    manifest=json.loads((base/'sources-v2/manifest.json').read_text(encoding='utf-8'))
    for path,expected in manifest['frozen_files_sha256'].items():
        if sha(base/'sources-v2'/path)!=expected:raise ValueError('frozen source changed: '+path)
    suite=(base/'final-full-suite.log').read_text(encoding='utf-8')
    count=re.search(r'Ran (\d+) tests',suite)
    if count is None or not re.search(r'^OK\s*$',suite,re.M):raise ValueError('full suite did not pass')
    health=local_json('http://127.0.0.1:8796/api/health')
    monitor=local_json('http://127.0.0.1:8796/api/monitor')
    if not monitor['config']['enabled'] or monitor['config']['structure_mode']!='intraday':
        raise ValueError('requested local intraday monitor was not enabled')
    if monitor['busy']:raise ValueError('baseline scan is still running')
    if not monitor['runs'] or monitor['runs'][0]['state']!='complete' or monitor['runs'][0]['payload'].get('failed'):
        raise ValueError('local monitor baseline did not complete')
    (base/'monitor-status-final.json').write_text(json.dumps({'captured_at':datetime.now(CN).isoformat(),
        'health':health,'monitor':monitor,'url':'http://127.0.0.1:8796/?symbol=sz300949&period=1m',
        'execution_allowed':False},ensure_ascii=False,indent=2),encoding='utf-8')
    records=[]
    for name in ['final-study-5m','final-study-1m']:
        study=json.loads((base/name/'study-summary.json').read_text(encoding='utf-8'))
        for r in study['records']:
            if r['state']!='complete':raise ValueError('incomplete security result')
            payload=json.loads(gzip.decompress(Path(r['artifact']).read_bytes()))
            if sha(Path(r['artifact']))!=r['artifact_sha256']:raise ValueError('study artifact changed')
            records.append({key:r[key] for key in ['symbol','period','input_bars','alerts','buy','sell','artifact','artifact_sha256']}
                           | {'next_open_hypotheses':r['by_state'].get('next_open_hypothesis',0),
                              'source_as_of':r['as_of'],'evaluation_sessions':len(r['evaluation_sessions']),
                              'invalidation_events':sum(e['event']=='invalidated' for e in payload['events']),
                              'withdrawal_events':sum(e['event']=='withdrawn' for e in payload['events'])})
    code=base/'code-snapshot';files={}
    for directory in ['chanmodel','workbench','tests','tools','third_party/chanpy']:
        for path in sorted((ROOT/directory).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or (path.suffix not in {'.py','.js','.cjs','.css','.html','.md','.json'} and path.name not in {'LICENSE','NOTICE'}):
                continue
            relative=path.relative_to(ROOT);target=code/relative;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target);files[relative.as_posix()]=sha(target)
    result={'schema':1,'completed_at':datetime.now(CN).isoformat(),'state':'passed',
        'source_bars':sum(r['input_bars'] for r in records),'research_alerts':sum(r['alerts'] for r in records),
        'next_open_hypotheses':sum(r['next_open_hypotheses'] for r in records),
        'full_suite_tests':int(count[1]),'verifications':verifications,'records':records,
        'source_raw_bytes_verified_datasets':sum(s.get('original_response_bytes_checked',s.get('provider_receipt_checked',False)) for s in manifest['sources']),
        'source_receipt_datasets':len(manifest['sources']),'code_files_sha256':files,
        'report_sha256':sha(base/'display/report-view.html'),'monitor_url':'http://127.0.0.1:8796/?symbol=sz300949&period=1m',
        'report_url':'http://127.0.0.1:8797/report-view.html','uploaded':False,'execution_allowed':False,
        'limitations':['descriptive event study; overlapping alerts are not independent portfolio wins',
            'session extremes are ex-post labels, never live inputs',
            'same-day A-share sells require preexisting T+1-eligible holdings',
            'only desktop and mobile browser viewport emulation, no physical phone or third-party terminal integration',
            'Sunday offline/live-source baseline passed; trading-session notification delivery remains to be observed',
            'browser desktop notifications require user permission and a running page']}
    (base/'FINAL_RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=['# 缠论分时本地测试与监控结果','',
          f"完成时间：{result['completed_at']}。本次未上传，未接入下单。",'',
          '## 打开入口','',
          '- [分时研究图表与回放](http://127.0.0.1:8797/report-view.html)',
          '- [本地实时看盘与监控](http://127.0.0.1:8796/?symbol=sz300949&period=1m)',
          '- 离线直接打开 `display/report-view.html`；电脑和390×844手机尺寸均已复测。',
          '- `display/QA.md` 保存浏览器验收；截图包括成功买卖点、无信号状态和失败反例。','',
          '## 计算与复核','',
          f"- 输入 {result['source_bars']:,} 根真实原生K线，7个证券/周期数据集。",
          f"- {result['research_alerts']}条为研究提醒；{result['next_open_hypotheses']}条有同日下一根开盘假设，其余缺少可评估下一根。",
          '- 完整此前历史预热，最后60个交易日做评估；参数在计算前固定为60交易分钟/2%。',
          '- 六股5分钟全量独立复算一次；一股1分钟独立复算两次。源码/数据/事件/原始开盘价和完整交易日极值均可核对。',
          f"- Python完整回归 {result['full_suite_tests']} 项通过；前端Node测试见 `final-node-tests.log`。",'',
          '| 股票 | 周期 | K线根数 | 提醒 | 下一开盘假设 | 买侧距日低中位 | 卖侧距日高中位 |',
          '|---|---|---:|---:|---:|---:|---:|']
    for r in records:
        buy=r['buy']['median_gap_to_session_extreme_bps'];sell=r['sell']['median_gap_to_session_extreme_bps']
        rows.append(f"| {r['symbol']} | {r['period']} | {r['input_bars']} | {r['alerts']} | {r['next_open_hypotheses']} | {buy/100:.3f}% | {sell/100:.3f}% |")
    rows += ['', '## 准确性结论','',
             '几何与因果错误已修复，但固定过滤没有证明稳定买到最低、卖到最高。请读 `固定过滤对照结果.md`；保留改进和变差结果，不把未来方向标签当成组合收益。',
             '买入模拟使用下一根原始开盘上浮5bps，卖出假定有可卖持仓并使用下一开盘下浮5bps；日高/日低仅用于事后对比。没有逐笔成交队列、完整费用和大样本样本外预测证明。',
             '', '## 监控状态','',
             '- 已在F盘独立实例开启 sz300949 原生1分钟研究监控，报价与结构间隔60秒。',
             '- 首次预热、数据修订重建及周末静默；旧日研究点过期，历史账本保留。',
             '- 当前周日待命，数据实际截止2026-11-13，0误发提醒；尚未实测开市后真实提醒的端到端投递。',
             '- 网页“扫描与提醒”里点击“启用本机桌面提醒”并保持网页/服务运行；未授权时查看应用内台账。',
             '- `monitor-status-final.json` 为完成时实际API状态，`monitor-runtime/runtime/workbench/` 保存SQLite和提醒记录。',
             '', '## 样本与边界','',
             '- 历史冻结输入截止11月5日或6日，各股票日期在JSON内分别保留；实时监控源已更新至11月13日。',
             '- 手机为浏览器视口仿真；本次未连接真实手机或通达信/同花顺等第三方客户端。',
             '- 原始响应未随部分本地cache打包：此时只验证CSV与来源metadata双哈希，不宣称逐字核验不存在的原始响应。',
             '- `sources/` 和首轮 `study-*`、`verification-*-first.*` 保留了开发中规则变化导致的初次不一致；正式验收只用 `final-study-*`。',
             '- 自动监控仅在进程运行期间有效，不是系统开机计划任务；两个服务都只监听127.0.0.1。',
             '', '复现命令、规则和逐条事件分别在 `code-snapshot/tools/`、`分时算法规则与结果口径.md` 与各周期 `alerts.csv`。']
    (base/'测试总结.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['state','source_bars','research_alerts','next_open_hypotheses','full_suite_tests','report_url','monitor_url','uploaded']}))


if __name__=='__main__':main()
