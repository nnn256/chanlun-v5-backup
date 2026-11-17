"""Closed-prefix price/volume phases; actor inventory and intent are unobserved.

Every range boundary is frozen before the candle that tests it. An inferred
phase is a research candidate; only consecutive closes beyond a prior boundary
receive a price-confirmed status. This classifier does not define Chan points.
"""
from __future__ import annotations

from collections import Counter, deque
import copy
import hashlib
import json
import math
from statistics import fmean

from .model import Candle

PHASE_VERSION='market_phase_price_volume_v1.0.0'
LABELS={
    'position_building_candidate':'建仓观察', 'absorption_candidate':'吸筹候选',
    'shakeout_candidate':'洗盘候选', 'supply_test_candidate':'试盘候选',
    'range_consolidation':'区间震荡', 'post_shakeout_consolidation':'洗盘后震荡',
    'post_test_consolidation':'试盘后震荡', 'launch_candidate':'启动候选',
    'launch_confirmed':'突破收盘确认', 'failed_launch':'启动失效',
    'distribution_risk':'派发风险', 'no_setup':'未形成阶段条件',
    'insufficient_data':'历史不足', 'data_discontinuity':'价格连续性待核对',
}
PARAMETERS={'warmup':60,'range_window':20,'near_window':5,'maximum_range_width':.20,
    'maximum_close_drift':.06,'prior_decline':.12,'breakout_buffer':.01,
    'support_buffer':.035,'probe_buffer':.005,'probe_volume':1.2,
    'launch_volume':1.3,'absorption_clv':.10,'contraction_volume':.90,
    'maximum_episode_sessions':120,'discontinuity':.25}
LIMITATIONS=[
    '建仓、吸筹、洗盘、试盘为量价代理；未观察到主力身份、库存或真实意图',
    '成交量承接不能等同资金净流入，筹码估算不能等同持仓登记',
    '标签可以跳过、反复或失效；并非必然按固定次序进入上涨',
]


def _average(values):
    return fmean(values) if values else None


def _clv(bar):
    return (2*bar.close-bar.high-bar.low)/(bar.high-bar.low) if bar.high>bar.low else 0.0


def _volume_ratio(values, reference):
    return values/reference if reference and reference>0 else None


