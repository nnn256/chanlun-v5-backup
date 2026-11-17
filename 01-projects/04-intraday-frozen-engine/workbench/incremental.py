"""Authenticated engine snapshots with append-only closed-bar recovery."""
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import gzip
import hashlib
import hmac
import io
import json
import os
import secrets
import threading

from chanmodel.model import Candle
from chanmodel.reference_engine import PROFILE, COMMIT, SETTINGS, ReferenceSession, verify_engine
from chanmodel.object_graph import graph_dumps, graph_loads
from chanmodel.tdx_data import atomic_bytes
from .store import STATE

SCHEMA = 4
JSON_SCHEMA = 3
LEGACY_SCHEMA = 1
MAGIC = b'CHJ7'
JSON_MAGIC = b'CHJ6'
PICKLE_MAGIC = b'CHJ5'
LEGACY_MAGIC = b'CHJ4'
OLDER_PICKLE_MAGIC = b'CHS4'
MAX_CHECKPOINT_BYTES = 256 * 1024 * 1024
MAX_JOURNAL_BYTES = 16 * 1024 * 1024
CHECKPOINT_EVERY = 128
SESSION_CACHE_LIMIT = int(os.environ.get('CHANLUN_SESSION_CACHE_SIZE', '32'))
if not 8 <= SESSION_CACHE_LIMIT <= 256:
    raise ValueError('CHANLUN_SESSION_CACHE_SIZE must be between 8 and 256 sessions')
ROOT = STATE / 'live-sessions'
MEMORY = OrderedDict()
MEMORY_LOCK = threading.RLock()
KEY_LOCK = threading.Lock()
KEY_LOCKS = {}


def settings_fingerprint(period):
    value = {'profile': PROFILE, 'commit': COMMIT, 'settings': SETTINGS,
             'period': period, 'adjustment': 'unadjusted'}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _key():
    path = ROOT / 'checkpoint.key'
    with KEY_LOCK:
        if path.exists():
            key = path.read_bytes()
            if len(key) != 32:
                raise ValueError('live session checkpoint key is invalid')
            return key
        key = secrets.token_bytes(32)
        atomic_bytes(path, key)
        return key


def _identity_lock(identity):
    with MEMORY_LOCK:
        return KEY_LOCKS.setdefault(identity, threading.RLock())


@dataclass
class LiveSession:
    session: ReferenceSession
    saved_count: int = 0
    revisions: int = 0
    last_full_audit: float = 0.0
    journal_count: int = 0
    needs_migration: bool = False
    last_load_source: str = 'new'


def _checkpoint_path(symbol, period):
    return ROOT / symbol / period / 'session.bin'


def _journal_path(symbol, period):
    return ROOT / symbol / period / 'session.wal'


def _public_state(session):
    return {'bars': [[b.pos, b.open, b.high, b.low, b.close, b.closed_at, b.volume, b.closed] for b in session.bars],
            'registry': session.registry, 'events': session.events,
            'structural_first': [[list(key), value] for key, value in sorted(session.structural_first.items())]}


def _restore_legacy_state(state, period):
    session = ReferenceSession(period, observe=True)
    for row in state['bars']:
        if not isinstance(row, list) or len(row) != 8:
            raise ValueError('invalid legacy live bar checkpoint row')
        position, open_, high, low, close, closed_at, volume, closed = row
        session.append(Candle(position, open_, high, low, close, closed_at, volume, closed))
    if session.registry != state.get('registry') or session.events != state.get('events'):
        raise ValueError('replayed legacy live session event ledger differs from checkpoint')
    expected = {tuple(row[0]): row[1] for row in state.get('structural_first', [])}
    if session.structural_first != expected:
        raise ValueError('replayed legacy live session confirmation ledger differs from checkpoint')
    return session


def _validate_session(session, period, count):
    if not isinstance(session, ReferenceSession) or session.period != period or not session.observe:
        raise ValueError('live engine snapshot type/period mismatch')
    if session.closed_count != count or len(session.bars) != count:
        raise ValueError('live engine snapshot count mismatch')
    if any(not bar.closed or bar.pos != index for index, bar in enumerate(session.bars)):
        raise ValueError('live engine snapshot bars are not a closed contiguous prefix')


def _bar_row(bar):
    return [bar.pos, bar.open, bar.high, bar.low, bar.close, bar.closed_at, bar.volume, bar.closed]


def _bar_from_row(row):
    if not isinstance(row, list) or len(row) != 8:
        raise ValueError('invalid live journal bar row')
    position, open_, high, low, close, closed_at, volume, closed = row
    if type(position) is not int or type(closed) is not bool:
        raise ValueError('invalid live journal bar identity')
    return Candle(position, open_, high, low, close, closed_at, volume, closed)


