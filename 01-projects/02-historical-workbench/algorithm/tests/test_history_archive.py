from concurrent.futures import Future, ThreadPoolExecutor
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from workbench import history_archive as history


def pair(cache, symbol='sh600000', period='day', start='2026-11-09', rows=3, compressed=False, raw=True, **changes):
    folder = cache / 'tdx' / history.PERIODS[period]
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=['closed_at','open','high','low','close','volume','is_closed'])
    writer.writeheader()
    first = datetime.fromisoformat(start + 'T15:00:00+08:00')
    for index in range(rows):
        moment = first + timedelta(days=index)
        writer.writerow({'closed_at': moment.isoformat(), 'open': 10, 'high': 11, 'low': 9,
                         'close': 10, 'volume': 100, 'is_closed': 'true'})
    csv_bytes = stream.getvalue().encode()
    path = folder / 'ohlcv' / (symbol + ('.csv.gz' if compressed else '.csv'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(csv_bytes, mtime=0) if compressed else csv_bytes)
    value = {'symbol': symbol, 'source': 'tdx', 'period': history.PERIODS[period], 'adjustment': 'unadjusted',
        'csv_sha256': hashlib.sha256(csv_bytes).hexdigest(), 'closed_rows': rows,
        'received_at': (first + timedelta(days=rows)).isoformat(),
        'first_date': first.date().isoformat(), 'last_date': moment.date().isoformat(),
        'first_close': first.isoformat(), 'last_close': moment.isoformat(),
        'csv_path': 'C:/secret/private.csv', 'raw_path': 'C:/secret/private.json',
        'url': 'https://provider.invalid/path?token=DO_NOT_EXPORT', 'arbitrary_secret': 'DO_NOT_EXPORT'}
    if compressed: value['csv_storage_sha256'] = history._hash(path)[0]
    if raw:
        provider = json.dumps({'code':0,'data':{'price':10}}).encode()
        raw_path = folder / 'raw' / (symbol + '.json.gz');raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(gzip.compress(provider, mtime=0))
        value.update(raw_storage_sha256=history._hash(raw_path)[0], response_sha256=hashlib.sha256(provider).hexdigest())
    value.update(changes)
    metadata = folder / 'metadata' / (symbol + '.json');metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(json.dumps(value), encoding='utf-8')
    return path, metadata


class HistoryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'project';self.root.mkdir()
        self.contexts=[patch.object(history,'ROOT',self.root),patch.object(history,'STATE',self.root/'runtime/workbench'),
                       patch.object(history.shutil,'disk_usage',return_value=SimpleNamespace(free=100*1024**3))]
        for context in self.contexts:context.start();self.addCleanup(context.stop)
        history.INVENTORY_CACHE.clear();history.FLIGHTS.clear()

    def test_inventory_is_metadata_only_paged_and_does_not_create_export(self):
        pair(self.root/'market_data');pair(self.root/'market_data',symbol='sz000001')
        with patch.object(history,'_hash',side_effect=AssertionError('inventory read a large source body')):
            result=history.history_inventory('day',offset=1,limit=1)
        self.assertEqual(result['total'],2)
        self.assertEqual(result['rows'][0]['symbol'],'sz000001')
        self.assertFalse(result['rows'][0]['content_hash_verified'])
        self.assertFalse((self.root/'runtime/workbench/history-exports').exists())

    def test_export_selects_one_whole_latest_pair_and_excludes_secrets(self):
        pair(self.root/'market_data',start='2026-11-01')
        pair(self.root/'runtime/workbench/jobs/new/cache',start='2026-11-09')
        (self.root/'runtime/workbench/settings.json').write_text('DO_NOT_EXPORT')
        result=history.create_export()
        self.assertEqual(result['state'],'ready');self.assertEqual(result['coverage']['exported_pairs'],1)
        self.assertEqual(result['files'],4)
        self.assertEqual(history._hash(Path(result['path']),maximum=None)[0],result['sha256'])
        with ZipFile(result['path']) as archive:
            self.assertIsNone(archive.testzip())
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['sources'][0]['coverage']['last_closed'][:10],'2026-11-11')
            self.assertEqual(manifest['sources'][0]['alternative_sources'],1)
            metadata=archive.read('tdx/day/metadata/sh600000.json')
            self.assertNotIn(b'DO_NOT_EXPORT',metadata);self.assertNotIn(b'C:/secret',metadata)
            self.assertNotIn('settings.json',' '.join(archive.namelist()))
            for entry in manifest['files']:
                self.assertEqual(hashlib.sha256(archive.read(entry['path'])).hexdigest(),entry['sha256'])

    def test_compressed_intraday_is_validated_and_content_duplicates_are_written_once(self):
        pair(self.root/'market_data',period='5m',compressed=True)
        pair(self.root/'market_data',symbol='sz000001',period='5m',compressed=True)
        result=history.create_export(period='minute5')
        self.assertEqual(result['coverage']['exported_pairs'],2)
        with ZipFile(result['path']) as archive:
            manifest=json.loads(archive.read('manifest.json'));a,b=manifest['sources']
            self.assertEqual(a['csv_path'],b['csv_path']);self.assertEqual(a['raw_path'],b['raw_path'])
            self.assertEqual(len(manifest['files']),4)
            self.assertEqual(len(archive.namelist()),5)

    def test_newest_corrupt_content_falls_back_to_valid_source_without_modifying_it(self):
        path,_=pair(self.root/'market_data',start='2026-11-01');before=path.read_bytes()
        latest,_=pair(self.root/'runtime/workbench/jobs/new/cache',start='2026-11-09')
        latest.write_bytes(b'corrupt CSV')
        result=history.create_export()
        with ZipFile(result['path']) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['rejected_source_count'],1)
            self.assertEqual(manifest['sources'][0]['coverage']['last_closed'][:10],'2026-11-03')
        self.assertEqual(path.read_bytes(),before);self.assertEqual(latest.read_bytes(),b'corrupt CSV')

    def test_all_corrupt_does_not_leave_partial_or_successful_export(self):
        path,_=pair(self.root/'market_data');path.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'no history sources passed'):
            history.create_export()
        self.assertEqual(list((self.root/'runtime/workbench/history-exports').iterdir()),[])

    def test_content_rowcount_and_raw_checksum_validation_reject_mismatches(self):
        for changes in ({'closed_rows':99},{'raw_storage_sha256':'a'*64},{'response_sha256':'b'*64}):
            pair(self.root/'market_data',**changes)
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'no history sources passed'):
                history.create_export()

    def test_forming_suffix_is_exported_whole_while_closed_coverage_remains_truthful(self):
        path,metadata=pair(self.root/'market_data',rows=2)
        with path.open('a',encoding='utf-8',newline='') as stream:
            stream.write('2026-11-11T15:00:00+08:00,10,11,9,10,100,false\r\n')
        meta=json.loads(metadata.read_text());meta['csv_sha256']=history._hash(path)[0]
        metadata.write_text(json.dumps(meta))
        result=history.create_export()
        with ZipFile(result['path']) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            source=manifest['sources'][0]
            self.assertEqual(source['coverage']['rows'],3)
            self.assertEqual(source['coverage']['closed_rows'],2)
            self.assertEqual(source['coverage']['forming_rows'],1)
            self.assertEqual(source['coverage']['last_closed'][:10],'2026-11-10')
            self.assertIn(b'false',archive.read(source['csv_path']))

    def test_source_revision_between_validation_and_zip_copy_aborts_atomic_export(self):
        path,_=pair(self.root/'market_data')
        verify=history._verify
        def changing(item):
            result=verify(item);path.write_bytes(path.read_bytes()+b'changed after validation');return result
        with patch.object(history,'_verify',side_effect=changing):
            with self.assertRaisesRegex(ValueError,'changed while writing ZIP'):history.create_export()
        self.assertEqual(list((self.root/'runtime/workbench/history-exports').iterdir()),[])

    def test_linked_input_is_rejected_even_when_os_symlink_creation_is_unavailable(self):
        path,_=pair(self.root/'market_data')
        actual=Path.is_symlink
        def simulated(candidate):return candidate==path or actual(candidate)
        with patch.object(Path,'is_symlink',simulated):
            value=history.history_inventory(refresh=True)
        self.assertEqual(value['total'],0)
        self.assertEqual(value['invalid_sources_count'],1)

    def test_partial_coverage_is_explicit_and_missing_original_raw_is_not_generated(self):
        pair(self.root/'market_data',raw=False)
        bad,_=pair(self.root/'market_data',symbol='sz000001');bad.write_bytes(b'corrupt')
        result=history.create_export()
        self.assertEqual(result['state'],'partial')
        self.assertEqual(result['coverage']['failed_pairs'],1)
        with ZipFile(result['path']) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertIsNone(manifest['sources'][0]['raw_path'])
            self.assertEqual(len(archive.namelist()),3)

    def test_disk_budget_and_scope_validation_precede_archive_writes(self):
        pair(self.root/'market_data')
        with patch.object(history.shutil,'disk_usage',return_value=SimpleNamespace(free=1024)):
            with self.assertRaisesRegex(ValueError,'free disk'):history.create_export()
        with patch.object(history,'MAX_EXPORT_SOURCE_BYTES',1):
            with self.assertRaisesRegex(ValueError,'source budget'):history.create_export()
        for kwargs in ({'period':'../../db'},{'symbol':'../../settings'},{'scope':'stock'},
                       {'scope':'all','symbol':'sh600000'},{'scope':'secret'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):history.create_export(**kwargs)
        with self.assertRaisesRegex(ValueError,'multi-security export is not supported'):
            history.create_export(scope='selected',symbol='sh600000')

    def test_external_symlinks_and_metadata_absolute_path_injection_are_not_followed(self):
        external=Path(self.temp.name)/'outside';outside,_=pair(external)
        target=self.root/'market_data/tdx/day/ohlcv/sh600000.csv';target.parent.mkdir(parents=True)
        try: target.symlink_to(outside)
        except OSError:self.skipTest('symlinks unavailable on this Windows environment')
        _,meta=pair(self.root/'runtime/workbench/jobs/local/cache')
        metadata=self.root/'market_data/tdx/day/metadata/sh600000.json';metadata.parent.mkdir()
        metadata.write_bytes(meta.read_bytes())
        inventory=history.history_inventory(refresh=True)
        self.assertEqual(inventory['invalid_sources_count'],1)
        self.assertEqual(inventory['total'],1)

    def test_download_name_only_resolves_completed_export_receipts(self):
        pair(self.root/'market_data');result=history.create_export(scope='stock',symbol='sh600000')
        self.assertEqual(history.export_download_path(result['name']),Path(result['path']))
        for value in ('../settings.json',result['path'],'history-day-all-missing.zip'):
            with self.assertRaises(ValueError):history.export_download_path(value)

    def test_singleflight_same_scope_shares_one_export_and_returns_isolated_receipts(self):
        started=threading.Event();joined=threading.Event();release=threading.Event()
        class TrackingFuture(Future):
            def result(self,*args,**kwargs):
                if not self.done():joined.set()
                return super().result(*args,**kwargs)
        def create(*args):
            started.set();self.assertTrue(release.wait(3));return {'coverage':{'pairs':1}}
        with patch.object(history,'Future',TrackingFuture),patch.object(history,'_create',side_effect=create) as build:
            with ThreadPoolExecutor(max_workers=2) as pool:
                a=pool.submit(history.create_export);self.assertTrue(started.wait(2))
                b=pool.submit(history.create_export)
                try:self.assertTrue(joined.wait(2))
                finally:release.set()
                one,two=a.result(3),b.result(3)
        self.assertEqual(build.call_count,1)
        one['coverage']['pairs']=2;self.assertEqual(two['coverage']['pairs'],1)


if __name__=='__main__':unittest.main()
