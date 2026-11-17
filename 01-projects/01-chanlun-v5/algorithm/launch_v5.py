"""Launch the local V5 workbench from this folder without downloading anything."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser


ROOT = Path(__file__).resolve().parent
PROFILE = 'course_feature_sequence_recursive_v2'


def matches_health(health, database):
    return (
        health.get('service') == 'chanlun-workbench-v1'
        and health.get('release') == 'V5'
        and health.get('version') == '5.0.0'
        and health.get('workbench_profile') == PROFILE
        and Path(health.get('database', '')).resolve() == database.resolve()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8895)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11+ is required')
    if not 1024 <= args.port <= 65535:
        parser.error('--port must be 1024..65535')
    database = ROOT.parent / 'workbench-data-8895/workbench.sqlite3'
    url = f'http://127.0.0.1:{args.port}'
    def health():
        try:
            with urllib.request.urlopen(url + '/api/health', timeout=2) as response:
                return json.load(response)
        except (OSError, ValueError):
            return None
    current = health()
    if current is not None and not matches_health(current, database):
        raise RuntimeError(f'Port {args.port} contains a different workbench; choose another --port')
    if current is None:
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', args.port)) == 0:
                raise RuntimeError(f'Port {args.port} is occupied by a different service')
        logs = ROOT.parent / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ, 'PYTHONIOENCODING': 'utf-8',
            'CHANLUN_WORKBENCH_ROOT': '.',
            'CHANLUN_WORKBENCH_DATA_DIR': '../workbench-data-8895',
            'CHANLUN_APP_DATA_DIR': '../workbench-data-8895',
            'CHANLUN_V5_PROFILE': PROFILE,
            'CHANLUN_V5_UNIVERSE': '../runs/full-market-20261114-tdx-partial/universe.json',
        }
        stamp = time.time_ns()
        with (logs / f'v5-{stamp}.stdout.log').open('wb') as out, (logs / f'v5-{stamp}.stderr.log').open('wb') as err:
            process = subprocess.Popen(
                [sys.executable, '-m', 'workbench.server', '--port', str(args.port)],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            current = health()
            if current is not None:
                if not matches_health(current, database):
                    raise RuntimeError('Started server returned a different V5 database or profile')
                break
            if process.poll() is not None:
                raise RuntimeError(f'Workbench exited with code {process.returncode}; see {logs}')
            time.sleep(.4)
        else:
            raise RuntimeError(f'Workbench startup timed out; see {logs}')
    print(f'V5 READY {url}')
    if not args.no_browser:
        webbrowser.open(url)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f'START FAILED: {exc}', file=sys.stderr)
        raise SystemExit(1)
