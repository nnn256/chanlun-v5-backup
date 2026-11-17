import sys,importlib.util,time,json,gzip,cProfile,pstats,io,hashlib
from pathlib import Path
sys.path.insert(0,r"C:/Users/li/Documents/ChatGPT/缠学习/缠论算法")
from chanmodel.v2.io import load_cache_series
root=Path(__file__).parent
mode=sys.argv[1];period=sys.argv[2] if len(sys.argv)>2 else '1m'
if mode=='baseline':
 spec=importlib.util.spec_from_file_location('chanmodel._intraday_baseline',root/'intraday_research_baseline.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
else:
 import chanmodel.intraday_research as module
source,_=load_cache_series(root.parent/'sources-v2/market_data','sz300949',period)
source=source.prefix('2026-11-06T15:00:00+08:00')
profile=cProfile.Profile();profile.enable();started=time.perf_counter()
session=module.IntradayResearchSession('sz300949',period)
for i,bar in enumerate(source.bars):
 session.append(bar)
 if (i+1)%5000==0:print(mode,period,i+1,'bars',flush=True)
snapshot=session.snapshot();replay_seconds=time.perf_counter()-started
started=time.perf_counter();evaluation=module.evaluate_intraday(source.bars,snapshot['events'],period);evaluation_seconds=time.perf_counter()-started
profile.disable();buffer=io.StringIO();pstats.Stats(profile,stream=buffer).sort_stats('cumulative').print_stats(30)
(root/f'{mode}-{period}.profile.txt').write_text(buffer.getvalue(),encoding='utf-8')
body={'snapshot':snapshot,'evaluation':evaluation};encoded=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode();(root/f'{mode}-{period}.json.gz').write_bytes(gzip.compress(encoded,mtime=0))
receipt={'mode':mode,'period':period,'bars':len(source.bars),'events':len(snapshot['events']),'alerts':evaluation['summary']['alerts'],'replay_seconds':replay_seconds,'evaluation_seconds':evaluation_seconds,'body_sha256':hashlib.sha256(encoded).hexdigest()}
(root/f'{mode}-{period}.receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps(receipt),flush=True)
