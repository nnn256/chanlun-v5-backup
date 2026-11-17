from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chanmodel.release import APP_VERSION, APP_LABEL


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description='Build the per-user V4 Windows Installer package')
    parser.add_argument('--wix-bin', type=Path, required=True,
                        help='WiX v3.14.1 bin directory containing candle.exe, light.exe and WixUIExtension.dll')
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--readme', type=Path, required=True)
    parser.add_argument('--icon', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()

    wix_bin = args.wix_bin.resolve()
    candle, light = wix_bin / 'candle.exe', wix_bin / 'light.exe'
    wix_ui = wix_bin / 'WixUIExtension.dll'
    wix_util = wix_bin / 'WixUtilExtension.dll'
    for path in (candle, light, wix_ui, wix_util, args.exe, args.readme, args.icon):
        if not path.is_file():
            raise FileNotFoundError(path)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    payload=Path(tempfile.gettempdir())/f'chanlun-workbench-{APP_VERSION}-msi-payload'
    payload.mkdir(parents=True,exist_ok=True)
    exe=payload/'ChanlunWorkbenchV4.exe'
    launcher=payload/'LaunchV43.cmd'
    readme=payload/'README.txt'
    icon=payload/'Workbench.ico'
    shutil.copy2(args.exe.resolve(),exe)
    shutil.copy2(args.readme.resolve(),readme)
    shutil.copy2(args.icon.resolve(),icon)
    launcher.write_text('@echo off\r\nsetlocal\r\n'
        'start "" "%~dp0ChanlunWorkbenchV4.exe"\r\n',encoding='ascii',newline='')
    source = ROOT / 'installer' / 'ChanlunWorkbenchV4.wxs'
    object_file = output / 'ChanlunWorkbenchV4.wixobj'
    msi = output / f'ChanlunWorkbenchV4-{APP_VERSION}-x64.msi'
    compiler_args = [str(candle), '-nologo', '-arch', 'x64', '-ext', str(wix_util),
        f'-dAppVersion={APP_VERSION}', f'-dExePath={exe}',
        f'-dLauncherPath={launcher}', f'-dReadmePath={readme}',
        f'-dIconPath={icon}', '-out', str(object_file), str(source)]
    compiled = subprocess.run(compiler_args, cwd=ROOT, capture_output=True, text=True,
                              encoding='utf-8', errors='replace')
    (output / 'candle.stdout.txt').write_text(compiled.stdout, encoding='utf-8')
    (output / 'candle.stderr.txt').write_text(compiled.stderr, encoding='utf-8')
    if compiled.returncode:
        raise RuntimeError(f'WiX candle failed ({compiled.returncode}): {compiled.stderr[-2000:]}')

    linker_args = [str(light), '-nologo', '-ext', str(wix_ui), '-ext', str(wix_util),
                   '-out', str(msi), str(object_file)]
    linked = subprocess.run(linker_args, cwd=ROOT, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    (output / 'light.stdout.txt').write_text(linked.stdout, encoding='utf-8')
    (output / 'light.stderr.txt').write_text(linked.stderr, encoding='utf-8')
    if linked.returncode or not msi.is_file():
        raise RuntimeError(f'WiX light failed ({linked.returncode}): {linked.stderr[-2000:]}')

    receipt = {'version': APP_VERSION, 'release': APP_LABEL, 'architecture': 'x64',
        'install_scope': 'perUser', 'msi': str(msi), 'msi_bytes': msi.stat().st_size,
        'msi_sha256': sha256(msi), 'exe_sha256': sha256(exe),
        'launcher_sha256': sha256(launcher),
        'installer_profile': 'wix_v3_per_user_major_upgrade_close_application_v2'}
    (output / 'msi-build-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
