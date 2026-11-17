import hashlib
import importlib.util
import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import desktop_app
from chanmodel.release import APP_VERSION,APP_LABEL

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('build_desktop_v4',ROOT/'tools/build_desktop_v4.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


class DesktopV4Tests(unittest.TestCase):
    def test_user_data_directory_can_be_selected_and_persisted(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);settings=root/'settings.json';old=root/'old';new=root/'D-drive/ChanlunData'
            project=old/'project';project.mkdir(parents=True)
            (project/'market_data').mkdir();(project/'market_data/raw.csv').write_text('raw',encoding='utf-8')
            db=project/'runtime/workbench/workbench.sqlite3';db.parent.mkdir(parents=True)
            import sqlite3
            with closing(sqlite3.connect(db)) as connection:
                connection.execute('CREATE TABLE jobs(state TEXT)')
                connection.execute("INSERT INTO jobs VALUES('completed')")
                connection.commit()
            settings.parent.mkdir(parents=True,exist_ok=True)
            settings.write_text(json.dumps({'data_directory':str(old)}),encoding='utf-8')
            with patch.object(desktop_app,'app_settings_path',return_value=settings):
                result=desktop_app.resolve_data_directory(Namespace(data_dir=str(new)))
            self.assertEqual(result,new.resolve())
            self.assertEqual((new/'project/market_data/raw.csv').read_text(encoding='utf-8'),'raw')
            stored=json.loads(settings.read_text(encoding='utf-8'))
            self.assertEqual(Path(stored['data_directory']),new.resolve())
            self.assertTrue(old.exists())

    def test_data_directory_change_refuses_live_jobs_and_preserves_target(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);settings=root/'settings.json';old=root/'old';new=root/'new'
            db=old/'project/runtime/workbench/workbench.sqlite3';db.parent.mkdir(parents=True)
            import sqlite3
            with closing(sqlite3.connect(db)) as connection:
                connection.execute('CREATE TABLE jobs(state TEXT)')
                connection.execute("INSERT INTO jobs VALUES('running')")
                connection.commit()
            settings.write_text(json.dumps({'data_directory':str(old)}),encoding='utf-8')
            with patch.object(desktop_app,'app_settings_path',return_value=settings):
                with self.assertRaisesRegex(ValueError,'任务运行'):
                    desktop_app.resolve_data_directory(Namespace(data_dir=str(new)))
            self.assertFalse(new.exists())
            self.assertEqual(Path(json.loads(settings.read_text(encoding='utf-8'))['data_directory']),old.resolve())

    def test_nonempty_selected_parent_uses_dedicated_child_and_preserves_existing_files(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);settings=root/'settings.json';old=root/'old';parent=root/'D-drive';parent.mkdir()
            (parent/'keep.txt').write_text('keep',encoding='utf-8')
            settings.write_text(json.dumps({'data_directory':str(old)}),encoding='utf-8')
            with patch.object(desktop_app,'app_settings_path',return_value=settings):
                value=desktop_app.resolve_data_directory(Namespace(data_dir=str(parent)))
            self.assertEqual(value,(parent/'ChanlunWorkbenchData').resolve())
            self.assertEqual((parent/'keep.txt').read_text(encoding='utf-8'),'keep')

    def test_nonempty_existing_app_child_is_never_overwritten(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);settings=root/'settings.json';old=root/'old';parent=root/'D-drive'
            target=parent/'ChanlunWorkbenchData';target.mkdir(parents=True)
            (target/'keep.txt').write_text('unrelated',encoding='utf-8')
            (old/'project').mkdir(parents=True)
            settings.write_text(json.dumps({'data_directory':str(old)}),encoding='utf-8')
            with patch.object(desktop_app,'app_settings_path',return_value=settings):
                with self.assertRaisesRegex(ValueError,'子目录已有非工作台文件'):
                    desktop_app.resolve_data_directory(Namespace(data_dir=str(parent)))
            self.assertEqual((target/'keep.txt').read_text(encoding='utf-8'),'unrelated')
            self.assertFalse((target/'project').exists())

    def test_installer_preserves_per_user_upgrade_identity_and_directory_selection(self):
        namespace={'w':'http://schemas.microsoft.com/wix/2006/wi'}
        document=ET.parse(ROOT/'installer/ChanlunWorkbenchV4.wxs')
        product=document.getroot().find('w:Product',namespace)
        package=product.find('w:Package',namespace)
        self.assertEqual(product.get('Version'),'$(var.AppVersion)')
        self.assertEqual(product.get('UpgradeCode'),'{2A0DDDA3-39E6-4FCE-BE79-DBA53BE6B84A}')
        self.assertEqual(package.get('InstallScope'),'perUser')
        self.assertEqual(package.get('Platform'),'x64')
        self.assertEqual(product.find('w:Property[@Id="WIXUI_INSTALLDIR"]',namespace).get('Value'),'INSTALLFOLDER')
        self.assertIsNotNone(product.find('w:UIRef[@Id="WixUI_InstallDir"]',namespace))

    def test_data_directory_cli_option_is_resolved(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);settings=root/'settings.json';chosen=root/'E-drive/ChanlunData'
            settings.write_text(json.dumps({'data_directory':str(root/'old-data')}),encoding='utf-8')
            with patch.object(desktop_app,'app_settings_path',return_value=settings):
                value=desktop_app.resolve_data_directory(Namespace(data_dir=str(chosen)))
            self.assertEqual(value,chosen.resolve())
            self.assertTrue(value.is_dir())
            self.assertFalse((value/'project').exists())

    def test_bundled_project_launcher_forwards_arbitrary_data_directory(self):
        source=(ROOT/'tools/build_desktop_v4.py').read_text(encoding='utf-8')
        self.assertIn("parser.add_argument('--data-dir'",source)
        self.assertIn("args.data_dir",source)
        self.assertIn('default_data_directory',source)

    def test_public_seed_paths_are_portable_and_hashes_remain_intact(self):
        value={'file':'C:/Users/fixture/project/market_data/tdx/day/abc.csv',
               'raw_path':'C:\\Users\\fixture\\private\\unknown.json','csv_sha256':'0123',
               'relative':'runtime/results/example.json'}
        result=builder.portable_value(value)
        self.assertEqual(result['file'],'market_data/tdx/day/abc.csv')
        self.assertEqual(result['raw_path'],'<local_path_omitted>')
        self.assertEqual(result['csv_sha256'],'0123')
        self.assertEqual(result['relative'],value['relative'])
    def resources(self,folder):
        folder.mkdir()
        code=b"VERSION='4.0.0'\n";page=b'<title>V4</title>'
        archive=folder/'project-seed.zip'
        with ZipFile(archive,'w') as z:
            z.writestr('chanmodel/release.py',code)
            z.writestr('workbench/web/index.html',page)
            z.writestr('runtime/workbench/workbench.sqlite3',b'bundled-example-db')
        build={'version':APP_VERSION,'release':APP_LABEL,'payload_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
               'code_sha256':{'chanmodel/release.py':hashlib.sha256(code).hexdigest(),
                              'workbench/web/index.html':hashlib.sha256(page).hexdigest()}}
        (folder/'build-info.json').write_text(json.dumps(build),encoding='utf-8')
        return build

    def test_distribution_is_v4_and_every_live_algorithm_file_is_selected(self):
        with self.assertRaisesRegex(RuntimeError, 'disabled for a non-V4 source tree'):
            builder.source_entries()

    def test_code_repair_preserves_existing_database_and_job_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.resources(root/'resources');data=root/'user-data';data.mkdir()
            with patch.object(desktop_app,'resource_directory',return_value=root/'resources'):
                project,build=desktop_app.prepare_project(data,lambda _:None)
                db=project/'runtime/workbench/workbench.sqlite3';db.write_bytes(b'user-jobs-must-stay')
                result=project/'runtime/workbench/jobs/existing/result.json';result.parent.mkdir(parents=True);result.write_text('saved')
                (project/'chanmodel/release.py').write_text('stale code',encoding='utf-8')
                desktop_app.prepare_project(data,lambda _:None)
            self.assertEqual(db.read_bytes(),b'user-jobs-must-stay')
            self.assertEqual(result.read_text(),'saved')
            self.assertEqual(hashlib.sha256((project/'chanmodel/release.py').read_bytes()).hexdigest(),build['code_sha256']['chanmodel/release.py'])

    def test_corrupted_embedded_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.resources(root/'resources');data=root/'data';data.mkdir()
            archive=root/'resources/project-seed.zip'
            archive.write_bytes(archive.read_bytes()+b'corrupt')
            with patch.object(desktop_app,'resource_directory',return_value=root/'resources'):
                with self.assertRaisesRegex(ValueError,'资源校验失败'):desktop_app.prepare_project(data,lambda _:None)

    def test_incomplete_seed_cannot_claim_successful_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.resources(root/'resources');data=root/'data';data.mkdir()
            info=root/'resources/build-info.json';build=json.loads(info.read_text(encoding='utf-8'))
            build['code_sha256']['chanmodel/missing.py']='0'*64;info.write_text(json.dumps(build),encoding='utf-8')
            with patch.object(desktop_app,'resource_directory',return_value=root/'resources'):
                with self.assertRaisesRegex(ValueError,'不一致'):desktop_app.prepare_project(data,lambda _:None)


if __name__=='__main__':unittest.main()
