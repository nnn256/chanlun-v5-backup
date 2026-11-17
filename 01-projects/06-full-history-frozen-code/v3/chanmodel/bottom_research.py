"""Prefix-causal bottom formation and exit research, separate from Chan buy points.

The state machine records structure boundaries when they become knowable. It
does not claim that every range becomes a bottom or that a candidate predicts
future profit. Money-flow history is excluded unless it has point-in-time
publication evidence; chip positioning is a turnover-weighted price-distribution
proxy, not observed shareholder holdings.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from statistics import mean
from collections import deque
from bisect import bisect_right

from .causal_replay import StreamingStructure
from .model import Candle, Config
from .signals import macd
from .structure import merge_bars, fractals_at, strokes_at
from .v2.series import session_closes
from .market_phase import MarketPhaseSession

BOTTOM_VERSION='bottom_departure_causal_v1.0.3'
VARIANTS=('structure_v1','participation_v1','regime_v1')
CN=timezone(timedelta(hours=8))
CONFIG=Config(stroke_mode='strict',macd_multiplier=2.0,second_policy='conservative')
STOP_BUFFER=0.035
RETEST_BAND=0.025
BREAKOUT_BUFFER=0.01
MIN_REBOUND=0.04
TARGET_RETURN=0.10
HORIZON=20
ROUND_TRIP_COST=0.0020


def _number(value,default=None):
    try:value=float(value)
    except (TypeError,ValueError):return default
    return value if math.isfinite(value) else default


def _bar(value,index):
    stamp=value.get('closed_at') or value.get('date_cn') or value.get('time')
    if isinstance(stamp,(int,float)):
        point=datetime.fromtimestamp(stamp-8*3600,CN)
    else:
        raw=str(stamp).replace(' ','T')
        point=datetime.fromisoformat(raw if ('T' in raw and ('+' in raw[10:] or '-' in raw[10:])) else raw+':00+08:00')
        if point.tzinfo is None:point=point.replace(tzinfo=CN)
        else:point=point.astimezone(CN)
    closed=value.get('is_closed',value.get('closed',True)) is not False
    return Candle(index,*[_number(value.get(key)) for key in ('open','high','low','close')],
                  point.isoformat(),_number(value.get('volume'),0.0),closed)


def _chip_proxy(bars,index,window=60,bins=24):
    """Causal turnover-weighted close distribution; not actual holder cost basis."""
    prior=bars[max(0,index-window+1):index+1]
    valid=[b for b in prior if b.volume and b.volume>0]
    if len(valid)<8:return {'state':'insufficient','mode':'turnover_price_distribution_proxy',
                            'observations':len(valid),'observed_holdings':False}
    lo=min(b.low for b in valid);hi=max(b.high for b in valid)
    if hi<=lo:return {'state':'flat_range','mode':'turnover_price_distribution_proxy',
                      'observations':len(valid),'observed_holdings':False}
    weights=[0.0]*bins
    for bar in valid:
        typical=(bar.high+bar.low+bar.close)/3
        slot=min(bins-1,max(0,int((typical-lo)/(hi-lo)*bins)))
        weights[slot]+=bar.volume
    peak=max(range(bins),key=lambda slot:weights[slot]);total=sum(weights)
    selected={peak};covered=weights[peak];left=peak-1;right=peak+1
    while covered<total*.70 and (left>=0 or right<bins):
        if left<0:take_right=True
        elif right>=bins:take_right=False
        else:take_right=weights[right]>=weights[left]
        slot=right if take_right else left
        selected.add(slot);covered+=weights[slot]
        if take_right:right+=1
        else:left-=1
    width=(hi-lo)/bins
    poc=lo+(peak+.5)*width
    return {'state':'estimated','mode':'turnover_price_distribution_proxy','observations':len(valid),
            'observed_holdings':False,'point_of_control_proxy':poc,
            'value_area_low_proxy':lo+min(selected)*width,'value_area_high_proxy':lo+(max(selected)+1)*width,
            'poc_distance_pct':(valid[-1].close/poc-1)*100 if poc else None,
            'known_at':valid[-1].closed_at,
            'limitations':['turnover distributes traded volume over price bins','not shareholder registry or account-cost data']}


def _participation(bars,index,chip):
    prior=bars[max(0,index-20):index]
    recent=bars[max(0,index-4):index]
    volumes=[b.volume for b in prior if b.volume and b.volume>0]
    avg=mean(volumes) if volumes else None
    recent_vol=mean([b.volume for b in recent if b.volume and b.volume>0]) if recent else None
    volume_ratio=recent_vol/avg if avg and recent_vol is not None else None
    last=bars[index]
    close_location=(last.close-last.low)/(last.high-last.low) if last.high>last.low else .5
    # Current historical samples do not include point-in-time main-force flow.
    money={'state':'not_point_in_time','known_at':None,'historical_usable':False,
           'source':'none','reason':'available source snapshots lack independently verified publication timestamps'}
    emotion={'state':'proxy','score':None,'known_at':last.closed_at,
             'source':'price_volume_regime_proxy','historical_usable':True,
             'inputs':['20-session return','20-session realized range','recent volume ratio']}
    start=max(0,index-20)
    ret20=(last.close/bars[start].close-1) if bars[start].close else 0
    hi=max(x.high for x in bars[start:index+1]);lo=min(x.low for x in bars[start:index+1])
    drawdown=(last.close/hi-1) if hi else 0
    emotion_score=max(0,min(100,50+ret20*240+drawdown*180))
    emotion={**emotion,'score':round(emotion_score,2),'return_20':round(ret20,5),'drawdown_20':round(drawdown,5)}
    chip_distance=chip.get('poc_distance_pct') if chip.get('state')=='estimated' else None
    participation_score=0
    if volume_ratio is not None:participation_score+=1 if volume_ratio<=.9 else -1 if volume_ratio>1.5 else 0
    participation_score+=1 if close_location>=.65 else -1 if close_location<=.3 else 0
    participation_score+=1 if ret20>0 else -1 if drawdown<-.12 else 0
    if chip_distance is not None:participation_score+=1 if -5<=chip_distance<=3 else -1 if chip_distance>12 else 0
    return {'volume_ratio_4v20':round(volume_ratio,4) if volume_ratio is not None else None,
            'close_location':round(close_location,4),'return_20':round(ret20,5),
            'drawdown_20':round(drawdown,5),'participation_score':participation_score,
            'money_flow':money,'emotion':emotion,'chip_structure':chip}


def _segment_force(segment,bars):
    start=max(0,segment['start']);end=min(len(bars)-1,segment['end'])
    selected=bars[start:end+1]
    volume=sum(x.volume or 0 for x in selected)
    area=_number(segment.get('macd_area'),sum(abs(x.close-x.open) for x in selected))
    amplitude=abs(segment['end_price']/segment['start_price']-1) if segment['start_price'] else 0
    return {'bars':len(selected),'volume':volume,'macd_area':area,'relative_amplitude':amplitude,
            'normalized_force':area/max(1,len(selected)),
            'definition':'directional MACD absolute area / segment duration; price amplitude retained separately'}


class BottomSession:
    """Append-only daily bottom-state observer using only closed-prefix data."""
    def __init__(self,symbol,benchmark_by_date=None,emotion_by_date=None,flow_by_date=None):
        self.symbol=symbol;self.stream=StreamingStructure(CONFIG,segments=True);self.bars=[]
        self.bottom_events=[];self.events=[];self.active=None;self.seen_fractals=set();self.fractal_state={}
        self.benchmark_by_date=benchmark_by_date or {};self.emotion_by_date=emotion_by_date or {};self.flow_by_date=flow_by_date or {}
        self._last_revision=None;self._digest=hashlib.sha256();self._benchmark_dates=sorted(self.benchmark_by_date)
        self.market_phase=MarketPhaseSession(symbol)

    def _features(self,index,chip):
        features=_participation(self.bars,index,chip)
        date=self.bars[index].closed_at[:10];position=bisect_right(self._benchmark_dates,date)-1
        if position>=20:
            end=self._benchmark_dates[position];start=self._benchmark_dates[position-20]
            last=self.benchmark_by_date[end];prior=self.benchmark_by_date[start]
            if last and prior and prior>0:
                ret=last/prior-1
                features['benchmark_return_20']=ret;features['benchmark_as_of']=end
                features['emotion']={'state':'proxy','score':round(max(0,min(100,50+ret*400)),2),
                    'source':'sh000001_20session_return_proxy','known_at':end+'T15:00:00+08:00',
                    'historical_usable':True,'meaning':'index regime proxy, not limit-up or investor sentiment survey'}
        for mapping,key in ((self.emotion_by_date,'emotion'),(self.flow_by_date,'money_flow')):
            record=mapping.get(date)
            if not isinstance(record,dict):continue
            known=record.get('known_at') or record.get('published_at')
            if record.get('historical_usable') is True and record.get('publication_time_verified') is True and known:
                if datetime.fromisoformat(known)<=datetime.fromisoformat(self.bars[index].closed_at):
                    features[key]={**record,'state':'observed','historical_usable':True}
        return features

    def _emit(self,state,index,*,anchor=None,price=None,basis=None,features=None,score=None):
        active=self.active
        event={'id':f'{self.symbol}:{active["id"]}:{state}:{index}','symbol':self.symbol,'sequence':len(self.events),
               'state':state,'anchor_index':active['anchor_index'] if anchor is None else anchor,
               'available_at_index':index,'available_time':self.bars[index].closed_at,
               'anchor_time':self.bars[active['anchor_index'] if anchor is None else anchor].closed_at,
               'price':price if price is not None else active['support'],
               'support':active['support'],'resistance':active.get('resistance'),
               'invalidation':active['support']*(1-STOP_BUFFER),
               'score':score if score is not None else active.get('score',0),
               'basis':basis or [],'features':features or {},'definition_mode':'bottom_structure_proxy_v1',
               'profile':BOTTOM_VERSION,'execution_allowed':False,
               'strict_original_equivalence_proven':False}
        self.events.append(event);active['state']='watch' if state=='bottom_watch' else state;active['last_event_index']=index
        active['score']=event['score']
        return event

    def _begin_watch(self,fractal,index,divergence,force_now,force_prior):
        self.active={'id':fractal['id'],'anchor_index':fractal['source'],'support':fractal['price'],
            'state':'watch','score':0,'resistance':None,'first_bottom_index':fractal['source'],
            'first_bottom_available':index,'breakout_index':None}
        chip=_chip_proxy(self.bars,index);features=self._features(index,chip)
        score=(1 if divergence else 0)+(1 if features['volume_ratio_4v20'] is not None and features['volume_ratio_4v20']<1 else 0)+1
        event=self._emit('bottom_watch',index,anchor=fractal['source'],price=fractal['price'],
            basis=['closed_confirmed_bottom_fractal']+(['down_segment_force_weakened'] if divergence else []),
            features={**features,'down_force':force_now,'prior_down_force':force_prior},score=score)
        event['episode_id']=self.active['id'];self.bottom_events.append(event)
        return event

    def append(self,value):
        bar=value if isinstance(value,Candle) else _bar(value,len(self.bars))
        if not bar.closed:return []
        if bar.pos!=len(self.bars):bar=Candle(len(self.bars),bar.open,bar.high,bar.low,bar.close,bar.closed_at,bar.volume,bar.closed)
        emitted=[];self.bars.append(bar)
        changed=self.stream.append(bar)
        index=bar.pos
        if self.active and index-self.active['first_bottom_available']>120:
            event=self._emit('expired',index,basis=['120_closed_sessions_without_completed_episode'])
            event['episode_id']=self.active['id'];emitted.append(event);self.bottom_events.append(event);self.active=None
        if self.active:
            active=self.active
            if active['state'] not in {'invalidated','advance'} and bar.low<active['support']*(1-STOP_BUFFER):
                event=self._emit('invalidated',index,basis=['closed_daily_low_breached_support_buffer'],score=0)
                event['episode_id']=active['id'];emitted.append(event);self.bottom_events.append(event);self.active=None
        current_fractals={f['id']:f for f in self.stream.fractals}
        for ident,prior in list(self.fractal_state.items()):
            if prior['state']=='candidate' and ident not in current_fractals and prior['available_at_index']<index:
                revision={'id':f'{self.symbol}:{ident}:withdrawn:{index}','symbol':self.symbol,
                    'event':'fractal_revision','state':'withdrawn','fractal_id':ident,
                    'anchor_index':prior['anchor_index'],'available_at_index':index,'available_time':bar.closed_at,
                    'price':prior['price'],'basis':'new_closed_bar_revised_prior_fractal','execution_allowed':False}
                self.events.append(revision);self.bottom_events.append(revision);emitted.append(revision);prior['state']='withdrawn'
                if self.active and ident in self.active.get('source_fractal_ids',[self.active['id']]):
                    revision['episode_id']=self.active['id']
                    revision['basis']='active_bottom_evidence_withdrawn'
                    self.active=None
        # A fractal is usable only after its right-side candle is closed.
        for fractal in self.stream.fractals:
            if fractal['kind']!='bottom' or fractal['basis_at']>index:continue
            if fractal['id'] not in self.fractal_state:
                self.fractal_state[fractal['id']]={'state':'candidate','anchor_index':fractal['source'],
                    'available_at_index':fractal['basis_at'],'price':fractal['price']}
            if fractal['id'] in self.seen_fractals:continue
            self.seen_fractals.add(fractal['id'])
            prev_segment=next((s for s in reversed(self.stream.segments)
                               if s['direction']=='down' and s['state']=='confirmed' and s['end']<=fractal['source']),None)
            prior_down=next((s for s in reversed(self.stream.segments)
                             if prev_segment and s['direction']=='down' and s['state']=='confirmed' and s['end']<prev_segment['start']),None)
            force_now=_segment_force(prev_segment,self.bars) if prev_segment else None
            force_prior=_segment_force(prior_down,self.bars) if prior_down else None
            divergence=bool(force_now and force_prior and prev_segment['basis_at']<=index and prior_down['basis_at']<=index
                and prev_segment['end_price']<prior_down['end_price']
                and force_now['normalized_force']<force_prior['normalized_force'])
            if self.active is None:
                if index<30:continue
                prior_high=max(b.high for b in self.bars[max(0,index-60):index+1])
                if fractal['price']>prior_high*.92:continue
                emitted.append(self._begin_watch(fractal,index,divergence,force_now,force_prior))
                continue
            active=self.active
            distance=fractal['price']/active['support']-1 if active['support'] else 0
            if active['state']=='watch':
                if distance<0:
                    # A new confirmed low inside the support buffer supersedes a
                    # stale watch and starts a fresh two-bottom episode.
                    prior_episode=active['id']
                    revision=self._emit('superseded',index,anchor=fractal['source'],price=fractal['price'],
                        basis=['new_confirmed_lower_bottom_supersedes_watch'],score=0)
                    revision['episode_id']=prior_episode;revision['superseded_by']=fractal['id']
                    self.bottom_events.append(revision);emitted.append(revision);self.active=None
                    prior_high=max(b.high for b in self.bars[max(0,index-60):index+1])
                    if index>=30 and fractal['price']<=prior_high*.92:
                        emitted.append(self._begin_watch(fractal,index,divergence,force_now,force_prior))
                    continue
                # A rebound counts only when its top anchor lies between the
                # first and second bottom anchors, not merely when confirmed now.
                tops=[f for f in self.stream.fractals if f['kind']=='top' and
                      active['first_bottom_index']<f['source']<fractal['source'] and
                      f['basis_at']<=index]
                resistance_tops=[f for f in self.stream.fractals if f['kind']=='top' and
                      active['first_bottom_index']<f['source'] and f['basis_at']<=index]
                if resistance_tops:active['resistance']=max(f['price'] for f in resistance_tops)
                if distance<=.06 and index>=active['first_bottom_available']+3 and tops and max(f['price'] for f in tops)>=active['support']*(1+MIN_REBOUND):
                    active['support']=min(active['support'],fractal['price'])
                    active['source_fractal_ids']=[active['id'],fractal['id']]
                    chip=_chip_proxy(self.bars,index);features=self._features(index,chip)
                    event=self._emit('base_formed',index,anchor=fractal['source'],price=fractal['price'],
                        basis=['second_confirmed_bottom_fractal','higher_low_within_6pct','support_not_invalidated','intervening_rebound_at_least_4pct'],
                        features=features,score=min(5,active['score']+1+(1 if features['volume_ratio_4v20'] is not None and features['volume_ratio_4v20']<.9 else 0)))
                    event['episode_id']=active['id'];emitted.append(event);self.bottom_events.append(event)
        active=self.active
        if active:
            index_high=max(b.high for b in self.bars[active['first_bottom_index']:index+1])
            if active['resistance'] is None and index>active['first_bottom_available']:
                active['resistance']=index_high
            if active['state']=='base_formed' and active.get('breakout_index') is None and active.get('resistance'):
                # Departure is a research state after a closed close above a resistance
                # that was established by a previously confirmed top fractal.
                valid_tops=[f for f in self.stream.fractals if f['kind']=='top' and
                            active['first_bottom_available']<f['basis_at']<index]
                resistance=max((f['price'] for f in valid_tops),default=active['resistance'])
                active['resistance']=resistance
                if valid_tops and index>active.get('last_event_index',-1) and bar.close>resistance*(1+BREAKOUT_BUFFER):
                    chip=_chip_proxy(self.bars,index);features=self._features(index,chip)
                    event=self._emit('departure',index,price=bar.close,
                        basis=['closed_close_above_previously_confirmed_resistance','upward_departure_candidate'],
                        features=features,score=active['score']+1+(1 if bar.close>bar.open else 0))
                    active['breakout_index']=index;active['breakout_resistance']=resistance
                    event['episode_id']=active['id'];emitted.append(event);self.bottom_events.append(event)
            elif active['state']=='departure' and active.get('breakout_index') is not None and index>active['breakout_index']:
                resistance=active.get('breakout_resistance',active['resistance'])
                touched_retest=bar.low<=resistance*(1+RETEST_BAND)
                if touched_retest and resistance*(1-RETEST_BAND)<=bar.low and bar.close>resistance:
                    chip=_chip_proxy(self.bars,index);features=self._features(index,chip)
                    event=self._emit('retest_held',index,price=bar.close,
                        basis=['first_post_departure_retest','close_holds_above_breakout_level'],features=features,score=active['score']+2)
                    event['episode_id']=active['id'];event['state']='retest_held';emitted.append(event);self.bottom_events.append(event)
                elif touched_retest:
                    event=self._emit('retest_failed',index,
                        basis=['first_post_departure_retest_failed_to_hold_breakout_level'],score=0)
                    event['episode_id']=active['id'];emitted.append(event);self.bottom_events.append(event);self.active=None
                elif bar.close<resistance*(1-STOP_BUFFER):
                    event=self._emit('invalidated',index,basis=['post_breakout_close_lost_reclaimed_resistance'],score=0)
                    event['episode_id']=active['id'];emitted.append(event);self.bottom_events.append(event);self.active=None
            elif active['state']=='retest_held':
                resistance=active.get('breakout_resistance',active['resistance'])
                if bar.close<resistance:
                    event=self._emit('invalidated',index,basis=['post_retest_close_lost_breakout_level'],score=0)
                    event['episode_id']=active['id'];emitted.append(event);self.bottom_events.append(event);self.active=None
        self.market_phase.append(bar)
        self._digest.update(json.dumps([bar.closed_at,bar.open,bar.high,bar.low,bar.close,bar.volume],separators=(',',':')).encode()+b'\n')
        self._last_revision=self._digest.hexdigest()
        for event in emitted:event['episode_id']=event.get('episode_id',self.active['id'] if self.active else None)
        return emitted

    def snapshot(self):
        bars=self.bars
        if not bars:
            return {'symbol':self.symbol,'version':BOTTOM_VERSION,'state':'no_data','bars':[],
                    'bottom_events':[],'current':{'state':'no_data'},'history':[], 'market_phase':self.market_phase.snapshot(),
                    'factor_coverage':factor_coverage(self.emotion_by_date,self.flow_by_date),
                    'definition_mode':'bottom_structure_proxy_v1','execution_allowed':False}
        prefix=[Candle(i,b.open,b.high,b.low,b.close,b.closed_at,b.volume,True) for i,b in enumerate(bars)]
        digest=self._last_revision
        structure=self.stream.snapshot(max_rank=4)
        current=self._current_features(structure,prefix)
        centers=[center for level in structure['hierarchy']['levels'] for center in level['centers']]
        return {'symbol':self.symbol,'version':BOTTOM_VERSION,'state':self.active['state'] if self.active else current['state'],
                'bars':[{'time':int(datetime.fromisoformat(b.closed_at).timestamp())+8*3600,
                         'source_index':b.pos,'date_cn':b.closed_at[:16].replace('T',' '),
                         'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume,'is_closed':True} for b in bars],
                'fractals':structure['base']['fractals'],'strokes':structure['base']['strokes'],'segments':structure['base']['segments'],
                'all_centers':centers,
                'signals':structure['signals'],'confirmations':[],'bottom_events':self.bottom_events[-100:],
                'current':current,'history':self.events[-200:],'market_phase':self.market_phase.snapshot(),
                'coverage':{'count':len(bars),'closed_count':len(bars),'first':bars[0].closed_at,'last':bars[-1].closed_at,
                            'input_sha256':digest,'revision_sha256':digest,'max_observed_index':len(bars)-1,
                            'refresh_after_seconds':10},
                'factor_coverage':factor_coverage(self.emotion_by_date,self.flow_by_date),
                'definition_mode':'bottom_structure_proxy_v1','execution_allowed':False,
                'strict_original_equivalence_proven':False}

    def _current_features(self,structure,bars):
        down=[s for s in structure['base']['segments'] if s['direction']=='down' and s['state']=='confirmed']
        down=down[-2:];divergence=False
        if len(down)==2:
            previous,latest=down
            divergence=(latest['end_price']<previous['end_price'] and
                        latest['macd_area']/max(1,latest['end']-latest['start']+1)<
                        previous['macd_area']/max(1,previous['end']-previous['start']+1))
        chip=_chip_proxy(bars,len(bars)-1);features=self._features(len(bars)-1,chip)
        support=self.active['support'] if self.active else None
        resistance=self.active.get('resistance') if self.active else None
        close=bars[-1].close
        if self.active and close<self.active['support']*(1-STOP_BUFFER):state='invalidated'
        elif self.active:state=self.active['state']
        else:state='no_setup'
        return {'state':state,'score':self.active['score'] if self.active else 0,
                'support':support,'resistance':resistance,'close':close,'as_of':bars[-1].closed_at,
                'divergence':divergence,'features':features,
                'money_flow':features['money_flow'],'chip_structure':chip,
                'emotion':features['emotion'],'basis':['closed_daily_prefix_only']+(['weaker_second_down_segment'] if divergence else []),
                'invalidation':support*(1-STOP_BUFFER) if support else None,
                'definitions':{'stop_buffer':STOP_BUFFER,'retest_band':RETEST_BAND,'breakout_buffer':BREAKOUT_BUFFER,
                               'minimum_rebound':MIN_REBOUND}}


def factor_coverage(emotion_by_date=None,flow_by_date=None):
    emotion_by_date=emotion_by_date or {};flow_by_date=flow_by_date or {}
    return {'money_flow':{'state':'unavailable' if not flow_by_date else 'retrospective_only',
            'records':len(flow_by_date),'historical_usable':False,
            'meaning':'attributed order-size flow, not verified beneficial-owner holdings; known_at absent or after collection'},
            'chips':{'state':'turnover_distribution_proxy','historical_usable':True,'observed_holdings':False,
            'meaning':'causal rolling turnover-weighted price bins; not shareholder cost basis'},
            'emotion':{'state':'archive_available' if emotion_by_date else 'price_volume_proxy_only',
            'records':len(emotion_by_date),'historical_usable':False if emotion_by_date else None,
            'meaning':'market-wide daily snapshots have delayed collection timestamps; market return/drawdown proxy is prefix causal'}}


def eligible(event,variant):
    if event.get('state')!='base_formed':return False
    features=event.get('features') or {};participation=features.get('participation_score',0)
    if variant=='structure_v1':return True
    if variant=='participation_v1':return participation>=0 and (features.get('volume_ratio_4v20') is None or features['volume_ratio_4v20']<=1.5)
    if variant=='regime_v1':return (features.get('emotion') or {}).get('score',50)>=35 and participation>=-1
    raise ValueError('unknown bottom validation variant: '+str(variant))


def _return(entry,exit_,cost=ROUND_TRIP_COST):
    return (exit_/entry-1)-cost if entry else None


def evaluate_events(symbol,bars,events,*,horizon=HORIZON,target=TARGET_RETURN,benchmark_by_date=None):
    """20-session target/support barrier; simultaneous barriers resolve adversely first."""
    if type(horizon) is not int or horizon<2:raise ValueError('horizon must be an integer >=2 sessions for A-share T+1')
    if not 0<target<1:raise ValueError('target must be in (0,1)')
    result=[]
    for event in events:
        if event['state'] not in {'base_formed'}:continue
        available=event.get('available_at_index')
        if not isinstance(available,int) or available+1>=len(bars):continue
        entry_index=available+1;entry=bars[entry_index].open
        stop=event['support']*(1-STOP_BUFFER);limit=entry*(1+target)
        if entry<=stop:
            result.append({'symbol':symbol,'event_id':event['id'],'state':'invalidated_before_entry',
                'available_at_index':available,'entry_index':entry_index,'entry_time':bars[entry_index].closed_at,
                'entry_price':None,'return':None,'horizon':horizon,'horizon_complete':False,
                'max_observed_index':entry_index,'execution_allowed':False})
            continue
        end=min(len(bars)-1,entry_index+horizon-1);outcome='censored';exit_price=bars[end].close;exit_index=end
        if entry<=0:
            result.append({'symbol':symbol,'event_id':event['id'],'state':'invalid_entry_price',
                           'available_at_index':available,'entry_index':entry_index,'return':None,
                           'evaluation_end_index':entry_index,'horizon':horizon,'execution_allowed':False})
            continue
        for index in range(entry_index+1,end+1):
            bar=bars[index]
            stop_hit=bar.low<=stop;target_hit=bar.high>=limit
            if stop_hit:
                outcome='stop';exit_price=min(bar.open,stop) if bar.open<stop else stop;exit_index=index;break
            if target_hit:
                outcome='target';exit_price=max(bar.open,limit) if bar.open>limit else limit;exit_index=index;break
        outcome_complete=outcome in {'target','stop'} or end==entry_index+horizon-1
        item={'symbol':symbol,'event_id':event['id'],'state':outcome,
            'available_at_index':available,'entry_index':entry_index,'entry_time':bars[entry_index].closed_at,
            'entry_price':entry,'exit_index':exit_index,'exit_time':bars[exit_index].closed_at,
            'exit_price':exit_price,'gross_return':exit_price/entry-1,'return':_return(entry,exit_price),
            'target':target,'support_stop':stop,'horizon':horizon,'horizon_complete':end==entry_index+horizon-1,
            'outcome_complete':outcome_complete,'label_end_index':end,'label_end_time':bars[end].closed_at,
            'max_observed_index':end,'horizon_end_time':bars[end].closed_at,
            'signal_time':bars[available].closed_at,'execution_allowed':False}
        benchmark_by_date=benchmark_by_date or {}
        entry_date=bars[entry_index].closed_at[:10];exit_date=bars[exit_index].closed_at[:10]
        b0=benchmark_by_date.get(entry_date);b1=benchmark_by_date.get(exit_date)
        if b0 and b1 and b0>0:item.update(benchmark_return=b1/b0-1,excess_return=item['return']-(b1/b0-1),benchmark_source='TDX sh000001 daily close')
        else:item.update(benchmark_return=None,excess_return=None,benchmark_source=None)
        result.append(item)
    return result


def summarize(outcomes):
    finished=[row for row in outcomes if row['state'] in {'target','stop','censored','same_bar_adverse'} and row.get('return') is not None]
    complete=[row for row in finished if row.get('outcome_complete',row.get('horizon_complete'))]
    returns=[row['return'] for row in complete]
    mean_return=sum(returns)/len(returns) if returns else None
    n_target=sum(row['state']=='target' for row in complete);n_stop=sum(row['state'] in {'stop','same_bar_adverse'} for row in complete)
    return {'events':len(outcomes),'evaluated':len(complete),'censored':sum(not row.get('horizon_complete',False) for row in finished),
            'target_hits':n_target,'stops':n_stop,'direction_hit_rate':n_target/len(complete) if complete else None,
            'mean_return':mean_return,'median_return':sorted(returns)[len(returns)//2] if returns else None,
            'execution_allowed':False}


def annotate_split_rows(rows,boundaries):
    """Classify by actual forward outcome completion date, not signal date."""
    train_end,validation_end=boundaries
    for row in rows:
        outcome_date=str(row.get('exit_time') or '')[:10]
        row['split']='train' if outcome_date and outcome_date<=train_end else 'validation' if outcome_date and outcome_date<=validation_end else 'test' if outcome_date else 'censored'
    return rows


def time_splits(date_sequences,purge=HORIZON):
    dates=sorted({date for seq in date_sequences for date in seq})
    if len(dates)<purge*4:raise ValueError(f'chronological research needs at least {purge*4} distinct sessions')
    train_end=dates[int(len(dates)*.70)-1];validation_end=dates[int(len(dates)*.85)-1]
    return {'train_start':dates[0],'train_end':train_end,'validation_end':validation_end,'test_end':dates[-1],
            'trading_dates':dates,
            'purge_sessions':purge,'basis':'chronological union of collected daily sessions; labels crossing boundaries are purged',
            'current_universe_survivorship_bias':True}


def split_outcomes(rows,splits,horizon=HORIZON):
    bounds={'train':splits['train_end'],'validation':splits['validation_end'],'test':splits['test_end']}
    dates=splits.get('trading_dates') or []
    date_index={date:index for index,date in enumerate(dates)}
    train_edge=date_index.get(splits['train_end']);validation_edge=date_index.get(splits['validation_end']);test_edge=date_index.get(splits['test_end'])
    for row in rows:
        date=(row.get('entry_time') or '')[:10];exit_date=(row.get('label_end_time') or row.get('horizon_end_time') or row.get('exit_time') or '')[:10]
        if not date:row['split']='censored';continue
        start=date_index.get(date);end=date_index.get(exit_date)
        if start is None or end is None:row['split']='censored';continue
        if date<=bounds['train']:
            split='train';start_ok=train_edge is not None and start<=train_edge-horizon
            end_ok=train_edge is not None and end<=train_edge-horizon
        elif date<=bounds['validation']:
            split='validation';start_ok=train_edge is not None and validation_edge is not None and start>=train_edge+horizon
            end_ok=validation_edge is not None and end<=validation_edge-horizon
        else:
            split='test';start_ok=validation_edge is not None and start>=validation_edge+horizon
            end_ok=test_edge is not None and end<=test_edge
        if row.get('outcome_complete',row.get('horizon_complete')) and start_ok and end_ok:
            row['split']=split
        else:
            row['split']='purged' if split!='test' or validation_edge is not None and start<validation_edge+horizon else 'censored'
    return rows


def split_metrics(rows):
    result={}
    for split in ('train','validation','test'):
        sample=[row for row in rows if row.get('split')==split and row.get('outcome_complete',row.get('horizon_complete'))]
        returns=[row['return'] for row in sample if isinstance(row.get('return'),(int,float))]
        excess=[row['excess_return'] for row in sample if isinstance(row.get('excess_return'),(int,float))]
        result[split]={'events':sum(row.get('split')==split for row in rows),'evaluated':len(sample),
            'target_hits':sum(row.get('state')=='target' for row in sample),
            'stops':sum(row.get('state')=='stop' for row in sample),
            'direction_hit_rate':sum(row.get('state')=='target' for row in sample)/len(sample) if sample else None,
            'mean_return':sum(returns)/len(returns) if returns else None,
            'mean_excess_return':sum(excess)/len(excess) if excess else None}
    result['purged']=sum(row.get('split')=='purged' for row in rows)
    result['censored']=sum(row.get('split')=='censored' for row in rows)
    return result
