import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import io
import importlib.util

from workbench.runtime_protection import (
    PayloadProtectionError,seal_payload,open_payload,load_embedded_payload)


@unittest.skipUnless(os.name=='nt','Windows CNG integration')
class RuntimeProtectionTests(unittest.TestCase):
    def test_authenticated_roundtrip_and_unique_nonce(self):
        key=secrets.token_bytes(32);data=b'PK'+b'private resource'*1000
        metadata={'build_id':'fixed-build','version':'4.4.7'}
        one=seal_payload(data,key,metadata);two=seal_payload(data,key,metadata)
        self.assertNotEqual(one,two)
        self.assertNotIn(data[:100],one)
        self.assertEqual(open_payload(one,key,metadata),data)

    def test_ciphertext_tag_key_and_build_metadata_tamper_are_rejected(self):
        key=secrets.token_bytes(32);metadata={'id':'source-build'}
        sealed=seal_payload(b'compressed resources',key,metadata)
        for index in (8,20,len(sealed)-1):
            bad=bytearray(sealed);bad[index]^=1
            with self.assertRaises(PayloadProtectionError):open_payload(bytes(bad),key,metadata)
        with self.assertRaises(PayloadProtectionError):open_payload(sealed,secrets.token_bytes(32),metadata)
        with self.assertRaises(PayloadProtectionError):open_payload(sealed,key,{'id':'other-build'})

    def test_bad_format_and_key_length_are_not_accepted(self):
        for value in (b'',b'PKzip',b'CLRP1\0'):
            with self.assertRaises(PayloadProtectionError):open_payload(value,b'k'*32,{})
        with self.assertRaises(PayloadProtectionError):seal_payload(b'data',b'short',{})

    def test_embedded_key_module_and_ciphertext_are_verified_together(self):
        key=secrets.token_bytes(32);payload=b'resource-archive'
        plain_hash=hashlib.sha256(payload).hexdigest()
        metadata={'build_id':'build-one','version':'fixture','plaintext_sha256':plain_hash}
        sealed=seal_payload(payload,key,metadata)
        info={'version':'fixture','payload_sha256':hashlib.sha256(sealed).hexdigest(),
            'payload_protection':{'format':'windows-cng-aes256-gcm-v1','filename':'project-seed.bin',
                'build_id':'build-one','plaintext_sha256':plain_hash}}
        module=types.ModuleType('_chanlun_payload_key');module.KEY=key;module.BUILD_ID='build-one'
        with tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules,{'_chanlun_payload_key':module}):
            root=Path(tmp);(root/'project-seed.bin').write_bytes(sealed)
            self.assertEqual(load_embedded_payload(root,info),payload)
            module.BUILD_ID='other-build'
            with self.assertRaisesRegex(PayloadProtectionError,'身份'):load_embedded_payload(root,info)


class LegacyPayloadTests(unittest.TestCase):
    def test_legacy_zip_is_read_only_and_requires_original_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'project-seed.zip'
            with ZipFile(path,'w') as z:z.writestr('workbench/web/index.html','static')
            raw=path.read_bytes();build={'payload_sha256':hashlib.sha256(raw).hexdigest()}
            self.assertEqual(load_embedded_payload(root,build),raw)
            path.write_bytes(raw+b'changed')
            with self.assertRaisesRegex(PayloadProtectionError,'校验失败'):load_embedded_payload(root,build)


