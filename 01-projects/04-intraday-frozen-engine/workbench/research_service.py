"""One resident research state per symbol; append only new closed daily bars."""
from collections import OrderedDict
import copy
import hashlib
import json
import threading

from chanmodel.regime_research import RegimeSession

LOCK = threading.RLock()
KEY_LOCKS = {}
CACHE = OrderedDict()
MAX_SESSIONS = 16


def _signature(row):
    context={key:row[key] for key in ('context','net_flow','net_flow_yuan','up_count','down_count',
                                      'source','available_at','unit','scope') if key in row}
    return (tuple(row.get(key) for key in ('source_index','closed_at','open','high','low','close','volume')),
            json.dumps(context,sort_keys=True,allow_nan=False))


def _is_closed(row):
    value=row.get('is_closed',True)
    if value is True or type(value) is int and value==1:return True
    if value is False or type(value) is int and value==0:return False
    if isinstance(value,str) and value.strip().lower() in {'true','1'}:return True
    if isinstance(value,str) and value.strip().lower() in {'false','0'}:return False
    raise ValueError('daily K-line is_closed must be explicitly true or false')


def attach_research(panel, symbol, context=None):
    if panel.get('period') != 'day' or panel.get('kind') == 'line':
        return panel
    identity = str(symbol)
    with LOCK:
        mutex = KEY_LOCKS.setdefault(identity, threading.RLock())
    with mutex:
        source_rows=panel.get('bars',[])
        rows = [row for row in source_rows if _is_closed(row)]
        excluded_open_bars=len(source_rows)-len(rows)
        signatures = [_signature(row) for row in rows]
        context_hash = hashlib.sha256(json.dumps(context, sort_keys=True, allow_nan=False).encode()).hexdigest()
        with LOCK:
            prior = CACHE.get(identity)
        reused = bool(prior and prior['context_hash'] == context_hash and
                      len(prior['session'].series)==len(prior['signatures']) and
                      len(signatures) >= len(prior['signatures']) and
                      signatures[:len(prior['signatures'])] == prior['signatures'])
        session = prior['session'] if reused else RegimeSession(symbol=symbol, context=context)
        start = len(prior['signatures']) if reused else 0
        try:
            for row in rows[start:]:
                session.append(row)
            report = session.snapshot(include_series=False)
        except Exception:
            # A suffix can fail after several valid bars were appended. Never
            # retain a partly advanced engine beside the old prefix receipt.
            with LOCK:
                CACHE.pop(identity,None)
            raise
        # Calendar timestamps are attached at the API boundary; the engine's
        # observed_index always indexes its validated closed-bar prefix.
        compact = {key: value for key, value in report.items() if key != 'series'}
        compact['events'] = copy.deepcopy(report.get('events', []))
        compact['latest'] = copy.deepcopy(report.get('latest'))
        compact['provenance']['open_bar_excluded']=excluded_open_bars>0
        compact['runtime'] = {'session_reused': reused, 'new_closed_bars': len(rows) - start,
                              'closed_bars': len(rows),'forming_bars_excluded':excluded_open_bars,
                              'history_rebuild_reason': None if reused else 'cold_start_or_changed_history_or_context'}
        panel['regime_research'] = compact
        with LOCK:
            CACHE[identity] = {'session': session, 'signatures': signatures, 'context_hash': context_hash}
            CACHE.move_to_end(identity)
            while len(CACHE) > MAX_SESSIONS:
                CACHE.popitem(last=False)
    return panel


def attach_bundle(bundle):
    symbol = bundle.get('summary', {}).get('symbol', '')
    for panel in bundle.get('chart', {}).get('panels', []):
        attach_research(panel, symbol)
    return bundle
