"""Build and verify a portable V5 source, all-market results, and data package."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import zipfile


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RELEASE = 'ChanlunV5-20261115'
MAX_RANK = 8
UNIVERSE_RUN = 'full-market-20261114-tdx-partial'
RECURSIVE_RUN = 'v5-recursive-l8-20261115'
UNIVERSE_PROFILE = 'course_feature_sequence_recursive_v2'
EXCLUDES = {'.git', '__pycache__', '.venv', 'node_modules', 'before', 'logs'}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_tree(source: Path, target: Path) -> int:
    count = 0
    for path in source.rglob('*'):
        relative = path.relative_to(source)
        if not path.is_file() or any(part in EXCLUDES for part in relative.parts):
            continue
        copy_file(path, target / relative)
        count += 1
    return count


def inventory(stage: Path) -> list[dict]:
    rows = []
    for path in sorted(stage.rglob('*')):
        if not path.is_file() or path.name == 'MANIFEST.json':
            continue
        if any(part in {'.git','__pycache__','.venv','node_modules'} for part in path.relative_to(stage).parts) or path.name.endswith(('-wal','-shm')):
            continue
        if any(part in {'before','logs'} for part in path.relative_to(stage).parts):
            raise ValueError(f'forbidden path in release: {path.relative_to(stage)}')
        rows.append({
            'path': path.relative_to(stage).as_posix(),
            'bytes': path.stat().st_size,
            'sha256': digest(path),
            'mutable':path.name=='workbench.sqlite3',
        })
    return rows


def verify_manifest(stage: Path, rows: list[dict]) -> None:
    failures = []
    for row in rows:
        path = (stage / row['path']).resolve()
        if not path.is_relative_to(stage.resolve()) or not path.is_file():
            failures.append(f"missing: {row['path']}")
        elif path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
            failures.append(f"hash mismatch: {row['path']}")
    if failures:
        raise RuntimeError('; '.join(failures[:10]))


def prepare_project(project: Path, python: str, cache_dir: Path, universe_file: Path,
                    recursive_run: Path, workers: int) -> dict:
    algorithm = project / 'algorithm'
    for directory in ('chanmodel', 'workbench', 'tests', 'third_party', 'examples', 'examples-final', 'tools', 'public_web', 'installer'):
        copy_tree(ROOT / directory, algorithm / directory)
    for source in ROOT.glob('*.py'):
        copy_file(source, algorithm/source.name)
    for relative in (
        'README-V5.md', 'README.md', 'V5-PROFILE.json', 'market_scan.py',
        'run_v5_recursive_market.py', 'import_v5_results_to_workbench.py',
        'run_v5_market.py', 'launch_v5.py',
    ):
        copy_file(ROOT / relative, algorithm / relative)
    copy_file(ROOT / 'tools/capture_full_stock.py', algorithm / 'tools/capture_full_stock.py')
    copy_file(ROOT / 'public_web/web/assets/lightweight-charts.js',
              algorithm / 'public_web/web/assets/lightweight-charts.js')
    for name in ('LICENSE', 'NOTICE', 'library-source.json'):
        copy_file(ROOT / 'public_web/web/assets' / name, algorithm / 'public_web/web/assets' / name)
    copy_file(ROOT / 'runtime/tdx-api-revised.exe', algorithm / 'runtime/tdx-api-revised.exe')
    copy_file(universe_file, project / 'runs' / UNIVERSE_RUN / 'universe.json')
    copy_tree(recursive_run, project / 'runs' / RECURSIVE_RUN)
    copy_tree(cache_dir, project / 'data/market_data')
    status=json.loads((REPO/'V5-RUN-STATUS.json').read_text(encoding='utf-8'))
    status['recursive']=json.loads((recursive_run/'summary.json').read_text(encoding='utf-8'))
    status['recursive']['run_dir']=f'runs/{RECURSIVE_RUN}'
    status['acquisition']['run_dir']=f'runs/{UNIVERSE_RUN}'
    status['data_root']='data/market_data'
    status['old_v5_workbench']=None
    status['legacy_workbench']=None
    status['workbench']['url']='http://127.0.0.1:8895'
    status['workbench']['database']='workbench-data-8895/workbench.sqlite3'
    (project/'V5-RUN-STATUS.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for meta in (project/'data/market_data').glob('*/day/metadata/*.json'):
        value=json.loads(meta.read_text(encoding='utf-8-sig'))
        folder=meta.parent.parent
        value['csv_path']=os.path.relpath(folder/'ohlcv'/f'{meta.stem}.csv',algorithm)
        value['raw_path']=os.path.relpath(folder/'raw'/f'{meta.stem}.json.gz',algorithm)
        meta.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    (project/'START.cmd').write_text(
        '@echo off\r\ncd /d "%~dp0"\r\nwhere py >nul 2>&1\r\n'
        'if not errorlevel 1 (py -3 algorithm/launch_v5.py) else (python algorithm/launch_v5.py)\r\n'
        'if errorlevel 1 pause\r\n',encoding='ascii')
    copy_file(ROOT/'tools/verify_v5_package.py',project/'verify_package.py')
    (project/'README-使用说明.md').write_text(
        '# 缠论V5 修复包\n\n完整解压后双击 START.cmd。需要本机已安装 Python 3.11 或更新版本。'
        '也可以在解压目录执行 `python algorithm/launch_v5.py`。默认端口 8895；端口被其他工作台占用时，'
        '用 `py -3 algorithm/launch_v5.py --port 8896` 启动解压后的独立副本。\n\n'
        '如需从当前TDX行情重新采集并执行L8递归扫描，先确保TDX服务可访问，再运行 '
        '`py -3 algorithm/run_v5_market.py --workers 8`。此命令不会重写包内原有L8报告。\n\n'
        '包内包含算法源码、测试、L8 全市场递归报告、5,224只股票结果和对应日线行情。'
        '行情截至 2026-11-13；当前 provider 股票池 5,225个代码，sz002731为空行情，北交所缺失。'
        '递归上限 L8，实际层数由数据决定。缺少分钟历史的标的不会补造多周期确认。\n\n'
        '全市场回测页使用独立标注的 V4 固定引擎，不代表 V5 回测。V5日线因果观察为最近32个闭合交易日，'
        '在任务结果中独立说明范围。所有结果 execution_allowed=false。\n\n'
        '完整性核验：首次启动前运行 `py -3 verify_package.py --all`；运行后使用 '
        '`py -3 verify_package.py` 跳过会正常变化的数据库文件。\n\n'
        '运行在线刷新需要 TDX 行情服务和网络；查看包内已保存结果不需要联网。'
        '本包没有更改火绒设置；之前报毒的 before 备份目录不在交付中，未声称通过火绒复检。\n',encoding='utf-8')

    state = project / 'workbench-data-8895'
    env = {
        **os.environ,
        'PYTHONIOENCODING': 'utf-8',
        'CHANLUN_WORKBENCH_ROOT': '.',
        'CHANLUN_WORKBENCH_DATA_DIR': '../workbench-data-8895',
        'CHANLUN_V5_PROFILE': UNIVERSE_PROFILE,
        'CHANLUN_V5_UNIVERSE': f'../runs/{UNIVERSE_RUN}/universe.json',
    }
    init = subprocess.run([
        python, '-c',
        'import json; from pathlib import Path; from workbench.store import connect,initialize; '
        'u=json.loads(Path("../runs/' + UNIVERSE_RUN + '/universe.json").read_text(encoding="utf-8"))["records"]; '
        'initialize(); '
        'db=connect(); c=db.__enter__(); '
        'c.executemany("INSERT OR IGNORE INTO universe(symbol,code,name,exchange,active) VALUES(?,?,?,?,1)", '
        '[(r["symbol"],r["code"],r["name"],r["exchange"]) for r in u]); db.__exit__(None,None,None)',
    ], cwd=algorithm, env=env, capture_output=True, text=True, encoding='utf-8')
    if init.returncode:
        raise RuntimeError(f'V5 release universe setup failed: {init.stderr[-2000:]}')
    imported = subprocess.run([
        python, 'import_v5_results_to_workbench.py',
        '--recursive-run', f'../runs/{RECURSIVE_RUN}',
        '--cache-dir', '../data/market_data', '--workers', str(workers),
    ], cwd=algorithm, env=env, capture_output=True, text=True, encoding='utf-8')
    if imported.returncode:
        raise RuntimeError(f'V5 result import failed: {imported.stdout[-1200:]} {imported.stderr[-2000:]}')
    return {'import_stdout': imported.stdout[-2000:], 'database': str(state / 'workbench.sqlite3')}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def verify_extracted(root: Path, python: str, receipt_dir: Path) -> dict:
    receipt_dir.mkdir(parents=True,exist_ok=True)
    env = {
        **os.environ,
        'PYTHONIOENCODING': 'utf-8',
        'CHANLUN_WORKBENCH_ROOT': '.',
        'CHANLUN_WORKBENCH_DATA_DIR': '../workbench-data-8895',
        'CHANLUN_V5_PROFILE': UNIVERSE_PROFILE,
        'CHANLUN_V5_UNIVERSE': f'../runs/{UNIVERSE_RUN}/universe.json',
    }
    algorithm = root / 'algorithm'
    tests = subprocess.run(
        [python, '-m', 'unittest', 'discover', '-s', 'tests'],
        cwd=algorithm, env=env, capture_output=True, text=True, encoding='utf-8',
    )
    (receipt_dir / 'extracted-tests.stdout.log').write_text(tests.stdout, encoding='utf-8')
    (receipt_dir / 'extracted-tests.stderr.log').write_text(tests.stderr, encoding='utf-8')
    if tests.returncode:
        raise RuntimeError(f'extracted release tests failed: {tests.stderr[-3000:]}')

    port = free_port()
    log = (receipt_dir / 'workbench-smoke.log').open('wb')
    process = subprocess.Popen(
        [python, '-m', 'workbench.server', '--port', str(port)], cwd=algorithm,
        env=env, stdout=log, stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    try:
        import urllib.request
        base = f'http://127.0.0.1:{port}'
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError('extracted workbench exited during startup')
            try:
                with urllib.request.urlopen(base + '/api/health', timeout=2) as response:
                    health = json.load(response)
                break
            except OSError:
                time.sleep(.5)
        else:
            raise RuntimeError('extracted workbench did not become ready')
        with urllib.request.urlopen(base + '/api/overview', timeout=15) as response:
            overview = json.load(response)
        with urllib.request.urlopen(base + '/api/stock/sh600000', timeout=30) as response:
            stock = json.load(response)
        with urllib.request.urlopen(base + '/assets/lightweight-charts.standalone.production.js', timeout=15) as response:
            asset_bytes = len(response.read())
        with urllib.request.urlopen(base+'/api/kline-audit/sh600000?audit_period=day',timeout=30) as response:
            audit=json.load(response)
        assert health['release'] == 'V5'
        assert health['workbench_profile'] == UNIVERSE_PROFILE
        assert overview['stats']['computed'] == 5224
        assert stock['summary']['workbench_profile'] == UNIVERSE_PROFILE
        assert stock['summary']['max_rank'] == MAX_RANK
        assert stock['chart']['panels'][0]['bars']
        assert asset_bytes > 100_000
        assert audit['source_state']=='matched',audit
        assert audit['provider_response_state']=='hash_and_ohlcv_matched',audit
        return {
            'python_tests': tests.stderr.splitlines()[-2:],
            'workbench': 'pass', 'health_profile': health['workbench_profile'],
            'computed': overview['stats']['computed'], 'symbol': 'sh600000',
            'max_rank': stock['summary']['max_rank'], 'daily_bars': len(stock['chart']['panels'][0]['bars']),
            'chart_asset_bytes': asset_bytes,
            'original_kline_audit':audit['source_state'],
            'provider_response_audit':audit['provider_response_state'],
        }
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        log.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPO / 'releases' / RELEASE)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--import-workers', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.import_workers <= 8:
        parser.error('--import-workers must be 1..8')
    output = args.output.resolve()
    stage = output / RELEASE
    if stage.exists():
        raise SystemExit(f'release staging already exists: {stage}; choose a fresh --output directory')
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f'release output directory is not empty: {output}')
    output.mkdir(parents=True, exist_ok=True)

    universe = REPO / 'runs' / UNIVERSE_RUN / 'universe.json'
    recursive = REPO / 'runs' / RECURSIVE_RUN
    cache = REPO / 'data' / 'market_data'
    summary = json.loads((recursive / 'summary.json').read_text(encoding='utf-8'))
    if summary.get('profile') != UNIVERSE_PROFILE or summary.get('max_rank') != MAX_RANK:
        raise SystemExit('L8 run profile does not match this release')
    if summary.get('success') != 5224 or summary.get('failed') != 1 or summary.get('pending') != 0:
        raise SystemExit('L8 run is incomplete or the market-data coverage changed')
    if not universe.is_file() or not cache.is_dir():
        raise SystemExit('V5 universe or local market cache is missing')
    records = json.loads(universe.read_text(encoding='utf-8'))['records']
    if len(records) != 5225:
        raise SystemExit(f'unexpected provider universe size: {len(records)}')

    print(json.dumps({'event':'prepare','release':RELEASE},ensure_ascii=False),flush=True)
    result = prepare_project(stage, args.python, cache, universe, recursive, args.import_workers)
    package_info = {
        'release': RELEASE, 'algorithm': '缠论V5', 'workbench_profile': UNIVERSE_PROFILE,
        'max_rank': MAX_RANK, 'market_data_as_of': summary['cutoff'],
        'universe_count': len(records), 'recursive_success': summary['success'],
        'recursive_empty_or_failed': summary['failed'], 'execution_allowed': False,
        'strict_original_equivalence_proven': False,
        'excluded_workspace_backups': True,
        'content': ['source and tests', 'local market-data cache', 'L8 recursive reports', 'V5 workbench and imported results'],
        'import': result,
    }
    (stage / 'PACKAGE_INFO.json').write_text(json.dumps(package_info, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    rows = inventory(stage)
    manifest = {'release': RELEASE, 'file_count': len(rows), 'files': rows}
    (stage / 'MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    archive = output / f'{RELEASE}-FULL.zip'
    print(json.dumps({'event':'archive','files':len(rows),'input_bytes':sum(row['bytes'] for row in rows)},ensure_ascii=False),flush=True)
    with zipfile.ZipFile(archive, 'w', allowZip64=True) as target:
        for entry in [*rows,{'path':'MANIFEST.json'}]:
            path=stage/entry['path']
            relative = Path(RELEASE) / entry['path']
            compression = zipfile.ZIP_STORED if path.suffix.lower() in {'.gz', '.exe', '.sqlite3'} else zipfile.ZIP_DEFLATED
            target.write(path, relative.as_posix(), compress_type=compression, compresslevel=4 if compression == zipfile.ZIP_DEFLATED else None)
    with zipfile.ZipFile(archive) as target:
        bad = target.testzip()
        if bad:
            raise RuntimeError(f'archive CRC failed: {bad}')

    extracted = output / 'extracted-verification'
    print(json.dumps({'event':'extract_and_verify','archive_bytes':archive.stat().st_size}),flush=True)
    with zipfile.ZipFile(archive) as target:
        target.extractall(extracted)
    extracted_stage = extracted / RELEASE
    verify_manifest(extracted_stage, rows)
    smoke = verify_extracted(extracted_stage, args.python, output / 'verification')
    receipt = {
        'status': 'pass', 'archive': str(archive), 'archive_bytes': archive.stat().st_size,
        'archive_sha256': digest(archive), 'file_count': len(rows),
        'source_manifest_verified_after_extraction': True, 'zip_crc': 'pass',
        'isolated_extracted_verification': smoke,
        'excluded_workspace_backups': True,
    }
    (output / 'package-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
