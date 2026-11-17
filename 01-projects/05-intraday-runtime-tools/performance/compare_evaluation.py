from pathlib import Path
import sys,importlib.util,json,gzip,time,statistics,hashlib
sys.path.insert(0,r"C:/Users/li/Documents/ChatGPT/缠学习/缠论算法")
from chanmodel.v2.io import load_cache_series
import chanmodel.intraday_research as current
root=Path(__file__).parent
spec=importlib.util.spec_from_file_location('chanmodel._intraday_old_eval',root/'intraday_research_baseline.py');old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
a=json.loads(gzip.decompress((root/'baseline-1m.json.gz').read_bytes()));b=json.loads(gzip.decompress((root/'optimized-1m.json.gz').read_bytes()))
assert a==b
checks=[]
for period in ('1m','5m'):
 source,_=load_cache_series(root.parent/'sources-v2/market_data','sz300949',period);source=source.prefix('2026-11-06T15:00:00+08:00')
 events=a['snapshot']['events'] if period=='1m' else json.loads(gzip.decompress((root.parent/'final-study-5m/sz300949/5m/intraday-research.json.gz').read_bytes()))['events']
 expected=old.evaluate_intraday(source.bars,events,period);actual=current.evaluate_intraday(source.bars,events,period)
 assert expected==actual and actual['summary']['alerts']>0
 timings={}
 for name,function in [('baseline',old.evaluate_intraday),('optimized',current.evaluate_intraday)]:
  samples=[]
  for n in range(7):
   t=time.perf_counter();value=function(source.bars,events,period);samples.append(time.perf_counter()-t);assert value==expected
  timings[name]={'seconds':samples,'median':statistics.median(samples)}
 checks.append({'period':period,'bars':len(source.bars),'events':len(events),'alerts':actual['summary']['alerts'],'all_fields_equal':True,'timings':timings,'evaluation_sha256':hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
value={'state':'passed','full_1m_replay_equal':True,'full_1m_bars':22560,'full_1m_events':1286,'full_1m_alerts':600,'full_1m_output_sha256':'81ef1e73124069d880b95aec9019ade00b053b49355987b84973bb21bbca7c73','evaluation_checks':checks,'timing_limits':'Full replay profiling concurrent under cProfile is diagnostic, not isolated throughput. Evaluation uses seven sequential repetitions per version.','changed_code':{name:hashlib.sha256(Path(r"C:/Users/li/Documents/ChatGPT/缠学习/缠论算法",name).read_bytes()).hexdigest() for name in ['chanmodel/intraday_research.py','tools/verify_intraday_research.py']},'execution_allowed':False}
(root/'equivalence.json').write_text(json.dumps(value,indent=2),encoding='utf-8');print(json.dumps(value,indent=2))
