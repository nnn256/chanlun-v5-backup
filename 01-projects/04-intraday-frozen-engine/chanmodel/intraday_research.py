"""Causal native-Chan intraday reversal research and ex-post extreme scoring.

Only a witnessed local native structure completion may become a research alert.
Session highs/lows are computed after the session exclusively for evaluation;
they never select signals, filter alerts, or supply an executable fill price.
"""
from __future__ import annotations

from collections import Counter
from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
import copy
import math
import re
import statistics
from functools import lru_cache

from .model import Candle, time_value
from .reference_engine import COMMIT, PROFILE as ENGINE_PROFILE, ReferenceSession
from .v2.series import CN, PERIODS, session_closes

PROFILE = 'native_chan_intraday_reversal_causal_v1'


@dataclass(frozen=True)
class IntradayConfig:
    ranks: tuple[int, ...] = (1, 2)
    native_types: tuple[str, ...] = ('1', '1p', '2', '2s', '3a', '3b')
    max_confirmation_delay_minutes: int = 60
    max_pivot_distance_pct: float = 2.0
    same_session_pivot: bool = True

    def __post_init__(self):
        if not self.ranks or any(type(n) is not int or n not in (1, 2) for n in self.ranks):
            raise ValueError('intraday ranks must be a nonempty subset of 1,2')
        if not self.native_types or any(n not in ('1', '1p', '2', '2s', '3a', '3b') for n in self.native_types):
            raise ValueError('unknown native signal type')
        if type(self.max_confirmation_delay_minutes) is not int or self.max_confirmation_delay_minutes < 0:
            raise ValueError('confirmation delay must be a nonnegative integer')
        if (isinstance(self.max_pivot_distance_pct, bool) or
            not math.isfinite(self.max_pivot_distance_pct) or self.max_pivot_distance_pct < 0):
            raise ValueError('pivot distance must be a finite nonnegative percentage')


def _session_date(bar):
    return time_value(bar.closed_at).astimezone(CN).date().isoformat()


def _bar_open_time(bar, period):
    return time_value(bar.closed_at).astimezone(CN) - timedelta(minutes=PERIODS[period])


@lru_cache(maxsize=512)
def _session_calendar(day, period):
    """Immutable native grid shared across bars, without retaining securities."""
    closes=tuple(session_closes(day,period))
    return closes,frozenset(closes)


def _trading_minutes_between(first, last, period):
    start,end=time_value(first).astimezone(CN),time_value(last).astimezone(CN)
    day=start.date();count=0
    while day<=end.date():
        if day.weekday()<5:
            closes,_=_session_calendar(day,period)
            count+=max(0,bisect_right(closes,end)-bisect_right(closes,start))
        day+=timedelta(days=1)
    return count*PERIODS[period]


