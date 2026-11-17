"""Import a local history ZIP into a fresh discoverable cache, atomically.

ZIP members are data references, never extraction instructions. Only the
verified history-export schema is accepted; canonical cache paths are rebuilt
from each source's security and period rather than its ZIP member filename.
"""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import threading
import uuid
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from .store import ROOT, STATE
from . import history_archive as history

MAX_ZIP_BYTES = 9 * 1024**3
MAX_TOTAL_BYTES = 8 * 1024**3
MAX_MEMBER_BYTES = 512 * 1024**2
MAX_MANIFEST_BYTES = 32 * 1024**2
MAX_METADATA_BYTES = 1024**2
MAX_FILES = 100000
MAX_SOURCES = 30000
DISK_RESERVE_BYTES = 2 * 1024**3
LOCK = threading.Lock()
SHA = re.compile(r'[0-9a-f]{64}')
MEMBER = re.compile(r'tdx/(?:day|minute1|minute5|minute15|minute30|hour|week|month|quarter|year)/(?:ohlcv/(?:sh|sz|bj)\d{6}\.csv(?:\.gz)?|raw/(?:sh|sz|bj)\d{6}\.json\.gz|metadata/(?:sh|sz|bj)\d{6}\.json)')


def _safe(path):
    root = Path(ROOT).resolve();path = Path(path)
    resolved = path.resolve()
    if not resolved.is_relative_to(root):raise ValueError('history import destination leaves project directory')
    current = path.absolute()
    while current != root and current.is_relative_to(root):
        if current.is_symlink():raise ValueError('history import destination uses a linked directory')
        current = current.parent
    return resolved


def _digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):value.update(block)
    return value.hexdigest()


def _json(raw, label):
    try:value=json.loads(raw.decode('utf-8-sig'))
    except (ValueError,UnicodeError) as error:raise ValueError(label+' is not valid JSON') from error
    if not isinstance(value,dict):raise ValueError(label+' must be an object')
    return value


def _member_name(name):
    if not isinstance(name,str) or '\\' in name or '\x00' in name or ':' in name:
        raise ValueError('unsafe ZIP member name')
    path=PurePosixPath(name)
    if path.is_absolute() or any(part in {'','.','..'} for part in name.split('/')):
        raise ValueError('unsafe ZIP member path')
    if name!='manifest.json' and not MEMBER.fullmatch(name):raise ValueError('ZIP contains a non-history member')
    return name


def _manifest(archive):
    infos=archive.infolist()
    if not infos or len(infos)>MAX_FILES+1:raise ValueError('history ZIP member count exceeds budget')
    names={};folded=set();total=0
    for info in infos:
        name=_member_name(info.filename)
        if info.is_dir() or name.casefold() in folded:raise ValueError('history ZIP has duplicate or directory members')
        if stat.S_ISLNK(info.external_attr>>16) or info.flag_bits&1:
            raise ValueError('linked or encrypted ZIP members are not supported')
        if info.compress_type not in {ZIP_STORED,ZIP_DEFLATED}:raise ValueError('unsupported history ZIP compression')
        limit=MAX_MANIFEST_BYTES if name=='manifest.json' else MAX_METADATA_BYTES if '/metadata/' in name else MAX_MEMBER_BYTES
        if info.file_size<0 or info.file_size>limit:raise ValueError('history ZIP member exceeds size budget')
        names[name]=info;folded.add(name.casefold());total+=info.file_size
    if total>MAX_TOTAL_BYTES+MAX_MANIFEST_BYTES:raise ValueError('history ZIP expanded content exceeds budget')
    if 'manifest.json' not in names:raise ValueError('history ZIP has no manifest.json')
    value=_json(archive.read('manifest.json'),'history manifest')
    if value.get('schema')!='verified_local_history_zip_v1':raise ValueError('unsupported history ZIP schema')
    files=value.get('files');sources=value.get('sources')
    if not isinstance(files,list) or not files or len(files)>MAX_FILES:raise ValueError('history manifest files are invalid')
    if not isinstance(sources,list) or not sources or len(sources)>MAX_SOURCES:raise ValueError('history manifest sources are invalid')
    indexed={}
    for entry in files:
        if not isinstance(entry,dict):raise ValueError('history file manifest entry is invalid')
        name=_member_name(entry.get('path'))
        if name=='manifest.json' or name in indexed or name not in names:raise ValueError('history file manifest membership differs')
        if not isinstance(entry.get('sha256'),str) or not SHA.fullmatch(entry['sha256']):raise ValueError('history member SHA-256 is missing')
        if type(entry.get('bytes')) is not int or entry['bytes']!=names[name].file_size:
            raise ValueError('history member size differs from manifest')
        indexed[name]=entry
    if set(indexed)!=(set(names)-{'manifest.json'}):raise ValueError('ZIP members differ from the allowed history manifest')
    pairs=set();referenced=set();canonical_bytes=0;normalized=[]
    for source in sources:
        if not isinstance(source,dict):raise ValueError('history source entry is invalid')
        code=source.get('symbol');period=history._period(source.get('period'))
        history._symbol(code)
        if code is None or period=='all' or (code,period) in pairs:raise ValueError('duplicate or invalid history source identity')
        pairs.add((code,period))
        item={**source,'symbol':code,'period':period}
        for kind,key in [('ohlcv','csv_path'),('metadata','metadata_path'),('raw','raw_path')]:
            path=source.get(key)
            if kind=='raw' and path is None:continue
            if path not in indexed or '/'+kind+'/' not in path:raise ValueError('history source refers to an unlisted or wrong-kind member')
            referenced.add(path);canonical_bytes+=indexed[path]['bytes']
        if not isinstance(source.get('coverage'),dict):raise ValueError('history source coverage is missing')
        normalized.append(item)
    if referenced!=set(indexed):raise ValueError('history manifest contains unreferenced data members')
    if canonical_bytes>MAX_TOTAL_BYTES:raise ValueError('canonical imported files exceed disk budget after deduplication expansion')
    if value.get('exported_pairs')!=len(sources):raise ValueError('exported source count differs from history manifest')
    return value,indexed,normalized,canonical_bytes