def _journal_record(symbol, period, bar, key):
    record = {'schema': 1, 'symbol': symbol, 'period': period, 'bar': _bar_row(bar)}
    body = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    signature = hmac.new(key, b'WAL1' + body, hashlib.sha256).hexdigest()
    return json.dumps({'record': record, 'hmac': signature}, ensure_ascii=False,
                      allow_nan=False, separators=(',', ':')).encode('utf-8') + b'\n'


def _replay_journal(path, symbol, period, session):
    if not path.exists():
        return 0
    raw = path.read_bytes()
    if len(raw) > MAX_JOURNAL_BYTES:
        raise ValueError('live session journal exceeds size limit')
    complete_end = raw.rfind(b'\n') + 1
    if complete_end < len(raw):
        atomic_bytes(path, raw[:complete_end])
        raw = raw[:complete_end]
    if not raw:
        return 0
    key = _key()
    appended = 0
    expected_position = None
    for line in raw.splitlines():
        try:
            envelope = json.loads(line)
            record = envelope['record']
            body = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
            expected_hmac = hmac.new(key, b'WAL1' + body, hashlib.sha256).hexdigest()
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            raise ValueError('live session journal record is invalid') from exc
        if not hmac.compare_digest(str(envelope.get('hmac', '')), expected_hmac):
            raise ValueError('live session journal authentication failed')
        if record.get('schema') != 1 or record.get('symbol') != symbol or record.get('period') != period:
            raise ValueError('live session journal provenance mismatch')
        bar = _bar_from_row(record.get('bar'))
        if expected_position is not None and bar.pos != expected_position:
            raise ValueError('live session journal positions are discontinuous')
        expected_position = bar.pos + 1
        if bar.pos < session.closed_count:
            if _bar_row(session.bars[bar.pos]) != _bar_row(bar):
                raise ValueError('journal conflicts with its engine snapshot')
            continue
        if bar.pos != session.closed_count:
            raise ValueError('live session journal does not continue the engine snapshot')
        session.append(bar)
        appended += 1
    return appended


def get(symbol, period):
    identity = (symbol, period)
    with MEMORY_LOCK:
        value = MEMORY.get(identity)
        if value is not None:
            MEMORY.move_to_end(identity)
            value.last_load_source = 'memory'
            return value, True
    lock = _identity_lock(identity)
    with lock:
        with MEMORY_LOCK:
            value = MEMORY.get(identity)
            if value is not None:
                MEMORY.move_to_end(identity)
                value.last_load_source = 'memory'
                return value, True
        verify_engine()
        path = _checkpoint_path(symbol, period)
        journal_path = _journal_path(symbol, period)
        if not path.exists():
            if journal_path.exists() and journal_path.stat().st_size:
                raise ValueError('orphaned live session journal has no engine snapshot')
            value = LiveSession(ReferenceSession(period, observe=True))
            value.last_load_source = 'new'
            restored = False
        else:
            raw = path.read_bytes()
            if not 36 <= len(raw) <= MAX_CHECKPOINT_BYTES or raw[:4] not in {MAGIC, JSON_MAGIC, PICKLE_MAGIC, LEGACY_MAGIC, OLDER_PICKLE_MAGIC}:
                raise ValueError('live session checkpoint header/size invalid')
            signature, packed = raw[4:36], raw[36:]
            if not hmac.compare_digest(signature, hmac.new(_key(), packed, hashlib.sha256).digest()):
                raise ValueError('live session checkpoint authentication failed')
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(packed),mode='rb') as stream:
                    decoded=stream.read(MAX_CHECKPOINT_BYTES+1)
                if len(decoded)>MAX_CHECKPOINT_BYTES:raise ValueError('live session checkpoint decompressed size exceeds limit')
                if raw[:4] == MAGIC:
                    state = graph_loads(decoded, max_bytes=MAX_CHECKPOINT_BYTES)
                    expected = {'schema': SCHEMA, 'symbol': symbol, 'period': period, 'profile': PROFILE,
                                'commit': COMMIT, 'settings_fingerprint': settings_fingerprint(period)}
                    if state.get('metadata') != expected:
                        raise ValueError('live session checkpoint provenance mismatch')
                    session = state.get('session')
                    value = LiveSession(session, int(state['saved_count']), int(state['revisions']),
                                        float(state['last_full_audit']))
                    value.last_load_source = 'checkpoint'
                    _validate_session(session, period, value.saved_count)
                elif raw[:4] in {PICKLE_MAGIC, OLDER_PICKLE_MAGIC}:
                    raise ValueError('legacy recursive-object checkpoint quarantined for raw-history rebootstrap')
                elif raw[:4] == JSON_MAGIC:
                    state = json.loads(decoded)
                    expected = {'schema': JSON_SCHEMA, 'symbol': symbol, 'period': period, 'profile': PROFILE,
                                'commit': COMMIT, 'settings_fingerprint': settings_fingerprint(period)}
                    if state.get('metadata') != expected:
                        raise ValueError('legacy JSON checkpoint provenance mismatch')
                    session = _restore_legacy_state(state, period)
                    value = LiveSession(session, int(state['saved_count']), int(state['revisions']),
                                        float(state['last_full_audit']), needs_migration=True)
                    value.last_load_source = 'checkpoint'
                    _validate_session(session, period, value.saved_count)
                elif raw[:4] == LEGACY_MAGIC:
                    state = json.loads(decoded)
                    expected = {'schema': LEGACY_SCHEMA, 'symbol': symbol, 'period': period, 'profile': PROFILE,
                                'commit': COMMIT, 'settings_fingerprint': settings_fingerprint(period)}
                    if state.get('metadata') != expected:
                        raise ValueError('legacy live session checkpoint provenance mismatch')
                    session = _restore_legacy_state(state, period)
                    value = LiveSession(session, int(state['saved_count']), int(state['revisions']),
                                        float(state['last_full_audit']), needs_migration=True)
                    value.last_load_source = 'checkpoint'
                    _validate_session(session, period, value.saved_count)
            except (gzip.BadGzipFile, EOFError,RecursionError,OverflowError) as exc:
                raise ValueError('live session checkpoint payload is corrupt') from exc
            value.journal_count = _replay_journal(journal_path, symbol, period, value.session)
            value.saved_count = value.session.closed_count
            restored = True
        with MEMORY_LOCK:
            MEMORY[identity] = value
            MEMORY.move_to_end(identity)
            while len(MEMORY) > SESSION_CACHE_LIMIT:
                MEMORY.popitem(last=False)
        return value, restored


