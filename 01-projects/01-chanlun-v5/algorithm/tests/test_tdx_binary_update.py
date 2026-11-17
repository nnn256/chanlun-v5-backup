"""The update contract preserves running service images and uses verified bytes."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

import desktop_app
from workbench import services


class TdxBinaryUpdateTests(unittest.TestCase):
    def seed(self, resources, binary=b'new-tdx-service'):
        resources.mkdir(exist_ok=True)
        archive=resources/'project-seed.zip'
        page=b'<title>updated workbench</title>'
        with ZipFile(archive,'w') as stream:
            stream.writestr('runtime/tdx-api-revised.exe',binary)
            stream.writestr('workbench/web/index.html',page)
            stream.writestr('runtime/workbench/workbench.sqlite3',b'seed-db')
        build={'version':'fixture','payload_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
               'code_sha256':{'workbench/web/index.html':hashlib.sha256(page).hexdigest()},
               'binary_sha256':{'runtime/tdx-api-revised.exe':hashlib.sha256(binary).hexdigest()}}
        (resources/'build-info.json').write_text(json.dumps(build),encoding='utf-8')
        return build

    def test_update_leaves_legacy_exe_and_user_database_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'resources';self.seed(resources)
            data=root/'data';project=data/'project';legacy=project/'runtime/tdx-api-revised.exe'
            legacy.parent.mkdir(parents=True);legacy.write_bytes(b'old-running-image')
            database=project/'runtime/workbench/workbench.sqlite3';database.parent.mkdir()
            database.write_bytes(b'user-saved-jobs')
            with patch.object(desktop_app,'resource_directory',return_value=resources):
                prepared,build=desktop_app.prepare_project(data,lambda message:None)
            with patch.object(services,'ROOT',prepared):
                active=services.tdx_binary()
            self.assertNotEqual(active,legacy)
            self.assertEqual(active.read_bytes(),b'new-tdx-service')
            self.assertEqual(legacy.read_bytes(),b'old-running-image')
            self.assertEqual(database.read_bytes(),b'user-saved-jobs')
            self.assertEqual(build['tdx_runtime']['sha256'],hashlib.sha256(active.read_bytes()).hexdigest())

    @unittest.skipUnless(os.name=='nt','Windows sharing violation regression')
    def test_actual_windows_running_image_lock_does_not_block_update(self):
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,
                                     wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'resources';self.seed(resources)
            data=root/'data';legacy=data/'project/runtime/tdx-api-revised.exe'
            legacy.parent.mkdir(parents=True);legacy.write_bytes(b'locked-old-image')
            handle=kernel.CreateFileW(str(legacy),0x80000000,0x1|0x2,None,3,0,None)
            self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
            try:
                staging=legacy.with_name(legacy.name+'.installing');staging.write_bytes(b'new-bytes')
                with self.assertRaises(PermissionError):staging.replace(legacy)
                with patch.object(desktop_app,'resource_directory',return_value=resources):
                    project,build=desktop_app.prepare_project(data,lambda message:None)
                self.assertEqual(legacy.read_bytes(),b'locked-old-image')
                self.assertEqual((project/build['tdx_runtime']['path']).read_bytes(),b'new-tdx-service')
            finally:kernel.CloseHandle(handle)

    def test_two_releases_have_independent_service_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'resources';self.seed(resources,b'release-one')
            data=root/'data'
            with patch.object(desktop_app,'resource_directory',return_value=resources):
                project,first=desktop_app.prepare_project(data,lambda message:None)
                self.seed(resources,b'release-two')
                _,second=desktop_app.prepare_project(data,lambda message:None)
            self.assertNotEqual(first['tdx_runtime']['path'],second['tdx_runtime']['path'])
            self.assertEqual((project/first['tdx_runtime']['path']).read_bytes(),b'release-one')
            self.assertEqual((project/second['tdx_runtime']['path']).read_bytes(),b'release-two')
            with patch.object(services,'ROOT',project):
                self.assertEqual(services.tdx_binary(),project/second['tdx_runtime']['path'])

    def test_same_release_never_replaces_an_existing_service_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'resources';self.seed(resources)
            data=root/'data'
            with patch.object(desktop_app,'resource_directory',return_value=resources):
                project,build=desktop_app.prepare_project(data,lambda message:None)
                active=project/build['tdx_runtime']['path']
                original_replace=Path.replace
                def replace(source,target):
                    if Path(target)==active:raise AssertionError('unchanged service was rewritten')
                    return original_replace(source,target)
                with patch.object(Path,'replace',replace):desktop_app.prepare_project(data,lambda message:None)

    def test_binary_digest_mismatch_does_not_mark_build_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'resources';build=self.seed(resources)
            build['binary_sha256']['runtime/tdx-api-revised.exe']='0'*64
            (resources/'build-info.json').write_text(json.dumps(build),encoding='utf-8')
            data=root/'data'
            with patch.object(desktop_app,'resource_directory',return_value=resources):
                with self.assertRaisesRegex(ValueError,'内置TDX行情程序校验失败'):
                    desktop_app.prepare_project(data,lambda message:None)
            self.assertFalse((data/'installed-build.json').exists())

    def test_selected_service_binary_is_verified_and_cannot_escape_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp);info=desktop_app.stage_tdx_binary(project,b'expected-service')
            manifest=project/'runtime/tdx-runtime.json'
            manifest.write_text(json.dumps(info),encoding='utf-8')
            with patch.object(services,'ROOT',project):
                self.assertEqual(services.tdx_binary().read_bytes(),b'expected-service')
                (project/info['path']).write_bytes(b'corrupted')
                with self.assertRaisesRegex(ValueError,'校验失败'):services.tdx_binary()
                info['path']='../../outside.exe';manifest.write_text(json.dumps(info),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'路径无效'):services.tdx_binary()

    def test_malformed_runtime_manifest_is_rejected_as_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp);manifest=project/'runtime/tdx-runtime.json';manifest.parent.mkdir()
            for info in [[],{'schema':1,'sha256':42},{'schema':1,'sha256':'a'*64,'path':'../outside.exe'}]:
                manifest.write_text(json.dumps(info),encoding='utf-8')
                with patch.object(services,'ROOT',project):
                    with self.assertRaises(ValueError):services.tdx_binary()

    def test_service_launcher_uses_selected_verified_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);info=desktop_app.stage_tdx_binary(root,b'current-service')
            (root/'runtime/tdx-runtime.json').write_text(json.dumps(info),encoding='utf-8')
            process=Mock(pid=123);process.poll.return_value=None
            with patch.object(services,'ROOT',root),patch.object(services,'STATE',root/'state'), \
                 patch.object(services,'OWNED_PROCESS',None),patch.object(services,'LAST_READY',0), \
                 patch.object(services,'LAST_RESULT',None), \
                 patch.object(services,'probe',side_effect=[ConnectionRefusedError(),{'ready':True}]), \
                 patch.object(services.subprocess,'Popen',return_value=process) as launch:
                result=services.ensure_tdx(force=True)
            self.assertTrue(result['ready'])
            self.assertEqual(launch.call_args.args[0],[str(root/info['path'])])
            status=json.loads((root/'state/tdx-service.json').read_text(encoding='utf-8'))
            self.assertEqual(status['binary_sha256'],info['sha256'])


if __name__=='__main__':unittest.main()