def _copy_member(archive,name,entry,dest):
    dest.parent.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256();count=0
    with archive.open(name) as source,dest.open('xb') as target:
        for block in iter(lambda:source.read(1024**2),b''):
            count+=len(block)
            if count>entry['bytes']:raise ValueError('history member exceeds declared size while streaming')
            digest.update(block);target.write(block)
    if count!=entry['bytes'] or digest.hexdigest()!=entry['sha256']:
        raise ValueError('history ZIP member SHA-256 or size differs from manifest')


def _metadata(raw,source,csv_path,raw_path,final_csv,final_raw,archive_meta_sha):
    meta=_json(raw,'source metadata');code=source['symbol'];period=source['period']
    declared=meta.get('period',(meta.get('provider_meta') or {}).get('type','day'))
    if (meta.get('symbol')!=code or history._period(declared)!=period or meta.get('source')!='tdx' or
            meta.get('adjustment')!='unadjusted'):
        raise ValueError('history source metadata security/period/provider differs')
    if meta.get('csv_path')!=source['csv_path'] or meta.get('raw_path')!=source.get('raw_path'):
        raise ValueError('history source metadata paths differ from manifest references')
    checksum=meta.get('csv_sha256')
    if not isinstance(checksum,str) or not SHA.fullmatch(checksum):raise ValueError('history metadata CSV checksum is invalid')
    closed=meta.get('closed_rows')
    if type(closed) is not int or closed<=0:raise ValueError('history metadata has invalid closed row count')
    first=history._time(meta.get('first_close'));last=history._time(meta.get('last_close'))
    first_date=history._date(meta.get('first_date'));last_date=history._date(meta.get('last_date'))
    if (first is None and first_date is None) or (last is None and last_date is None):raise ValueError('history metadata coverage dates are invalid')
    result={'symbol':code,'period':history.PERIODS[period],'source':'tdx','adjustment':'unadjusted',
        'csv_path':str(final_csv),'csv_sha256':checksum,'closed_rows':closed,
        'first_date':first_date.isoformat() if first_date else first.date().isoformat(),
        'last_date':last_date.isoformat() if last_date else last.date().isoformat(),
        'first_close':first.isoformat() if first else first_date.isoformat()+'T15:00:00+08:00',
        'last_close':last.isoformat() if last else last_date.isoformat()+'T15:00:00+08:00',
        'history_import_schema':'verified_local_history_import_v1','archive_metadata_sha256':archive_meta_sha,
        'identity_provenance':'imported local archive with matching content hashes; upstream authenticity not independently certified',
        'coverage_claim':'complete imported saved file; listing-inception and missing-session absence unproved'}
    for key in ('price_unit','volume_unit','original_volume_unit','amount_unit','session_timezone','normalization_schema'):
        value=meta.get(key)
        if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_+. /:-]{1,100}',value):result[key]=value
    for key in ('requested_at','received_at','as_of','cache_run_as_of'):
        if history._time(meta.get(key)) is not None:result[key]=meta[key]
    original=meta.get('original_metadata_sha256')
    if isinstance(original,str) and SHA.fullmatch(original):result['original_metadata_sha256']=original
    if csv_path.suffix=='.gz':result.update(csv_compression='gzip',csv_storage_sha256=_digest(csv_path))
    if raw_path is not None:
        expected=meta.get('raw_storage_sha256');response=meta.get('response_sha256')
        if not isinstance(expected,str) or not SHA.fullmatch(expected) or _digest(raw_path)!=expected:
            raise ValueError('raw provider storage hash differs from imported metadata')
        if not isinstance(response,str) or not SHA.fullmatch(response):raise ValueError('raw provider response SHA is missing')
        result.update(raw_path=str(final_raw),raw_storage_sha256=expected,response_sha256=response)
    return result