class IntradayResearchSession:
    """Append-only study state shared by offline replay and live monitoring.

    Callers suppress warm-up notifications and alert only on returned new events.
    A research alert is local structure evidence, not a multi-timeframe proof or
    an order. A-share T+1 eligibility belongs to the execution simulation layer.
    """
    def __init__(self, symbol, period='5m', config=None, source='tdx', adjustment='unadjusted'):
        if not isinstance(symbol,str) or not re.fullmatch(r'(sh|sz|bj)\d{6}',symbol):
            raise ValueError('symbol requires an explicit exchange prefix')
        if period not in ('1m', '5m', '15m', '30m', '60m'):
            raise ValueError('intraday requires native 1m/5m/15m/30m/60m OHLC bars')
        if not source or adjustment not in ('unadjusted', 'qfq', 'hfq'):
            raise ValueError('source and adjustment must be declared')
        self.symbol, self.period, self.source, self.adjustment = symbol, period, source, adjustment
        self.config = config or IntradayConfig()
        self.reference = ReferenceSession(period, observe=True)
        self.events = []
        self.active = {}
        self.confirmed_versions = set()

    @property
    def bars(self):
        return self.reference.bars

    def append(self, bar: Candle):
        if not bar.closed:
            raise ValueError('forming candles are display-only; no intraday alert')
        if bar.closed_at is None or min(bar.open, bar.high, bar.low, bar.close) <= 0:
            raise ValueError('intraday requires positive OHLC and an explicit bar close')
        local = time_value(bar.closed_at).astimezone(CN)
        if local.weekday() >= 5 or local not in _session_calendar(local.date(), self.period)[1]:
            raise ValueError('intraday bar close is outside the CN A-share session grid')
        native = self.reference.append(bar)
        added = []

        def emit(kind, ident, data):
            event = {**data, 'id': self.period + ':' + ident, 'signal_id': ident, 'event': kind,
                     'state': 'local_structure_complete' if kind == 'research_alert' else kind,
                     'symbol': self.symbol, 'period': self.period, 'available_at': bar.pos,
                     'available_time': bar.closed_at, 'observed_index': bar.pos,
                     'observed_at': bar.closed_at, 'profile': PROFILE,
                     'execution_allowed': False}
            self.events.append(copy.deepcopy(event)); added.append(event)

        # Bar-close boundary evidence may revoke an earlier alert. It never
        # rewrites the original alert or claims an executable intrabar stop.
        for ident, previous in list(self.active.items()):
            broken = bar.low < previous['invalidation'] if previous['side'] == 'buy' else bar.high > previous['invalidation']
            if broken:
                emit('invalidated', ident, {**previous, 'invalidation_observed_at': bar.pos,
                     'available_at': bar.pos, 'available_time': bar.closed_at,
                     'invalidation_price': bar.low if previous['side'] == 'buy' else bar.high})
                self.active.pop(ident)
        for event in native:
            ident = event['id']
            if event['event'] in ('withdrawn', 'confirmation_withdrawn') and ident in self.active:
                previous = self.active.pop(ident)
                emit('withdrawn', ident, {**previous, 'available_at': bar.pos,
                     'available_time': bar.closed_at, 'withdrawal_reason': event['event']})

        completions = [e for e in native if e.get('state') == 'structure_complete' and
                       e['event'] in ('appeared', 'reappeared', 'structure_completed')]
        report = self.reference.snapshot(self.symbol, bar.closed_at, self.source, self.adjustment) if completions or (self.active and native) else None
        reviewed = {s['id']: s for s in report['signals']} if report else {}
        if report:
            for ident, previous in list(self.active.items()):
                current=reviewed.get(ident)
                if current is None or current.get('state')!='structure_complete' or not current.get('rule_audit',{}).get('passed'):
                    self.active.pop(ident)
                    emit('withdrawn',ident,{**previous,'withdrawal_reason':'local_geometry_review_no_longer_complete'})
        for event in completions:
            ident = event['id']; key = (ident, event['observed_index'])
            if key in self.confirmed_versions:
                continue
            self.confirmed_versions.add(key)
            anchor = event['anchor']
            if type(anchor) is not int or not 0 <= anchor <= bar.pos:
                raise ValueError('intraday confirmation anchor lies beyond the observed prefix')
            pivot_bar = self.bars[anchor]
            price = pivot_bar.low if event['side'] == 'buy' else pivot_bar.high
            span = self.bars[anchor:bar.pos + 1]
            same_day = _session_date(pivot_bar) == _session_date(bar)
            delay = _trading_minutes_between(pivot_bar.closed_at,bar.closed_at,self.period)
            distance = (bar.close / price - 1) * 100 if event['side'] == 'buy' else (1 - bar.close / price) * 100
            reasons = []
            if event['rank'] not in self.config.ranks: reasons.append('rank_not_selected')
            if event['native_type'] not in self.config.native_types: reasons.append('type_not_selected')
            signal = reviewed.get(ident)
            if not signal or signal.get('state') != 'structure_complete' or not signal.get('rule_audit', {}).get('passed'):
                reasons.append('local_geometry_not_reviewed_complete')
            if self.config.same_session_pivot and not same_day: reasons.append('pivot_from_an_earlier_session')
            if delay > self.config.max_confirmation_delay_minutes: reasons.append('confirmation_delay_exceeds_profile')
            if distance > self.config.max_pivot_distance_pct: reasons.append('confirmation_too_far_from_pivot')
            crossed = any(b.low < price for b in span[1:]) if event['side'] == 'buy' else any(b.high > price for b in span[1:])
            if crossed: reasons.append('pivot_broken_before_confirmation')
            evidence = {'side': event['side'], 'rank': event['rank'], 'native_type': event['native_type'],
                        'anchor': anchor, 'pivot_price': price, 'price': price,
                        'pivot_time': pivot_bar.closed_at, 'invalidation': price,
                        'invalidation_operator': 'lt' if event['side'] == 'buy' else 'gt',
                        'confirmation_delay_bars': bar.pos - anchor,
                        'confirmation_delay_trading_minutes': delay, 'pivot_distance_pct': distance,
                        'confirmation_price': bar.close,
                        'alert_kind': 'bottom_reversal' if event['side'] == 'buy' else 'top_reversal',
                        'definition_mode': 'pinned_native_local_structure',
                        'trade_level': self.period, 'confirm_level': 'native_local_structure',
                        'trigger_level': 'not_proven', 'lower_level_trigger': 'not_proven',
                        'structure_completeness': 'native_local_with_geometry_review',
                        'approximation_loss': ['native local completion is not independently proved multi-timeframe confirmation',
                                               'maximum delay and pivot-distance thresholds are explicit research filters'],
                        'rule_audit': copy.deepcopy(signal.get('rule_audit')) if signal else None}
            if reasons:
                emit('rejected', ident, {**evidence, 'rejection_reasons': reasons})
            else:
                emit('research_alert', ident, evidence)
                self.active[ident] = copy.deepcopy(added[-1])
        return copy.deepcopy(added)

    def snapshot(self):
        return {'schema': 'chanlun.intraday.research.v1', 'profile': PROFILE,
                'algorithm_profile': ENGINE_PROFILE, 'engine_commit': COMMIT,
                'symbol': self.symbol, 'period': self.period, 'source': self.source,
                'adjustment': self.adjustment, 'config': asdict(self.config),
                'processed_bars': len(self.bars), 'latest_bar_at': self.bars[-1].closed_at if self.bars else None,
                'events': copy.deepcopy(self.events), 'active_signals': copy.deepcopy(list(self.active.values())),
                'definition_mode': 'pinned_native_local_structure', 'execution_allowed': False}