class MarketPhaseSession:
    """One append per closed candle; bounded 121-bar feature work per update."""
    def __init__(self,symbol):
        self.symbol=symbol;self.bars=deque(maxlen=121);self.count=0
        self.events=[];self.episode=None;self.phase='insufficient_data'
        self.current={};self._digest=hashlib.sha256();self._last_time=None;self._last_gap=-1000

    def _emit(self,phase,bar,metrics,basis,status='candidate'):
        episode=self.episode or {}
        value={'id':f'{self.symbol}:phase:{phase}:{bar.pos}','phase':phase,'label':LABELS[phase],
            'symbol':self.symbol,'status':status,'available_at_index':bar.pos,
            'available_time':bar.closed_at,'anchor_index':bar.pos,'price':bar.close,
            'support':episode.get('support'),'resistance':episode.get('resistance'),
            'invalidation':episode.get('support',0)*(1-PARAMETERS['support_buffer']) or None,
            'episode_id':episode.get('id'),'range_known_at_index':episode.get('known_at_index'),
            'basis':list(basis),'metrics':dict(metrics),'actor_intent_verified':False,
            'definition_mode':'price_volume_phase_proxy','profile':PHASE_VERSION,
            'timeframe':'day','execution_allowed':False}
        changed=self.phase!=phase or self.current.get('episode_id')!=value.get('episode_id')
        if changed:
            self.events.append(copy.deepcopy(value))
        elif self.current:
            for key in ('id','available_at_index','available_time','anchor_index','price'):
                value[key]=self.current[key]
        self.phase=phase
        self.current={**value,'as_of':bar.closed_at,'as_of_index':bar.pos,'latest_price':bar.close,'next_watch':self._next_watch(phase),
            'limitations':list(LIMITATIONS)}

    @staticmethod
    def _next_watch(phase):
        if phase in {'launch_candidate','launch_confirmed'}:
            return '观察后续收盘能否守住原区间上沿；跌回则记录启动失效'
        if phase in {'failed_launch','distribution_risk','data_discontinuity'}:
            return '等待新的完整区间与承接证据，不沿用失效的启动判断'
        return '观察区间边界、回试量能与后续收盘；没有突破证据时保留候选'

    def append(self,bar):
        if not isinstance(bar,Candle):raise TypeError('append expects a Candle')
        if not bar.closed:return []
        if bar.pos!=self.count:raise ValueError('append one next closed candle only')
        if self._last_time is not None and bar.closed_at<=self._last_time:
            raise ValueError('candle times must strictly increase')
        numbers=(bar.open,bar.high,bar.low,bar.close,bar.volume)
        if any(x is None or not math.isfinite(x) for x in numbers) or min(numbers[:4])<=0 or bar.volume<0:
            raise ValueError('finite positive OHLC and nonnegative volume required')
        if bar.high<max(bar.open,bar.close,bar.low) or bar.low>min(bar.open,bar.close,bar.high):
            raise ValueError('invalid candle envelope')
        before=len(self.events);prior=list(self.bars)
        self._digest.update(json.dumps([bar.closed_at,*numbers],separators=(',',':')).encode()+b'\n')
        self.count+=1;self._last_time=bar.closed_at;self.bars.append(bar)
        if prior and abs(bar.open/prior[-1].close-1)>PARAMETERS['discontinuity']:
            self.episode=None;self._last_gap=bar.pos
            self._emit('data_discontinuity',bar,{},['开盘与前收盘跳变超过25%，旧区间停止沿用'],'unclassified')
            return self.events[before:]
        if self._last_gap>=0 and bar.pos-self._last_gap<60:
            self._emit('data_discontinuity',bar,{},['价格跳变后的60期观察窗口尚未完整'],'unclassified')
            return self.events[before:]
        if len(prior)<PARAMETERS['warmup']:
            self._emit('insufficient_data',bar,{'observations':len(prior)+1},['需要至少60根先前闭合K线'],'unclassified')
            return self.events[before:]
        base=prior[-20:];near=prior[-5:];history=prior[-60:]
        lo=min(b.low for b in base);hi=max(b.high for b in base)
        width=hi/lo-1
        drift=abs(base[-1].close/base[0].close-1)
        vol20=_average([b.volume for b in base if b.volume>0])
        vol5=_average([b.volume for b in near if b.volume>0])
        valid=sum(b.volume>0 for b in base)
        ratio=_volume_ratio(bar.volume,vol20)
        quiet=_volume_ratio(vol5,vol20) if vol5 is not None else None
        totalvol=sum(b.volume for b in base)
        clv=sum(_clv(b)*b.volume for b in base)/totalvol if totalvol>0 else None
        # The high preceding the twenty-bar base establishes low-position context.
        earlier=history[:-20];earlier_high=max(b.high for b in earlier)
        low_context=lo<=earlier_high*(1-PARAMETERS['prior_decline'])
        stable=width<=PARAMETERS['maximum_range_width'] and drift<=PARAMETERS['maximum_close_drift']
        metrics={'volume_ratio_20':ratio,'volume_ratio_5v20':quiet,'range_width':width,
            'range_width_pct':width*100,'return_20':bar.close/base[0].close-1,
            'close_location':(bar.close-bar.low)/(bar.high-bar.low) if bar.high>bar.low else .5,
            'clv_20':clv,'prior_decline':lo/earlier_high-1,'positive_volume_observations':valid,
            'prior_range_support':lo,'prior_range_resistance':hi,'prior_range_end_index':prior[-1].pos}
        if bar.volume<=0:
            self._emit('no_setup',bar,metrics,['本期无成交量，不推断当日建仓、吸筹、试盘或启动'],'unclassified')
            return self.events[before:]
        if self.episode and bar.pos-self.episode['known_at_index']>PARAMETERS['maximum_episode_sessions']:
            self.episode=None
        if self.episode and self.episode.get('launch_index') is None and bar.pos-self.episode['known_at_index']>=20:
            # A drifting range must renew from twenty entirely later candles;
            # otherwise its old high can masquerade as today's breakout level.
            overlap=lo<=self.episode['resistance'] and hi>=self.episode['support']
            if stable and low_context and overlap:
                self.episode.update(id=f'range:{bar.pos-1}',support=lo,resistance=hi,known_at_index=bar.pos-1,
                    last_test=None,last_test_index=None,was_shaken=False,was_tested=False)
            else:self.episode=None
        if self.episode and bar.low<self.episode['support']*(1-PARAMETERS['support_buffer']):
            self._emit('failed_launch' if self.episode.get('launch_index') is not None else 'no_setup',bar,metrics,
                ['价格跌破已知区间下沿的失效缓冲'],'observed')
            self.episode=None
            return self.events[before:]
        if self.episode is None and low_context and stable:
            self.episode={'id':f'range:{bar.pos-1}','support':lo,'resistance':hi,
                'known_at_index':bar.pos-1,'launch_index':None,'last_test':None,
                'last_test_index':None,'was_shaken':False,'was_tested':False}
        if self.episode is None:
            self._emit('range_consolidation' if stable else 'no_setup',bar,metrics,
                ['先前20根K线形成稳定区间' if stable else '当前尚无成熟低位区间'],
                'observed' if stable else 'unclassified')
            return self.events[before:]
        ep=self.episode;support=ep['support'];resistance=ep['resistance']
        metrics.update(range_position=(bar.close-support)/(resistance-support) if resistance>support else .5,
            frozen_range_support=support,frozen_range_resistance=resistance)
        if ep.get('launch_index') is not None:
            if bar.close<=resistance:
                self._emit('failed_launch',bar,metrics,['启动后收盘跌回原区间上沿'],'observed')
                self.episode=None
            elif ep.get('price_confirmed'):
                self._emit('launch_confirmed',bar,metrics,['已完成连续收盘确认，当前收盘仍守住原区间上沿'],'price_confirmed')
            elif (bar.pos>ep['launch_index'] and prior[-1].close>resistance*(1+PARAMETERS['breakout_buffer'])
                  and bar.close>resistance*(1+PARAMETERS['breakout_buffer'])):
                ep['price_confirmed']=True
                self._emit('launch_confirmed',bar,metrics,['连续两根闭合K线收盘高于先前上沿1%'],'price_confirmed')
            else:
                self._emit('launch_candidate',bar,metrics,['已突破但尚未形成连续收盘确认'])
            return self.events[before:]
        strong_volume=ratio is not None and ratio>=PARAMETERS['launch_volume'] and bar.volume>0
        if bar.close>resistance*(1+PARAMETERS['breakout_buffer']) and strong_volume and metrics['close_location']>=.65:
            ep['launch_index']=bar.pos
            self._emit('launch_candidate',bar,metrics,['收盘突破先前区间上沿1%','当日量能不低于前20日均量1.3倍','收盘位于当日振幅上部'])
        elif ratio is not None and ratio>=2.5 and bar.close<bar.open and metrics['close_location']<=.35:
            self._emit('distribution_risk',bar,metrics,['区间内放量下跌且收盘偏弱；洗盘与派发暂不能区分'])
        elif (bar.low<support*(1-PARAMETERS['probe_buffer']) and bar.close>=support
              and ratio is not None and 0<ratio<=1.2 and metrics['close_location']>=.65):
            ep.update(last_test='shakeout_candidate',last_test_index=bar.pos,was_shaken=True)
            self._emit('shakeout_candidate',bar,metrics,['试破已知区间下沿后收盘收回','试探时量能未明显放大','收盘承接较强'])
        elif (bar.high>resistance*(1+PARAMETERS['probe_buffer']) and resistance*.97<=bar.close<=resistance
              and ratio is not None and ratio>=PARAMETERS['probe_volume']
              and (bar.high-max(bar.open,bar.close))/max(1e-12,bar.high-bar.low)>=.30):
            ep.update(last_test='supply_test_candidate',last_test_index=bar.pos,was_tested=True)
            self._emit('supply_test_candidate',bar,metrics,['上冲已知区间上沿后收回区间','放量上影显示上方供给试探；无法验证操作者意图'])
        elif (ep['last_test_index'] is not None and 1<=bar.pos-ep['last_test_index']<=10
              and support<=bar.close<=resistance):
            key='post_shakeout_consolidation' if ep['last_test']=='shakeout_candidate' else 'post_test_consolidation'
            self._emit(key,bar,metrics,['先前试探后价格继续守在已知区间内'],'observed')
        elif (valid>=15 and clv is not None and clv>=PARAMETERS['absorption_clv']
              and quiet is not None and quiet<=1.05 and support<=bar.close<=resistance):
            self._emit('absorption_candidate',bar,metrics,['低位已知区间内成交量加权收盘承接为正','近端量能未过热；仅支持吸筹代理判断'])
        elif (quiet is not None and 0<quiet<=PARAMETERS['contraction_volume']
              and valid>=15 and support<=bar.close<=resistance):
            self._emit('position_building_candidate',bar,metrics,['先前低位区间横向稳定','近5日量能相对前20日收缩；建仓意图未被观察'])
        elif support<=bar.close<=resistance:
            self._emit('range_consolidation',bar,metrics,['价格仍在先前已知区间附近，尚无足够启动证据'],'observed')
        else:
            self._emit('no_setup',bar,metrics,['价格离开区间但量价组合不足，不能归为吸筹或启动'],'unclassified')
        return self.events[before:]

    def snapshot(self):
        return {'symbol':self.symbol,'version':PHASE_VERSION,'definition_mode':'price_volume_phase_proxy',
            'timeframe':'day','current':copy.deepcopy(self.current),
            'events':copy.deepcopy(self.events[-100:]),'counts':dict(Counter(e['phase'] for e in self.events)),
            'parameters':dict(PARAMETERS),'input_sha256':self._digest.hexdigest(),
            'closed_count':self.count,'actor_intent_verified':False,'execution_allowed':False,
            'limitations':list(LIMITATIONS)}