def import_history_archive(path,*,progress=None):
    """Import one explicitly selected local ZIP into a fresh canonical job cache.

    The returned path is discoverable by existing history source resolution.
    Existing market_data, task outputs and databases are never overwritten.
    """
    source=Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower()!='.zip':raise ValueError('select an existing local history ZIP')
    if not 0<source.stat().st_size<=MAX_ZIP_BYTES:raise ValueError('history ZIP size exceeds import budget')
    # A process-wide import lock prevents competing desktop launch requests
    # from duplicating an in-progress import or its disk reservation.
    with LOCK:
        source_hash=_digest(source)
        state=_safe(STATE);index_dir=_safe(state/'history-imports')
        index_path=index_dir/(source_hash+'.json')
        if index_path.is_file():
            prior=_json(index_path.read_bytes(),'history import receipt')
            ident=prior.get('id','')
            if re.fullmatch(r'\d{8}T\d{6}-[a-f0-9]{12}',ident):
                job=_safe(state/'jobs'/('import-history-'+ident))
                marker=job/'history-import-receipt.json'
                if (job/'cache/tdx').is_dir() and marker.is_file() and prior.get('source_zip_sha256')==source_hash:
                    saved=_json(marker.read_bytes(),'history import marker')
                    if saved.get('source_zip_sha256')==source_hash and saved.get('id')==ident:
                        return {**saved,'reused':True}
        with ZipFile(source) as archive:
            manifest,indexed,sources,estimated=_manifest(archive)
            existing=state if state.exists() else Path(ROOT).resolve()
            if shutil.disk_usage(existing).free<estimated+DISK_RESERVE_BYTES:
                raise ValueError('not enough free disk for canonical history import and 2GiB reserve')
            ident=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-')+uuid.uuid4().hex[:12]
            parent=_safe(state/'jobs');final=_safe(parent/('import-history-'+ident))
            staging_parent=_safe(state/'history-imports-staging');staging_parent.mkdir(parents=True,exist_ok=True)
            staging=_safe(staging_parent/ident);staging.mkdir(exist_ok=False)
            final_cache=final/'cache';cache=staging/'cache';records=[];verified=set();canonical_bytes=0
            try:
                for offset,item in enumerate(sources):
                    code=item['symbol'];period=item['period'];folder=cache/'tdx'/history.PERIODS[period]
                    final_folder=final_cache/'tdx'/history.PERIODS[period]
                    suffix='.csv' if period=='day' else '.csv.gz'
                    csv_path=folder/'ohlcv'/(code+suffix)
                    member=item['csv_path'];entry=indexed[member]
                    transcoding=not (member.endswith(suffix) and (suffix!='.csv' or not member.endswith('.gz')))
                    # A compressed daily input may expand during canonical
                    # conversion; reserve its bounded worst case before write.
                    required=(MAX_MEMBER_BYTES+entry['bytes'] if transcoding else entry['bytes'])
                    required+=indexed[item['metadata_path']]['bytes']+indexed.get(item.get('raw_path'),{}).get('bytes',0)
                    if shutil.disk_usage(staging).free<DISK_RESERVE_BYTES+required:
                        raise ValueError('free disk fell below the next source write and import reserve')
                    if member.endswith(suffix) and (suffix!='.csv' or not member.endswith('.gz')):
                        _copy_member(archive,member,entry,csv_path)
                    else:
                        incoming=staging/'temporary-members'/(uuid.uuid4().hex+('.csv.gz' if member.endswith('.gz') else '.csv'))
                        _copy_member(archive,member,entry,incoming)
                        csv_path.parent.mkdir(parents=True,exist_ok=True)
                        source_open=gzip.open if incoming.suffix=='.gz' else open
                        target_open=gzip.open if csv_path.suffix=='.gz' else open
                        total=0
                        with source_open(incoming,'rb') as inp,target_open(csv_path,'wb') as out:
                            for block in iter(lambda:inp.read(1024**2),b''):
                                total+=len(block)
                                if total>MAX_MEMBER_BYTES:raise ValueError('expanded canonical CSV exceeds size budget')
                                out.write(block)
                        incoming.unlink()
                    verified.add(member)
                    raw_path=None;raw_name=item.get('raw_path')
                    if raw_name is not None:
                        raw_path=folder/'raw'/(code+'.json.gz');_copy_member(archive,raw_name,indexed[raw_name],raw_path);verified.add(raw_name)
                    meta_name=item['metadata_path'];raw=archive.read(meta_name)
                    if len(raw)!=indexed[meta_name]['bytes'] or hashlib.sha256(raw).hexdigest()!=indexed[meta_name]['sha256']:
                        raise ValueError('history metadata member checksum mismatch')
                    verified.add(meta_name)
                    meta=_metadata(raw,item,csv_path,raw_path,final_folder/'ohlcv'/csv_path.name,
                        final_folder/'raw'/(code+'.json.gz'),indexed[meta_name]['sha256'])
                    meta_path=folder/'metadata'/(code+'.json');meta_path.parent.mkdir(parents=True,exist_ok=True)
                    meta_path.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
                    # Use the same streaming row/hash verifier as export, but
                    # pass explicit staging paths because publish is atomic.
                    candidate={'symbol':code,'period':period,'csv_path':csv_path,'metadata':meta,
                        'csv_sha256':meta['csv_sha256'],'closed_rows':meta['closed_rows'],
                        'first':meta['first_date'] if period=='day' else meta['first_close'],
                        'last':meta['last_date'] if period=='day' else meta['last_close'],
                        'raw_path':raw_path}
                    coverage,raw_info=history._verify(candidate)
                    for key in ('rows','closed_rows','forming_rows'):
                        if item['coverage'].get(key)!=coverage[key]:raise ValueError('imported CSV coverage differs from source manifest')
                    canonical_bytes+=csv_path.stat().st_size+meta_path.stat().st_size+(raw_path.stat().st_size if raw_path else 0)
                    if canonical_bytes>MAX_TOTAL_BYTES:raise ValueError('canonical imported files exceeded budget')
                    records.append({'symbol':code,'period':period,'coverage':coverage,
                        'csv_sha256':coverage['csv_sha256'],'csv_storage_sha256':coverage['stored_sha256'],
                        'metadata_sha256':_digest(meta_path),'raw_storage_sha256':raw_info['stored_sha256'] if raw_info else None,
                        'raw_response_sha256':raw_info['response_sha256'] if raw_info else None})
                    if progress:progress({'processed':offset+1,'total':len(sources),'symbol':code,'period':period})
                if verified!=set(indexed):raise ValueError('not all manifest files were verified')
                if _digest(source)!=source_hash:raise ValueError('history ZIP changed during import')
                temporary=staging/'temporary-members'
                if temporary.exists():temporary.rmdir()
                receipt={'schema':'verified_local_history_import_v1','state':'ready','id':ident,
                    'cache_root':str(final_cache),'job_root':str(final),'pairs':len(records),'files':len(indexed),
                    'canonical_bytes':canonical_bytes,'closed_rows':sum(r['coverage']['closed_rows'] for r in records),
                    'securities':len({r['symbol'] for r in records}),'source_zip_sha256':source_hash,
                    'source_zip_name':source.name,'imported_at':datetime.now(timezone.utc).isoformat(),
                    'original_exported_pairs':manifest['exported_pairs'],'records':records,
                    'receipt_path':str(final/'history-import-receipt.json'),'network_used':False,
                    'algorithm_calculated':False,'reused':False,
                    'scope':'new local task cache; original files and existing tasks retained',
                    'provider_authenticity_proven':False}
                encoded=json.dumps(receipt,ensure_ascii=False,indent=2).encode()
                (staging/'history-import-receipt.json').write_bytes(encoded)
                parent.mkdir(parents=True,exist_ok=True)
                if final.exists():raise ValueError('history import target already exists')
                staging.rename(final)
                index_dir.mkdir(parents=True,exist_ok=True)
                temporary_index=index_path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
                temporary_index.write_bytes(encoded);temporary_index.replace(index_path)
                return receipt
            except BaseException:
                # Only this fresh staging path may be removed. Published task
                # caches are retained even if writing the optional index fails.
                if staging.exists():shutil.rmtree(_safe(staging))
                raise
