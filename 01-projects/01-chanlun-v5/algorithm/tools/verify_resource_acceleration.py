"""Verify that multiprocessing admission preserves an actual V5 report."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chanmodel.resource_runtime import adaptive_results,snapshot_resources
from chanmodel.v2.io import load_cache_series
from workbench.v5_engine import analyze_inputs


def signature(series):
    report=analyze_inputs({'day':series},series.bars[-1].closed_at)
    return hashlib.sha256(json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def main():
    cache=ROOT.parent/'data/market_data'
    series,_=load_cache_series(cache,'sh600000','day')
    series=replace(series,bars=series.bars[:800],input_sha256='resource-verification-first-800-source-bars')
    started=time.perf_counter();baseline=signature(series);baseline_seconds=time.perf_counter()-started
    status=[]
    # This small, deterministic equivalence test reserves only one worker.
    # Its planner fixture is not represented as live available-memory evidence.
    fixture={'cpu':{'logical_processors':2},'memory':{'total_bytes':4*1024**3,'available_bytes':3*1024**3}}
    started=time.perf_counter()
    outputs=[future.result() for _,future in adaptive_results(signature,[series],workers=1,
        snapshot_fn=lambda:fixture,on_resource=status.append)]
    assert outputs==[baseline]
    return {'status':'pass','source':'local saved TDX sh600000 first 800 bars','bars':800,
            'v5_profile':'course_feature_sequence_recursive_v2','max_rank':8,
            'direct_report_sha256':baseline,'multiprocess_report_sha256':outputs[0],
            'direct_seconds':round(baseline_seconds,4),'multiprocess_seconds':round(time.perf_counter()-started,4),
            'timing_scope':'equivalence smoke, not speedup benchmark; includes one-process startup',
            'planner_fixture_used':True,'actual_resources':snapshot_resources(),
            'scheduler_finished_state':status[-1]['state'],'execution_allowed':False}


if __name__=='__main__':print(json.dumps(main(),ensure_ascii=False,indent=2))
