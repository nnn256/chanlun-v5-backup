"""Send fresh runtime metadata when a client's complete chart is unchanged."""
import hashlib
import json
import re


PANEL_UPDATE_FIELDS=(
    'period','presentation_sha256','observed_at','received_at','confirmed_through',
    'latest_bar_at','forming_count','source_receipt','coverage','live_session','note',
    'presentation_reused',
)
_SHA=re.compile(r'[0-9a-f]{64}')


def snapshot_id(value):
    symbol=value.get('summary',{}).get('symbol')
    panels=value.get('chart',{}).get('panels')
    if not value.get('available') or not isinstance(symbol,str) or not panels:
        return None
    pairs=[];seen=set()
    for panel in panels:
        period=panel.get('period');identity=panel.get('presentation_sha256')
        if (not isinstance(period,str) or period in seen or
                not isinstance(identity,str) or not _SHA.fullmatch(identity)):
            return None
        seen.add(period);pairs.append((period,identity))
    raw=json.dumps(['live-delivery-v1',symbol,pairs],separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()


def snapshot_response(value,known_snapshot=None,*,full=False):
    """Compare only after this request obtained and validated current data.

    The token identifies the complete candle/structure presentation, not the
    acquisition timestamp. Matching replies still carry this request's source
    receipts and session metadata; full exports always retain all evidence.
    """
    identity=snapshot_id(value)
    if identity is None:return value
    if full or known_snapshot!=identity:
        return {**value,'snapshot_id':identity}
    chart=value['chart'];updates=[]
    for panel in chart['panels']:
        update={name:panel.get(name) for name in PANEL_UPDATE_FIELDS}
        research=panel.get('regime_research')
        if research is not None:
            update['research_runtime']=research.get('runtime')
            update['research_provenance']=research.get('provenance')
        updates.append(update)
    return {'available':True,'unchanged':True,'snapshot_id':identity,
            'summary':value['summary'],
            'chart_metadata':{name:item for name,item in chart.items() if name!='panels'},
            'panel_updates':updates}
