from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import build_msi_v4

WIX = {'w': 'http://schemas.microsoft.com/wix/2006/wi',
       'util': 'http://schemas.microsoft.com/wix/UtilExtension'}


class MsiAuthoringTests(unittest.TestCase):
    def test_running_app_is_closed_before_new_files_and_old_product_removal(self):
        document = ET.parse(ROOT / 'installer' / 'ChanlunWorkbenchV4.wxs')
        product = document.getroot().find('w:Product', WIX)
        major = product.find('w:MajorUpgrade', WIX)
        close = product.find('util:CloseApplication', WIX)
        restart = product.find('.//util:RestartResource', WIX)
        files = product.find('.//w:Component[@Id="WorkbenchFiles"]', WIX)
        marker = files.find('w:RegistryValue', WIX)

        self.assertEqual(major.get('Schedule'), 'afterInstallExecute')
        self.assertEqual(close.get('Target'), 'ChanlunWorkbenchV4.exe')
        self.assertEqual(close.get('PromptToContinue'), 'yes')
        self.assertEqual(close.get('CloseMessage'), 'yes')
        self.assertEqual(close.get('Timeout'), '30')
        self.assertEqual(close.get('RebootPrompt'), 'yes')
        self.assertIsNone(close.get('TerminateProcess'))
        self.assertEqual(restart.get('Path'), '[#WorkbenchExe]')
        self.assertEqual(files.get('Guid'), '{D95F465E-C44E-47DA-92BD-9DC4249A6130}')
        self.assertEqual(marker.get('Key'), r'Software\ChanlunWorkbenchV4\4.3.0')
        self.assertEqual(files.find('w:File[@Id="WorkbenchLauncher"]', WIX).get('Name'), 'LaunchV43.cmd')

    def test_msi_build_links_util_extension_and_keeps_selected_data_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wix_bin = root / 'wix'
            wix_bin.mkdir()
            for name in ('candle.exe', 'light.exe', 'WixUIExtension.dll', 'WixUtilExtension.dll'):
                (wix_bin / name).write_bytes(b'tool')
            exe, readme, icon = (root / name for name in ('app.exe', 'README.txt', 'app.ico'))
            for path in (exe, readme, icon):
                path.write_bytes(b'fixture')
            output = root / 'output'
            calls = []

            def run(args, **kwargs):
                calls.append(args)
                if Path(args[0]).name == 'light.exe':
                    msi = Path(args[args.index('-out') + 1])
                    msi.write_bytes(b'fixture msi')
                return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

            with patch.object(sys, 'argv', [
                'build_msi_v4.py', '--wix-bin', str(wix_bin), '--exe', str(exe),
                '--readme', str(readme), '--icon', str(icon), '--output-dir', str(output)]), \
                 patch.object(build_msi_v4.subprocess, 'run', side_effect=run), \
                 patch.object(build_msi_v4.tempfile, 'gettempdir', return_value=str(root / 'tmp')):
                build_msi_v4.main()

            util = str((wix_bin / 'WixUtilExtension.dll').resolve())
            self.assertEqual(len(calls), 2)
            for args in calls:
                ext_positions = [i for i, arg in enumerate(args) if arg == '-ext']
                self.assertTrue(any(args[i + 1] == util for i in ext_positions))
            launcher = root / 'tmp' / f'chanlun-workbench-{build_msi_v4.APP_VERSION}-msi-payload' / 'LaunchV43.cmd'
            launcher_text = launcher.read_text(encoding='ascii')
            self.assertIn('ChanlunWorkbenchV4.exe', launcher_text)
            self.assertNotIn('CHANLUN_APP_DATA_DIR', launcher_text)
            self.assertNotIn('ChanlunV42Data', launcher_text)


if __name__ == '__main__':
    unittest.main()
