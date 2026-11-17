"""Measured local resource status; recursive structures currently run on CPU."""
import csv
import io
import shutil
import subprocess
import threading
import time

from chanmodel.resource_runtime import snapshot_resources,plan_workers

_LOCK=threading.Lock()
_GPU=(0.0,None)


def gpu_status():
    global _GPU
    with _LOCK:
        if _GPU[1] is not None and time.monotonic()-_GPU[0]<30:return dict(_GPU[1])
        result={'devices':[],'supported':False,'execution':'cpu',
                'reason':'recursive_state_machine_cpu','probe_state':'not_detected'}
        command=shutil.which('nvidia-smi')
        if command:
            try:
                completed=subprocess.run([command,'--query-gpu=name,memory.total,memory.used,utilization.gpu',
                    '--format=csv,noheader,nounits'],capture_output=True,text=True,encoding='utf-8',
                    errors='replace',timeout=3,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if completed.returncode==0:
                    for values in csv.reader(io.StringIO(completed.stdout)):
                        if len(values)!=4:continue
                        def number(value):
                            try:return float(value.strip())
                            except ValueError:return None
                        result['devices'].append({'name':values[0].strip(),'memory_total_mb':number(values[1]),
                            'memory_used_mb':number(values[2]),'utilization_percent':number(values[3])})
                    result['name']=' / '.join(device['name'] for device in result['devices'])
                    result['probe_state']='detected' if result['devices'] else 'not_detected'
                else:result['probe_state']='probe_failed'
            except (OSError,subprocess.TimeoutExpired):result['probe_state']='probe_failed'
        _GPU=(time.monotonic(),result)
        return dict(result)


def resource_status():
    snapshot=snapshot_resources()
    plan=plan_workers('auto',memory_per_worker_mb=384,snapshot=snapshot)
    return {**snapshot,'plan':plan,'gpu':gpu_status(),'execution_backend':'cpu_multiprocess',
            'policy':'cpu_memory_adaptive_v1','execution_allowed':False}
