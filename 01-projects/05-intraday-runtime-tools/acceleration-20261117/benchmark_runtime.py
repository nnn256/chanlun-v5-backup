"""Sequential real-OHLC runtime comparison, separate from production results."""
from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def measure(root, output, mode, bars):
    sys.path.insert(0, str(root / 'frozen-code'))
    from chanmodel.v2.io import load_cache_series
    from chanmodel.intraday_research import IntradayResearchSession, evaluate_intraday
    series, _ = load_cache_series(root / 'acquisition/market_data', 'sz300949', '1m')
    observed = series.bars[:bars]
    gc.collect()
    counts_before = [x.copy() for x in gc.get_stats()]
    if mode == 'gc_disabled':
        gc.disable()
    wall = time.perf_counter()
    cpu = time.process_time()
    session = IntradayResearchSession('sz300949', '1m')
    for bar in observed:
        session.append(bar)
    snapshot = session.snapshot()
    evaluation = evaluate_intraday(observed, snapshot['events'], '1m')
    result = {'snapshot': snapshot, 'evaluation': evaluation}
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    receipt = {'mode': mode, 'bars': len(observed), 'events': len(snapshot['events']),
               'alerts': sum(e['event'] == 'research_alert' for e in snapshot['events']),
               'wall_seconds': time.perf_counter() - wall, 'cpu_seconds': time.process_time() - cpu,
               'canonical_sha256': hashlib.sha256(encoded).hexdigest(),
               'gc_collections': [a['collections'] - b['collections'] for a, b in zip(gc.get_stats(), counts_before)],
               'execution_allowed': False, 'production_artifacts_modified': False}
    if sys.platform == 'win32':
        class Counters(ctypes.Structure):
            _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        handle = kernel.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            receipt['peak_working_set_bytes'] = counters.PeakWorkingSetSize
            receipt['private_bytes'] = counters.PagefileUsage
            receipt['peak_private_bytes'] = counters.PeakPagefileUsage
        else:
            raise ctypes.WinError(ctypes.get_last_error())
    (output / (mode + '.json')).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--bars', type=int, default=6000)
    parser.add_argument('--mode', choices=['gc_default', 'gc_disabled'])
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / f'acceleration-20261117/runtime-benchmark-{args.bars}'
    output.mkdir(parents=True, exist_ok=True)
    if args.mode:
        measure(root, output, args.mode, args.bars)
        return
    for mode in ['gc_default', 'gc_disabled']:
        subprocess.run([sys.executable, '-X', 'faulthandler', str(Path(__file__).resolve()),
                        '--root', str(root), '--bars', str(args.bars), '--mode', mode], check=True)
    results = {mode: json.loads((output / (mode + '.json')).read_text(encoding='utf-8'))
               for mode in ['gc_default', 'gc_disabled']}
    equal = results['gc_default']['canonical_sha256'] == results['gc_disabled']['canonical_sha256']
    receipt = {'equal': equal, 'bars': args.bars, 'results': results,
               'wall_speedup': results['gc_default']['wall_seconds'] / results['gc_disabled']['wall_seconds'],
               'scope': 'single security prefix benchmark; not whole-market throughput'}
    (output / 'comparison.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    if not equal:
        raise SystemExit('Runtime outputs differ')


if __name__ == '__main__':
    main()
