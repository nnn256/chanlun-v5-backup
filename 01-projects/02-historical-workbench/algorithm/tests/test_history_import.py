import copy
import gzip
import hashlib
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from chanmodel.v2.io import load_cache_series
from workbench import history_archive as archive,history_import as importer
from tests.test_history_archive import pair


def rewrite(source,target,change=None,extra=None):
    with ZipFile(source) as original:
        files={name:original.read(name) for name in original.namelist()}
    manifest=json.loads(files['manifest.json'])
    if change:change(manifest,files)
    files['manifest.json']=json.dumps(manifest).encode()
    with ZipFile(target,'w',ZIP_DEFLATED) as result:
        for name,raw in files.items():result.writestr(name,raw)
        if extra:result.writestr(*extra)
    return target


class HistoryImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.source=self.base/'source';self.target=self.base/'target'
        self.source.mkdir();self.target.mkdir()
        self.contexts=[patch.object(archive,'ROOT',self.source),patch.object(archive,'STATE',self.source/'runtime/workbench'),
            patch.object(importer,'ROOT',self.target),patch.object(importer,'STATE',self.target/'runtime/workbench'),
            patch.object(archive.shutil,'disk_usage',return_value=SimpleNamespace(free=100*1024**3))]
        for item in self.contexts:item.start();self.addCleanup(item.stop)
        archive.INVENTORY_CACHE.clear()

    def export(self,codes=('sh600000',),periods=('day',),compressed=False):
        for code in codes:
            for period in periods:pair(self.source/'market_data',symbol=code,period=period,compressed=compressed or period!='day')
        return Path(archive.create_export(period='all')['path'])

    def install(self,path):
        # The archive verifier and importer normally share the same ROOT.
        with patch.object(archive,'ROOT',self.target):return importer.import_history_archive(path)

    def test_complete_export_roundtrip_is_discoverable_and_no_existing_cache_is_overwritten(self):
        path=self.export(periods=('day','5m','30m'))
        original=self.target/'market_data/keep.txt';original.parent.mkdir();original.write_text('retain')
        result=self.install(path)
        self.assertEqual(result['state'],'ready');self.assertEqual(result['pairs'],3)
        cache=Path(result['cache_root']);self.assertTrue(cache.is_dir())
        for period in ('day','5m','30m'):
            series,receipt=load_cache_series(cache,'sh600000',period)
            self.assertEqual(len(series.bars),3);self.assertTrue(receipt['provider_identity_receipt_checked'])
        self.assertEqual(original.read_text(),'retain')
        self.assertTrue(Path(result['receipt_path']).is_file())
        second=self.install(path)
        self.assertTrue(second['reused']);self.assertEqual(second['cache_root'],result['cache_root'])

    def test_deduplicated_member_names_are_remapped_for_each_security(self):
        path=self.export(codes=('sh600000','sz000001'))
        with ZipFile(path) as source:
            manifest=json.loads(source.read('manifest.json'))
            self.assertEqual(manifest['sources'][0]['csv_path'],manifest['sources'][1]['csv_path'])
        result=self.install(path);cache=Path(result['cache_root'])
        for code in ('sh600000','sz000001'):
            series,_=load_cache_series(cache,code,'day');self.assertEqual(series.symbol,code)
            meta=json.loads((cache/f'tdx/day/metadata/{code}.json').read_text())
            self.assertIn(code+'.csv',meta['csv_path']);self.assertNotIn('DO_NOT_EXPORT',json.dumps(meta))

    def test_compressed_daily_source_becomes_plain_canonical_day_csv(self):
        path=self.export(compressed=True);result=self.install(path)
        cache=Path(result['cache_root']);self.assertTrue((cache/'tdx/day/ohlcv/sh600000.csv').is_file())
        series,_=load_cache_series(cache,'sh600000','day');self.assertEqual(len(series.bars),3)

    def test_traversal_extra_settings_and_duplicate_zip_members_are_rejected(self):
        path=self.export()
        for index,extra in enumerate((('../outside.txt',b'bad'),('runtime/settings.json',b'secret'),
                                      ('tdx/day/ohlcv/sh600000.csv',b'duplicate'))):
            malformed=rewrite(path,self.base/f'bad-{index}.zip',extra=extra)
            with self.subTest(extra=extra[0]),self.assertRaises(ValueError):self.install(malformed)
        self.assertFalse((self.base/'outside.txt').exists())
        self.assertFalse((self.target/'runtime/workbench/jobs').exists())

    def test_zip_symlink_member_is_rejected_without_extraction(self):
        path=self.export();target=self.base/'symlink.zip'
        with ZipFile(path) as original,ZipFile(target,'w',ZIP_DEFLATED) as out:
            for name in original.namelist():
                info=ZipInfo(name);info.compress_type=ZIP_DEFLATED
                if '/ohlcv/' in name:info.external_attr=(stat.S_IFLNK|0o777)<<16
                out.writestr(info,original.read(name))
        with self.assertRaisesRegex(ValueError,'linked'):self.install(target)

    def test_member_checksum_and_metadata_identity_fail_atomically(self):
        original=self.export()
        def wrong_hash(manifest,files):manifest['files'][0]['sha256']='a'*64
        def wrong_identity(manifest,files):
            name=manifest['sources'][0]['metadata_path'];meta=json.loads(files[name]);meta['symbol']='sz000001'
            files[name]=json.dumps(meta).encode()
            entry=next(row for row in manifest['files'] if row['path']==name)
            entry.update(bytes=len(files[name]),sha256=hashlib.sha256(files[name]).hexdigest())
        for index,change in enumerate((wrong_hash,wrong_identity)):
            path=rewrite(original,self.base/f'wrong-{index}.zip',change)
            with self.subTest(index=index),self.assertRaises(ValueError):self.install(path)
        self.assertFalse((self.target/'runtime/workbench/jobs').exists())
        staging=self.target/'runtime/workbench/history-imports-staging'
        self.assertEqual(list(staging.iterdir()),[])

    def test_duplicate_source_and_unlisted_reference_are_rejected(self):
        original=self.export()
        for index,change in enumerate((lambda m,f:m['sources'].append(copy.deepcopy(m['sources'][0])),
                                       lambda m,f:m['sources'][0].update(csv_path='tdx/day/ohlcv/sz000001.csv'))):
            path=rewrite(original,self.base/f'bad-source-{index}.zip',change)
            with self.subTest(index=index),self.assertRaises(ValueError):self.install(path)

    def test_manifest_coverage_cannot_claim_different_rows(self):
        original=self.export()
        path=rewrite(original,self.base/'wrong-coverage.zip',lambda m,f:m['sources'][0]['coverage'].update(rows=999))
        with self.assertRaisesRegex(ValueError,'coverage differs'):self.install(path)
        self.assertFalse((self.target/'runtime/workbench/jobs').exists())

    def test_disk_member_and_canonical_budget_guards(self):
        path=self.export()
        with patch.object(importer.shutil,'disk_usage',return_value=SimpleNamespace(free=1024)):
            with self.assertRaisesRegex(ValueError,'free disk'):self.install(path)
        with patch.object(importer,'MAX_MEMBER_BYTES',10):
            with self.assertRaisesRegex(ValueError,'size budget'):self.install(path)
        with patch.object(importer,'MAX_TOTAL_BYTES',10):
            with self.assertRaisesRegex(ValueError,'budget'):self.install(path)

    def test_missing_metadata_file_size_and_unsupported_schema_are_rejected(self):
        original=self.export()
        cases=(lambda m,f:m.update(schema='other'),lambda m,f:m['files'][0].update(bytes=999),
               lambda m,f:m['sources'][0].update(metadata_path='tdx/day/metadata/missing.json'))
        for index,change in enumerate(cases):
            path=rewrite(original,self.base/f'bad-manifest-{index}.zip',change)
            with self.subTest(index=index),self.assertRaises(ValueError):self.install(path)


if __name__=='__main__':unittest.main()