def quarantine(symbol, period, reason):
    paths = (_checkpoint_path(symbol, period), _journal_path(symbol, period))
    moved = []
    stamp = secrets.token_hex(4)
    for path in paths:
        if path.exists():
            target = path.with_name(path.name + '.quarantined-' + stamp)
            path.replace(target)
            moved.append(str(target.relative_to(STATE)))
    with MEMORY_LOCK:
        MEMORY.pop((symbol, period), None)
    if not moved:
        return None
    return {'state': 'checkpoint_rejected_and_quarantined', 'reason': reason, 'paths': moved}


def save(symbol, period, value):
    session = value.session
    if session.closed_count != len(session.bars):
        raise ValueError('live session has inconsistent bar count')
    metadata = {'schema': SCHEMA, 'symbol': symbol, 'period': period, 'profile': PROFILE,
                'commit': COMMIT, 'settings_fingerprint': settings_fingerprint(period)}
    payload = {'metadata': metadata, 'saved_count': session.closed_count,
               'revisions': value.revisions, 'last_full_audit': value.last_full_audit,
               'session': session}
    packed = gzip.compress(graph_dumps(payload), compresslevel=3, mtime=0)
    if len(packed) > MAX_CHECKPOINT_BYTES:
        raise ValueError('live session checkpoint exceeds size limit')
    signature = hmac.new(_key(), packed, hashlib.sha256).digest()
    atomic_bytes(_checkpoint_path(symbol, period), MAGIC + signature + packed)
    atomic_bytes(_journal_path(symbol, period), b'')
    value.saved_count = session.closed_count
    value.journal_count = 0
    value.needs_migration = False
    value.last_load_source = 'memory'
    with MEMORY_LOCK:
        MEMORY[(symbol, period)] = value
        MEMORY.move_to_end((symbol, period))
    return hashlib.sha256(packed).hexdigest()


def append_journal(symbol, period, value, bars):
    bars = tuple(bars)
    if not bars:
        return False
    if value.needs_migration:
        save(symbol, period, value)
        return False
    if value.saved_count != bars[0].pos or value.session.closed_count != bars[-1].pos + 1:
        raise ValueError('journal append does not continue the durable session')
    if any(bar.pos != bars[0].pos + index for index, bar in enumerate(bars)):
        raise ValueError('journal append bars are not contiguous')
    path = _journal_path(symbol, period)
    payload = b''.join(_journal_record(symbol, period, bar, _key()) for bar in bars)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    value.saved_count = value.session.closed_count
    value.journal_count += len(bars)
    with MEMORY_LOCK:
        MEMORY[(symbol, period)] = value
        MEMORY.move_to_end((symbol, period))
    return value.journal_count >= CHECKPOINT_EVERY or path.stat().st_size >= MAX_JOURNAL_BYTES


def clear_memory():
    with MEMORY_LOCK:
        MEMORY.clear()


def flush_all():
    with MEMORY_LOCK:
        items = list(MEMORY.items())
    results = {}
    for identity, value in items:
        with _identity_lock(identity):
            results[identity[0] + '|' + identity[1]] = save(*identity, value)
    return results