def evaluate_intraday(bars, events, period='5m', horizons=(3, 6, 12), slippage_bps=5.0):
    """Score observed research alerts; future extremes appear only in labels.

    Sell rows simulate exiting already T+1-eligible holdings, never a short sell.
    Buy rows do not assume the new A-share holding can be resold the same day.
    """
    if period not in ('1m', '5m', '15m', '30m', '60m'):
        raise ValueError('unsupported intraday evaluation period')
    if not math.isfinite(slippage_bps) or slippage_bps < 0:
        raise ValueError('slippage must be a finite nonnegative number')
    if any(type(h) is not int or h < 1 for h in horizons):
        raise ValueError('forward horizons must be positive integers')
    if any(b.pos != i or not b.closed for i, b in enumerate(bars)):
        raise ValueError('evaluation requires a contiguous closed-bar prefix')
    dates = {}
    times = [time_value(bar.closed_at) for bar in bars]
    session_dates = [moment.astimezone(CN).date().isoformat() for moment in times]
    for i, day in enumerate(session_dates): dates.setdefault(day, []).append(i)
    # Session completeness and oracle extrema depend only on this immutable
    # evaluation input. Computing them once per session changes neither alert
    # selection nor fills and avoids rebuilding a 240-point grid per alert.
    day_evidence = {}
    rows = []
    lifecycle = sorted(events, key=lambda e: e.get('available_at', e.get('observed_index', -1)))
    for event_position, event in enumerate(lifecycle):
        if event.get('event') != 'research_alert': continue
        i = event['available_at']; anchor = event['anchor']; side = event['side']
        if type(i) is not int or type(anchor) is not int or not 0 <= anchor <= i < len(bars):
            raise ValueError('evaluation alert indices violate observed-prefix causality')
        if time_value(event['available_time']) != time_value(bars[i].closed_at):
            raise ValueError('evaluation alert availability differs from the observed close')
        if side not in ('buy', 'sell'): raise ValueError('unknown alert side')
        day = session_dates[i]
        if day not in day_evidence:
            indices=dates[day]
            expected,_=_session_calendar(times[indices[0]].astimezone(CN).date(),period)
            day_evidence[day] = {
                'expected':expected,
                'positions':{moment:n for n,moment in enumerate(expected)},
                'closed':tuple(times[k] for k in indices)==expected,
                'low':min(bars[k].low for k in indices),
                'high':max(bars[k].high for k in indices),
            }
        evidence=day_evidence[day]
        expected_day=evidence['expected']
        closed_session = evidence['closed']
        row = {**copy.deepcopy(event), 'session': day, 'evaluation_state': 'no_same_session_next_bar',
               'fill_price': None, 'fill_time': None, 'daily_extreme': None,
               'daily_extreme_gap_bps': None, 'future_labels': {},
               'session_extreme_state': 'complete_native_session' if closed_session else 'incomplete_native_session',
               'fill_semantics': 'next observed same-session native bar open plus declared slippage',
               'sell_inventory_assumption': 'preexisting_T1_eligible_holdings' if side == 'sell' else None,
               'buy_same_day_resale_allowed': False, 'execution_allowed': False}
        j = i + 1
        if j < len(bars) and session_dates[j] == day:
            expected = expected_day
            n = evidence['positions'].get(times[i])
            if n is None:raise ValueError('alert time is not in the native session grid')
            if n + 1 < len(expected) and times[j] == expected[n + 1]:
                revoked = any(e['event'] in ('invalidated', 'withdrawn') and e.get('signal_id') == event.get('signal_id') and
                              e.get('available_at', -1) <= i for e in lifecycle[event_position + 1:])
                if revoked:
                    row['evaluation_state'] = 'revoked_before_fill'
                elif bars[i].volume is None or bars[i].volume <= 0:
                    row['evaluation_state'] = 'unavailable_prior_volume'
                elif side == 'buy' and bars[j].open < event['invalidation']:
                    row['evaluation_state'] = 'opening_gap_invalidates_buy'
                else:
                    sign = 1 if side == 'buy' else -1
                    fill = bars[j].open * (1 + sign * slippage_bps / 10000)
                    row.update(evaluation_state='next_open_hypothesis', fill_index=j, fill_price=fill,
                               fill_time=_bar_open_time(bars[j], period).isoformat(), fill_bar_close=bars[j].closed_at)
                    if closed_session:
                        extreme = evidence['low'] if side == 'buy' else evidence['high']
                        gap = (fill / extreme - 1) * 10000 if side == 'buy' else (1 - fill / extreme) * 10000
                        row.update(daily_extreme=extreme, daily_extreme_gap_bps=gap,
                                   oracle_used_only_for_evaluation=True)
                    for h in horizons:
                        end = j + h - 1
                        if end >= len(bars) or session_dates[end] != day:
                            row['future_labels'][str(h)] = {'state': 'insufficient_same_session_future'}
                            continue
                        window = bars[j:end + 1]
                        expected_window=expected_day[n+1:n+1+h]
                        if tuple(times[j:end+1]) != expected_window:
                            row['future_labels'][str(h)] = {'state':'missing_native_bar_in_forward_window'}
                            continue
                        row['future_labels'][str(h)] = {
                            'state': 'observed', 'end_time': bars[end].closed_at,
                            'directional_close_return': (bars[end].close / fill - 1) * sign,
                            'favorable_excursion': (max(b.high for b in window) / fill - 1) if side == 'buy' else (1 - min(b.low for b in window) / fill),
                            'adverse_excursion': (min(b.low for b in window) / fill - 1) if side == 'buy' else (1 - max(b.high for b in window) / fill)}
            else:
                row['evaluation_state'] = 'missing_next_native_bar'
        rows.append(row)
    summary = {'alerts': len(rows), 'by_state': dict(Counter(r['evaluation_state'] for r in rows)),
               'by_side': dict(Counter(r['side'] for r in rows)),
               'scope': 'next-open directional event study; not a same-day round-trip A-share portfolio',
               'execution_allowed': False}
    for side in ('buy', 'sell'):
        gaps = [r['daily_extreme_gap_bps'] for r in rows if r['side'] == side and r['daily_extreme_gap_bps'] is not None]
        summary[side] = {'closed_session_scored': len(gaps),
                         'median_gap_to_session_extreme_bps': statistics.median(gaps) if gaps else None,
                         'within_50bps_of_session_extreme': sum(x <= 50 for x in gaps),
                         'within_100bps_of_session_extreme': sum(x <= 100 for x in gaps)}
    summary['forward_directional_outcomes']={}
    for h in horizons:
        values=[r['future_labels'][str(h)]['directional_close_return'] for r in rows
                if r['future_labels'].get(str(h),{}).get('state')=='observed']
        summary['forward_directional_outcomes'][str(h)]={
            'observed':len(values),'missing':len(rows)-len(values),
            'mean_directional_close_return':statistics.fmean(values) if values else None,
            'positive_fraction':sum(x>0 for x in values)/len(values) if values else None,
            'semantics':'event direction label, not realized portfolio win rate'}
    return {'profile': PROFILE + ':event_evaluation', 'period': period,
            'settings':{'horizons':list(horizons),'slippage_bps':slippage_bps}, 'rows': rows, 'summary': summary,
            'session_extremes_are_ex_post_labels': True, 'execution_allowed': False}
