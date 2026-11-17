"""Inspect hardware, benchmark transfer-inclusive CUDA MACD, or compute a batch."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if (ROOT/'core/hardware_compute.py').is_file():
    from core.gpu_macd import batch_macd,CudaMacd,CudaUnavailable
    from core.hardware_compute import hardware_status,resource_plan
    def status():
        hardware=hardware_status(include_gpu=True)
        return {'hardware':hardware,'plan':resource_plan(status=hardware)}
else:
    from chanmodel.gpu_macd import batch_macd,CudaMacd,CudaUnavailable
    from workbench.resources import hardware_snapshot,plan_resources
    def status():
        hardware=hardware_snapshot(include_gpu=True)
        return {'hardware':hardware,'plan':plan_resources('native_backtest',snapshot=hardware)}


def benchmark(rows=512,bars=1024):
    if type(rows) is not int or type(bars) is not int or rows<1 or bars<1 or rows*bars>2_000_000:
        raise ValueError('benchmark must have 1..2,000,000 price observations')
    values=[[100+math.sin(i*.03+j*.02)*3+j*.01 for i in range(bars)] for j in range(rows)]
    started=time.perf_counter();cpu=batch_macd(values,backend='cpu');cpu_seconds=time.perf_counter()-started
    result={'data':'explicit synthetic prices for hardware timing, not market prices',
        'shape':[rows,bars],'cpu_seconds':cpu_seconds,'input_validation_included':True,
        'host_device_transfers_included':True,'result_finite_check_included':True,
        'execution_allowed':False}
    try:
        started=time.perf_counter();cold=batch_macd(values,backend='gpu');result['gpu_cold_seconds']=time.perf_counter()-started
        error=max((abs(a-b) for a,b in zip(cpu['values'],cold['values'])),default=0)
        warm=[]
        with CudaMacd() as context:
            for _ in range(3):
                started=time.perf_counter();gpu=batch_macd(values,backend='auto',context=context)
                warm.append(time.perf_counter()-started)
                error=max(error,max((abs(a-b) for a,b in zip(cpu['values'],gpu['values'])),default=0))
        result.update(gpu_backend=cold['backend'],device=cold['device'],gpu_warm_seconds=warm,
            gpu_warm_median_seconds=statistics.median(warm),max_absolute_error=error,
            cpu_gpu_equal=error==0,accelerated_scope='MACD indicator batch only; structure remains CPU')
        if error>1e-12:raise ValueError('CPU/GPU parity failed')
    except CudaUnavailable as exc:result.update(gpu_backend='unavailable',gpu_reason=str(exc))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--benchmark',action='store_true')
    parser.add_argument('--rows',type=int,default=512)
    parser.add_argument('--bars',type=int,default=1024)
    parser.add_argument('--input',type=Path,help='JSON object with rectangular prices and optional MACD parameters')
    parser.add_argument('--backend',choices=['auto','cpu','gpu'],default='auto')
    args=parser.parse_args()
    if args.output_dir.exists():parser.error('output directory already exists; choose a fresh directory')
    if args.benchmark and args.input:parser.error('choose benchmark or input, not both')
    args.output_dir.mkdir(parents=True,exist_ok=False)
    report={'status':'passed','resources':status(),'execution_allowed':False,
        'recursive_algorithm_backend':'cpu','uploaded':False}
    if args.benchmark:report['benchmark']=benchmark(args.rows,args.bars)
    if args.input:
        raw=args.input.read_bytes()
        if len(raw)>16*1024*1024:raise ValueError('input JSON exceeds 16MiB')
        value=json.loads(raw);result=batch_macd(value['prices'],backend=args.backend,
            **{k:value[k] for k in ['fast','slow','signal','multiplier'] if k in value})
        report['input_sha256']=hashlib.sha256(raw).hexdigest()
        report['calculation']={k:v for k,v in result.items() if k!='values'}
        target=args.output_dir/'macd.json'
        target.write_text(json.dumps({**result,'values':list(result['values'])},allow_nan=False,separators=(',',':')),encoding='utf-8')
        report['calculation']['output_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    (args.output_dir/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','benchmark','calculation'] if k in report},ensure_ascii=False))


if __name__=='__main__':main()