@unittest.skipUnless(os.name=='nt','Windows protected package integration')
class ProtectedProjectTests(unittest.TestCase):
    def seed(self,resources,extra=None):
        from workbench.runtime_protection import seal_payload
        resources.mkdir()
        page=b'<title>protected workbench</title>'
        archive=io.BytesIO()
        with ZipFile(archive,'w') as z:
            z.writestr('workbench/web/index.html',page)
            z.writestr('runtime/workbench/workbench.sqlite3',b'example-db')
            if extra:z.writestr(*extra)
        raw=archive.getvalue();key=secrets.token_bytes(32);build_id=secrets.token_hex(8)
        plain_hash=hashlib.sha256(raw).hexdigest()
        metadata={'version':'fixture','build_id':build_id,'plaintext_sha256':plain_hash}
        sealed=seal_payload(raw,key,metadata)
        (resources/'project-seed.bin').write_bytes(sealed)
        build={'version':'fixture','payload_sha256':hashlib.sha256(sealed).hexdigest(),
            'code_sha256':{'chanmodel/must-not-extract.py':'0'*64},
            'runtime_files_sha256':{'workbench/web/index.html':hashlib.sha256(page).hexdigest(),
                'runtime/workbench/workbench.sqlite3':hashlib.sha256(b'example-db').hexdigest()},
            'runtime_immutable_files_sha256':{'workbench/web/index.html':hashlib.sha256(page).hexdigest()},
            'payload_protection':{'format':'windows-cng-aes256-gcm-v1','filename':'project-seed.bin',
                'build_id':build_id,'plaintext_sha256':plain_hash}}
        (resources/'build-info.json').write_text(json.dumps(build),encoding='utf-8')
        module=types.ModuleType('_chanlun_payload_key');module.KEY=key;module.BUILD_ID=build_id
        return build,module

    def test_protected_install_uses_runtime_manifest_and_repairs_static_without_source_or_user_data_loss(self):
        import desktop_app
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'resources';build,module=self.seed(resources)
            data=root/'data';data.mkdir()
            with patch.object(desktop_app,'resource_directory',return_value=resources), \
                 patch.dict(sys.modules,{'_chanlun_payload_key':module}):
                project,_=desktop_app.prepare_project(data,lambda _:None)
                self.assertFalse((project/'chanmodel').exists())
                self.assertFalse(list(project.rglob('*.py')))
                marker=json.loads((data/'installed-build.json').read_text(encoding='utf-8'))
                self.assertNotIn('code_sha256',marker)
                self.assertNotIn('runtime_files_sha256',marker)
                db=project/'runtime/workbench/workbench.sqlite3';db.write_bytes(b'user-jobs')
                saved=project/'runtime/workbench/jobs/user/result.json';saved.parent.mkdir(parents=True)
                saved.write_text('must remain',encoding='utf-8')
                (project/'workbench/web/index.html').write_text('damaged',encoding='utf-8')
                desktop_app.prepare_project(data,lambda _:None)
                self.assertEqual(db.read_bytes(),b'user-jobs')
                self.assertEqual(saved.read_text(),'must remain')
                self.assertEqual(hashlib.sha256((project/'workbench/web/index.html').read_bytes()).hexdigest(),
                                 build['runtime_files_sha256']['workbench/web/index.html'])

    def test_protected_archive_cannot_smuggle_python_source(self):
        import desktop_app
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'resources';_,module=self.seed(resources,('chanmodel/private.py','secret=1'))
            data=root/'data';data.mkdir()
            with patch.object(desktop_app,'resource_directory',return_value=resources), \
                 patch.dict(sys.modules,{'_chanlun_payload_key':module}):
                with self.assertRaisesRegex(ValueError,'源码'):desktop_app.prepare_project(data,lambda _:None)
            self.assertFalse((data/'installed-build.json').exists())

    def test_upgrade_preserves_existing_python_files_without_releasing_new_source(self):
        import desktop_app
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'resources';_,module=self.seed(resources)
            data=root/'data';old=data/'project/chanmodel/old-user-edited.py';old.parent.mkdir(parents=True)
            old.write_text('preserve old local work',encoding='utf-8')
            with patch.object(desktop_app,'resource_directory',return_value=resources), \
                 patch.dict(sys.modules,{'_chanlun_payload_key':module}):
                project,_=desktop_app.prepare_project(data,lambda _:None)
            self.assertEqual(old.read_text(encoding='utf-8'),'preserve old local work')
            self.assertEqual(list(project.rglob('*.py')),[old])

    def test_missing_tdx_resource_is_restored_from_protected_payload(self):
        import desktop_app
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'resources';build,module=self.seed(resources,('runtime/tdx-api-revised.exe',b'tdx-fixture'))
            build['binary_sha256']={'runtime/tdx-api-revised.exe':hashlib.sha256(b'tdx-fixture').hexdigest()}
            (resources/'build-info.json').write_text(json.dumps(build),encoding='utf-8')
            data=root/'data';data.mkdir()
            with patch.object(desktop_app,'resource_directory',return_value=resources), \
                 patch.dict(sys.modules,{'_chanlun_payload_key':module}):
                project,installed=desktop_app.prepare_project(data,lambda _:None)
                image=project/installed['tdx_runtime']['path'];image.unlink()
                desktop_app.prepare_project(data,lambda _:None)
                self.assertEqual(image.read_bytes(),b'tdx-fixture')

    def test_damaged_tdx_image_is_repaired_only_from_authenticated_bundled_bytes(self):
        import desktop_app
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'resources';build,module=self.seed(resources,('runtime/tdx-api-revised.exe',b'tdx-fixture'))
            build['binary_sha256']={'runtime/tdx-api-revised.exe':hashlib.sha256(b'tdx-fixture').hexdigest()}
            (resources/'build-info.json').write_text(json.dumps(build),encoding='utf-8')
            data=root/'data';data.mkdir()
            with patch.object(desktop_app,'resource_directory',return_value=resources), \
                 patch.dict(sys.modules,{'_chanlun_payload_key':module}):
                project,installed=desktop_app.prepare_project(data,lambda _:None)
                image=project/installed['tdx_runtime']['path'];image.write_bytes(b'corrupted image')
                desktop_app.prepare_project(data,lambda _:None)
                self.assertEqual(image.read_bytes(),b'tdx-fixture')

    def test_runtime_entries_filter_own_sources_but_keep_browser_and_data(self):
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('_protected_builder_fixture',root/'tools/build_desktop_v4.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        entries={'chanmodel/engine.py':Path('engine.py'),'workbench/server.py':Path('server.py'),
            'tools/capture.py':Path('capture.py'),'run.py':Path('run.py'),
            'third_party/chanpy/provenance.json':Path('provenance.json'),
            'workbench/web/app.js':Path('app.js'),'market_data/a.csv':Path('a.csv'),
            'runtime/tdx-api-revised.exe':Path('tdx-api-revised.exe')}
        result=builder.runtime_entries(entries)
        self.assertEqual(set(result),{'workbench/web/app.js','market_data/a.csv','runtime/tdx-api-revised.exe'})


if __name__=='__main__':unittest.main()
