"""Pinned MIT chan.py adapter, raw OHLC provenance and observed signal ledger.

The upstream algorithm and its options are named in every output. No claim of
universal original-Chan equivalence is inferred from agreement with this engine.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime,timezone,timedelta
import hashlib
import json
from pathlib import Path
import sys
import threading
import math
from array import array

VENDOR=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'third_party/chanpy'
if str(VENDOR) not in sys.path:sys.path.insert(0,str(VENDOR))
from ChanConfig import CChanConfig
from Common.CEnum import DATA_FIELD,KL_TYPE,FX_TYPE
from Common.CTime import CTime
from KLine.KLine_List import CKLine_List
from KLine.KLine_Unit import CKLine_Unit

from .model import time_value

PROFILE='chanpy_feature_sequence_strict_pinned_v1'
COMMIT='f8ca3b5e44d7166e2abd756a8e7fa816c79faebe'
SETTINGS={'trigger_step':True,'bi_strict':True,'bi_fx_check':'strict',
          'bi_end_is_peak':True,'bi_allow_sub_peak':False,'gap_as_kl':False,
          'seg_algo':'chan','left_seg_method':'peak','zs_algo':'normal','zs_combine':True,
          'one_bi_zs':False,'divergence_rate':1.0,'min_zs_cnt':1,'bsp3_follow_1':False,
          'strict_bsp3':True,'bs_type':'1,1p,2,2s,3a,3b','print_warning':False}
CN=timezone(timedelta(hours=8))
_HASH_LOCK=threading.Lock();_CHECKED=False


def verify_engine():
    global _CHECKED
    if _CHECKED:return
    with _HASH_LOCK:
        receipt=json.loads((VENDOR/'provenance.json').read_text(encoding='utf-8'))
        if receipt['commit']!=COMMIT:raise ValueError('reference engine commit mismatch')
        for name,digest in receipt['files'].items():
            if hashlib.sha256((VENDOR/name).read_bytes()).hexdigest()!=digest:
                raise ValueError('reference engine source hash mismatch: '+name)
        _CHECKED=True


def local_time(bars,index):return time_value(bars[index].closed_at).astimezone(CN).isoformat()


def native_objects(engine):
    for rank,collection in [(1,engine.bs_point_lst),(2,engine.seg_bs_point_lst)]:
        for point in collection.bsp_iter():
            yield rank,point


PERIOD_MAP={'1m':KL_TYPE.K_1M,'5m':KL_TYPE.K_5M,'15m':KL_TYPE.K_15M,'30m':KL_TYPE.K_30M,
            '60m':KL_TYPE.K_60M,'day':KL_TYPE.K_DAY,'week':KL_TYPE.K_WEEK,'month':KL_TYPE.K_MON,
            'quarter':KL_TYPE.K_QUARTER,'year':KL_TYPE.K_YEAR,'5d':KL_TYPE.K_DAY}


class _ExtremaIndex:
    """Append-only range extrema index for logarithmic historical invalidation checks."""
    def __init__(self):
        self.size=0;self.capacity=1
        self.minimum=array('d',[math.inf])*2
        self.maximum=array('d',[-math.inf])*2

    def append(self,low,high):
        if self.size==self.capacity:
            self.capacity*=2
            old_min=self.minimum;old_max=self.maximum
            self.minimum=array('d',[math.inf])*(self.capacity*2)
            self.maximum=array('d',[-math.inf])*(self.capacity*2)
            for index in range(self.size):
                self.minimum[self.capacity+index]=old_min[(self.capacity//2)+index]
                self.maximum[self.capacity+index]=old_max[(self.capacity//2)+index]
            for index in range(self.capacity-1,0,-1):
                self.minimum[index]=min(self.minimum[index*2],self.minimum[index*2+1])
                self.maximum[index]=max(self.maximum[index*2],self.maximum[index*2+1])
        node=self.capacity+self.size;self.minimum[node]=low;self.maximum[node]=high
        node//=2
        while node:
            self.minimum[node]=min(self.minimum[node*2],self.minimum[node*2+1])
            self.maximum[node]=max(self.maximum[node*2],self.maximum[node*2+1])
            node//=2
        self.size+=1

    def first_crossing(self,start,boundary,side):
        if start>=self.size:return None
        def visit(node,left,right):
            if right<=start or left>=self.size:return None
            if side=='buy' and self.minimum[node]>=boundary:return None
            if side=='sell' and self.maximum[node]<=boundary:return None
            if right-left==1:return left
            middle=(left+right)//2
            found=visit(node*2,left,middle)
            return found if found is not None else visit(node*2+1,middle,right)
        return visit(1,0,self.capacity)


class ReferenceSession:
    """Stateful fixed-engine session. A closed candle is admitted exactly once."""
    def __init__(self,period='day',observe=True):
        verify_engine()
        if period not in PERIOD_MAP:raise ValueError('unsupported native reference period: '+period)
        self.period=period;self.observe=bool(observe)
        self.engine=CKLine_List(PERIOD_MAP[period],CChanConfig({**SETTINGS,'trigger_step':self.observe}))
        self.bars=[];self.registry={};self.events=[];self.structural_first={};self.previous=None
        self.extrema=_ExtremaIndex()

    @property
    def closed_count(self):return len(self.bars)

    @property
    def last_closed_at(self):return self.bars[-1].closed_at if self.bars else None

    def append(self,bar):
        index=len(self.bars)
        if not bar.closed:raise ValueError('forming candles cannot enter the confirmed reference engine')
        if bar.pos!=index:raise ValueError(f'append position {bar.pos} must equal next engine position {index}')
        if self.bars and time_value(bar.closed_at)<=time_value(self.bars[-1].closed_at):
            raise ValueError('incremental candle close times must strictly increase')
        self.bars.append(bar);self.extrema.append(bar.low,bar.high)
        d=time_value(bar.closed_at).astimezone(CN)
        klu=CKLine_Unit({DATA_FIELD.FIELD_TIME:CTime(d.year,d.month,d.day,d.hour,d.minute,auto=False),
                         DATA_FIELD.FIELD_OPEN:bar.open,DATA_FIELD.FIELD_HIGH:bar.high,
                         DATA_FIELD.FIELD_LOW:bar.low,DATA_FIELD.FIELD_CLOSE:bar.close,
                         DATA_FIELD.FIELD_VOLUME:bar.volume or 0})
        klu.set_idx(index)
        if self.previous:klu.set_pre_klu(self.previous)
        self.engine.add_single_klu(klu);self.previous=klu
        if not self.observe:return []
        present=set();added=[]
        for rank,point in native_objects(self.engine):
            for kind in point.type:
                ident=f'cp:{rank}:{kind.value}:{"buy" if point.is_buy else "sell"}:{point.klu.idx}'
                present.add(ident);sure=bool(point.bi.is_sure)
                signature=json.dumps({'begin':point.bi.get_begin_klu().idx,'end':point.klu.idx,'sure':sure,
                    'first_context':point.relate_bsp1.klu.idx if point.relate_bsp1 else None,
                    'features':dict(point.features.items())},sort_keys=True,allow_nan=False)
                old=self.registry.get(ident)
                if old is None or not old['active'] or old.get('signature')!=signature:
                    event='appeared' if old is None else 'reappeared' if not old['active'] else 'structure_completed' if sure and not old['sure'] else 'confirmation_withdrawn' if old['sure'] and not sure else 'revised'
                    record={'first_seen':old['first_seen'] if old else index,'observed':index,
                        'sure':sure,'active':True,'confirmed':index if sure else None,'signature':signature}
                    self.registry[ident]=record
                    item={'id':ident,'event':event,'observed_index':index,'observed_at':bar.closed_at,
                          'anchor':point.klu.idx,'native_type':kind.value,'rank':rank,
                          'side':'buy' if point.is_buy else 'sell','state':'structure_complete' if sure else 'candidate'}
                    self.events.append(item);added.append(item)
        for ident,old in self.registry.items():
            if old['active'] and ident not in present:
                old['active']=False;old['observed']=index
                item={'id':ident,'event':'withdrawn','observed_index':index,'observed_at':bar.closed_at}
                self.events.append(item);added.append(item)
        for label,collection in [('stroke',self.engine.bi_list),('segment',self.engine.seg_list),('segment2',self.engine.segseg_list)]:
            for obj in collection:
                if obj.is_sure:self.structural_first.setdefault((label,obj.get_begin_klu().idx,obj.get_end_klu().idx),index)
        return added

    def result_tuple(self):return self.engine,self.bars,self.registry,self.events,self.structural_first

    def snapshot(self,symbol,cutoff=None,source='tdx',adjustment='unadjusted',input_sha256=''):
        if not self.bars:raise ValueError('cannot snapshot an empty reference session')
        moment=cutoff or self.bars[-1].closed_at
        return make_report(*self.result_tuple(),symbol,self.period,moment,source,adjustment,input_sha256,
                           first_crossing=self.extrema.first_crossing)

    def invalidate(self,updated_bars):
        """Recompute surviving signal status against the append-only extrema index."""
        if len(updated_bars)!=len(self.bars):raise ValueError('invalidation bars/session length mismatch')
        for row in updated_bars:
            point=self.extrema.first_crossing(row['available_at']+1,row['invalidation'],row['side'])
            row['invalidated_at']=point
            if point is not None and row['state']!='needs_review':row['state']='invalidated'
        return updated_bars


def run_reference(bars,period='day',observe=True,as_of=None):
    if not bars:raise ValueError('reference engine requires observed raw candles')
    cutoff=time_value(as_of) if as_of else time_value(bars[-1].closed_at)
    closed=[bar for bar in bars if bar.closed and time_value(bar.closed_at)<=cutoff]
    if not closed:raise ValueError('no closed OHLC at cutoff')
    if any(bar.pos!=index for index,bar in enumerate(closed)):raise ValueError('raw indices not a closed prefix')
    session=ReferenceSession(period,observe)
    for bar in closed:session.append(bar)
    if not observe:session.engine.cal_seg_and_zs()
    return session.result_tuple()


def make_report(engine,bars,registry,events,structural_first,symbol,period,cutoff,source,adjustment,input_sha256,*,first_crossing=None):
    def move(obj,kind):
        a,b=obj.get_begin_klu().idx,obj.get_end_klu().idx
        known=structural_first.get((kind,a,b),len(bars)-1)
        evidence=None;native_fx=getattr(obj,'eigen_fx',None)
        if native_fx:
            evidence={'gap':bool(native_fx.ele[1].gap) if native_fx.ele[1] else None,
                      'last_evidence_native_index':native_fx.last_evidence_bi.idx if native_fx.last_evidence_bi else None,
                      'elements':[{'low':e.low,'high':e.high,'native_line_indices':[line.idx for line in e.lst]}
                                  for e in native_fx.ele if e is not None]}
        return {'id':f'cp:{kind}:{a}:{b}','start':a,'end':b,'direction':'up' if obj.is_up() else 'down',
                'start_price':obj.get_begin_val(),'end_price':obj.get_end_val(),'low':obj._low(),'high':obj._high(),
                'state':'confirmed' if obj.is_sure else 'provisional','basis_at':known,'available_at':known,
                'basis_closed':True,'engine':PROFILE,'native_index':obj.idx,'reason':getattr(obj,'reason',None),
                'confirmed_time':local_time(bars,known) if obj.is_sure else None,
                'native_eigen_evidence':evidence}
    strokes=[move(s,'stroke') for s in engine.bi_list]
    segments=[move(s,'segment') for s in engine.seg_list]
    higher=[move(s,'segment2') for s in engine.segseg_list]
    centers=[];layers=[]
    center_lookup={}
    for rank,collection in [(1,engine.zs_list),(2,engine.segzs_list)]:
        values=[]
        for z in collection:
            ident=f'cp:c{rank}:{z.begin.idx}:{z.end.idx}'
            c={'id':ident,'rank':rank,'start':z.begin.idx,'end':z.end.idx,'zd':z.low,'zg':z.high,
               'dd':z.peak_low,'gg':z.peak_high,'state':'formed' if z.is_sure else 'forming',
               'basis_at':len(bars)-1,'components':[f'cp:{"stroke" if rank==1 else "segment"}:{m.get_begin_klu().idx}:{m.get_end_klu().idx}' for m in z.bi_lst],
               'native_is_sure':z.is_sure,'member_count':len(z.bi_lst),'engine':PROFILE}
            values.append(c);centers.append(c);center_lookup[id(z)]=c
        completed=[{**m,'rank':rank,'kind':'native_segment','state':'complete','completed_at':m['basis_at']} for m in (segments if rank==1 else higher) if m['state']=='confirmed']
        layers.append({'rank':rank,'centers':values,'completed_types':completed,'comparisons':[],'signals':[],
                       'input_kind':'native_stroke' if rank==1 else 'native_segment','completion_profile':PROFILE,
                       'definition_mode':'pinned_native_feature_sequence'})
    labels={'1':('first','一类'),'1p':('first','盘整一类'),'2':('second','二类'),
            '2s':('second','二类延伸'),'3a':('third','三类A'),'3b':('third','三类B')}
    signals=[]
    for rank,p in native_objects(engine):
        side='buy' if p.is_buy else 'sell';anchor=p.klu.idx;price=p.klu.low if p.is_buy else p.klu.high
        parent=p.bi.parent_seg
        for native in p.type:
            near=None;center_proof=None
            collection=engine.zs_list if rank==1 else engine.segzs_list
            if native.value=='3a':
                # Upstream 3a is the first pullback immediately after this
                # named center's outgoing line; do not substitute a nearby box.
                candidates=[z for z in collection if z.bi_out and z.bi_out.idx+1==p.bi.idx]
                if len(candidates)==1:near=center_lookup.get(id(candidates[0]));center_proof='native_zs_bi_out_plus_one'
            elif native.value=='3b' and p.relate_bsp1:
                first_parent=p.relate_bsp1.bi.parent_seg
                z=first_parent.get_final_multi_bi_zs() if first_parent else None
                if z is not None:near=center_lookup.get(id(z));center_proof='related_first_point_segment_final_center'
            elif native.value=='1' and parent:
                z=parent.get_final_multi_bi_zs()
                if z is not None:near=center_lookup.get(id(z));center_proof='native_terminal_segment_final_center'
            prefix,label=labels[native.value];ident=f'cp:{rank}:{native.value}:{side}:{anchor}'
            record=registry.get(ident,{'first_seen':len(bars)-1,'observed':len(bars)-1,'confirmed':None})
            at=record['observed'];own_sure=bool(p.bi.is_sure)
            # Invalidation is a parent center boundary only when it is the
            # explicit third-point reference; otherwise the signal pivot.
            boundary=price
            operator='lt' if p.is_buy else 'gt'
            broken_index=(first_crossing(at+1,boundary,side) if first_crossing else None)
            broken=(bars[broken_index] if broken_index is not None else
                    next((b for b in bars[at+1:] if (b.low<boundary if p.is_buy else b.high>boundary)),None))
            state='invalidated' if broken else 'structure_complete' if own_sure else 'awaiting_lower_confirmation'
            start=p.bi.get_begin_klu().idx
            signal={'id':ident,'class':prefix+'_'+side,'label':label+('买' if p.is_buy else '卖'),
                    'native_type':native.value,'side':side,'rank':rank,'anchor':anchor,'price':price,
                    'terminal_range':[start,anchor],'available_at':at,'available_time':local_time(bars,at),
                    'first_seen_time':local_time(bars,record['first_seen']),
                    'confirmed_at':record['confirmed'],'confirmed_time':local_time(bars,record['confirmed']) if record['confirmed'] is not None else None,
                    'event_time':local_time(bars,anchor),'invalidation':boundary,'invalidation_operator':operator,
                    'invalidated_at':broken.pos if broken else None,'state':state,'native_is_sure':own_sure,
                    'invalidation_semantics':'native signal pivot broken after its observed availability; context center is not silently reused as stop',
                    'center_id':near['id'] if near else None,'zd':near['zd'] if near else None,'zg':near['zg'] if near else None,
                    'center_relation_proof':center_proof or 'not_uniquely_mapped; no nearby-center substitution',
                    'relate_bsp1_anchor':p.relate_bsp1.klu.idx if p.relate_bsp1 else None,
                    'features':dict(p.features.items()),'engine':PROFILE,'engine_commit':COMMIT,
                    'definition_mode':'pinned_native_rules','structure_scope':'native_stroke_points' if rank==1 else 'native_segment_points',
                    'lower_level_trigger':'not_proven','execution_allowed':False,
                    'rule_audit':{'passed':own_sure,'local_geometry_completed':own_sure,'evidence_available_at':record['confirmed'] or at,
                                  'missing':[] if own_sure else ['native_stroke_or_segment_is_provisional'],
                                  'scope':'native sure structure; cross-timeframe trigger not asserted'}}
            signals.append(signal);layers[rank-1]['signals'].append(signal)
    merged=[];fractals=[]
    for k in engine.lst:
        raw=k.lst;item={'id':f'cp:k:{raw[0].idx}:{raw[-1].idx}','index':k.idx,'start':raw[0].idx,'end':raw[-1].idx,
                       'high':k.high,'low':k.low,'components':[x.idx for x in raw],'closed':True}
        merged.append(item)
        if k.fx!=FX_TYPE.UNKNOWN:
            top=k.fx==FX_TYPE.TOP;pivot=k.get_high_peak_klu() if top else k.get_low_peak_klu()
            fractals.append({'id':f'cp:f:{pivot.idx}','kind':'top' if top else 'bottom','source':pivot.idx,
                             'price':k.high if top else k.low,'merged_index':k.idx})
    report={'schema':'chanlun.reference.v1','profile':PROFILE,'symbol':symbol,'period':period,'adjustment':adjustment,
            'source':source,'as_of':cutoff,'last_bar_at':bars[-1].closed_at,'config':SETTINGS,
            'input_sha256':input_sha256,'input_audit':{'state':'raw_observed_prefix','bars_used':len(bars)},
            'base':{'merged':merged,'fractals':fractals,'strokes':strokes,'segments':segments,'higher_segments':higher,'stroke_rejections':[]},
            'hierarchy':{'levels':layers,'base_units':[],'edges':[],'profile':PROFILE},'signals':signals,
            'divergence_comparisons':[],'feature_sequences':[],'center_evolution':[],'center_monitors':[],
            'construction_phases':[],'decompositions':[],'observed_signal_events':events,
            'certificate_audit':{'state':'native_engine','errors':[],'scope':'native engine assertions and adapter provenance'},
            'definition_mode':'pinned_native_feature_sequence','engine_commit':COMMIT,
            'approximation_loss':['Upstream pinned rule options are explicit; universal original-Chan equivalence is not proved.',
                                  'Native is_sure is local structure certainty, not a multi-timeframe trading trigger.',
                                  'Historical signals may be revised; observed event ledger records first-seen and withdrawn times.'],
            'strict_original_equivalence_proven':False,'execution_allowed':False,'signal_anchor_profile':'native_line_endpoint',
            'engine_provenance':{'url':'https://github.com/Vespa314/chan.py','commit':COMMIT,'license':'MIT'},
            'snapshot_semantics':'native engine computed every raw prefix; version observation times are not endpoint times'}
    return review_geometry(report)


def review_geometry(report):
    """Surface disagreements with an independent strict-extrema interpretation.

    This is a review criterion, not a proof that the upstream interpretation is
    universally wrong. Unreviewed parent structures cannot certify a signal.
    """
    fractals={f['source']:f for f in report['base']['fractals']};issues=[];bad_strokes=set();bad_segments=set()
    for s in report['base']['strokes']:
        reasons=[]
        if s['state']=='confirmed' and s['start'] in fractals and s['end'] in fractals:
            a,z=fractals[s['start']]['merged_index'],fractals[s['end']]['merged_index']
            part=report['base']['merged'][a:z+1]
            expected=(min(x['low'] for x in part),max(x['high'] for x in part))
            actual=(s['start_price'],s['end_price']) if s['direction']=='up' else (s['end_price'],s['start_price'])
            if actual!=expected:reasons.append('standard_interval_extrema_disagreement')
        s['review_issues']=reasons
        if reasons:bad_strokes.add(s['id']);issues.append({'id':s['id'],'kind':'stroke','reasons':reasons})
    for s in report['base']['segments']:
        part=[m for m in report['base']['strokes'] if s['start']<=m['start'] and m['end']<=s['end']]
        reasons=[]
        if s['state']=='confirmed' and part:
            vertices=[m['start_price'] for m in part]+[part[-1]['end_price']]
            actual=(s['start_price'],s['end_price']) if s['direction']=='up' else (s['end_price'],s['start_price'])
            if actual!=(min(vertices),max(vertices)):reasons.append('input_vertex_extrema_disagreement')
            if any(m['id'] in bad_strokes for m in part):reasons.append('contains_stroke_requiring_review')
        s['review_issues']=reasons
        if reasons:bad_segments.add(s['id']);issues.append({'id':s['id'],'kind':'segment','reasons':reasons})
    bad_centers=set()
    for layer in report.get('hierarchy',{}).get('levels',[]):
        bad_children=bad_strokes if layer['rank']==1 else bad_segments
        for center in layer['centers']:
            if any(component in bad_children for component in center.get('components',[])):
                center['review_issues']=['contains_component_requiring_review'];bad_centers.add(center['id'])
            else:center['review_issues']=[]
    for p in report['signals']:
        dependencies=[];start,end=p['terminal_range']
        for s in report['base']['strokes']:
            if s['start']<=end and s['end']>=start and s['id'] in bad_strokes:dependencies.append(s['id'])
        for s in report['base']['segments']:
            if s['start']<=end and s['end']>=start and s['id'] in bad_segments:dependencies.append(s['id'])
        if p.get('center_id') in bad_centers:dependencies.append(p['center_id'])
        if p.get('native_type','').startswith('3') and not p.get('center_id'):
            dependencies.append('native_center_relation_not_uniquely_mapped')
        p['review_dependencies']=dependencies
        if dependencies and p['state']!='invalidated':
            p['state']='needs_review';p['rule_audit']['passed']=False;p['rule_audit']['local_geometry_completed']=False
            p['rule_audit']['missing']=['independent_geometry_review_required']
    report['geometry_review']={'profile':'independent_strict_extrema_review_v1','issues':issues,
                               'stroke_issues':len(bad_strokes),'segment_issues':len(bad_segments),
                               'semantics':'strict-extrema interpretation disagreement; not an automatic original-theory verdict'}
    return report


def analyze_reference(symbol,period,bars,cutoff,input_sha256='',source='tdx',adjustment='unadjusted',*,observe=True):
    engine,selected,registry,events,first=run_reference(bars,period,observe,cutoff)
    report=make_report(engine,selected,registry,events,first,symbol,period,cutoff,source,adjustment,input_sha256)
    report['observation_mode']='every_closed_bar_prefix' if observe else 'final_cutoff_snapshot_no_historical_first_seen_claim'
    return report
