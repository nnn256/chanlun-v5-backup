"""Causal daily price/volume research states, independent of Chan confirmation.

The states are observations, not calibrated forecasts or executable orders.
Each closed bar is admitted once.  Fixed rolling windows, monotonic extrema
queues and a bounded cost histogram avoid rescanning the complete history.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import copy
import hashlib
import json
import math
from typing import Mapping

VERSION = 'causal_regime_research_v1.1'
DEFINITION_MODE = 'causal_price_volume_research'
CN = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class RegimeConfig:
    ma_fast: int = 20
    ma_slow: int = 60
    slope_window: int = 5
    range_window: int = 20
    pressure_window: int = 5
    volume_window: int = 20
    cost_window: int = 60
    base_min_bars: int = 3
    watch_max_bars: int = 90
    drawdown_threshold: float = .12
    runup_threshold: float = .12
    near_extreme_pct: float = .04
    base_range_pct: float = .15
    weakening_ratio: float = .85
    base_return_floor: float = -.015
    breakout_buffer_pct: float = .002
    cost_bin_pct: float = .01

    def __post_init__(self):
        for key in ('ma_fast', 'ma_slow', 'slope_window', 'range_window',
                    'pressure_window', 'volume_window', 'cost_window',
                    'base_min_bars', 'watch_max_bars'):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= 2000:
                raise ValueError(f'{key} must be an integer in 1..2000')
        if not 1 < self.ma_fast < self.ma_slow:
            raise ValueError('moving averages require 1 < ma_fast < ma_slow')
        if self.watch_max_bars <= self.base_min_bars:
            raise ValueError('watch_max_bars must exceed base_min_bars')
        for key in ('drawdown_threshold', 'runup_threshold', 'near_extreme_pct',
                    'base_range_pct', 'weakening_ratio', 'breakout_buffer_pct',
                    'cost_bin_pct'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(f'{key} must be finite and strictly between zero and one')
        if not -.5 < self.base_return_floor <= 0:
            raise ValueError('base_return_floor must be in (-.5, 0]')


def _config(value):
    if value is None:
        return RegimeConfig()
    if isinstance(value, RegimeConfig):
        return value
    if not isinstance(value, Mapping):
        raise ValueError('config must be a mapping or RegimeConfig')
    return RegimeConfig(**dict(value))


def _number(value, name, *, nullable=False):
    if value is None and nullable:
        return None
    if value is None or isinstance(value, bool):
        raise ValueError(f'{name} must be a finite number')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name} must be a finite number') from exc
    if not math.isfinite(result):
        raise ValueError(f'{name} must be a finite number')
    return result


def _timestamp(value, name='closed_at'):
    if isinstance(value, datetime):
        point = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError(f'{name} must be a valid timestamp')
        try:
            point = datetime.fromtimestamp(value, timezone.utc)
        except (OSError, ValueError, OverflowError) as exc:
            raise ValueError(f'{name} must be a valid timestamp') from exc
    elif isinstance(value, str):
        try:
            point = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError(f'{name} must be an ISO timestamp with timezone') from exc
    else:
        raise ValueError(f'{name} requires a timestamp')
    if point.tzinfo is None or point.utcoffset() is None:
        raise ValueError(f'{name} must have an explicit timezone')
    return point.astimezone(CN)


def _closed(value):
    if value is True or value == 1 and type(value) in (int, float):
        return True
    if value is False or value == 0 and type(value) in (int, float):
        return False
    if isinstance(value, str):
        if value.strip().lower() in ('true', '1'):
            return True
        if value.strip().lower() in ('false', '0'):
            return False
    raise ValueError('is_closed must explicitly be true or false')


def _bar(row):
    if not isinstance(row, Mapping):
        raise ValueError('bar must be a mapping')
    stamp = row.get('closed_at', row.get('time', row.get('timestamp')))
    moment = _timestamp(stamp)
    values = {name: _number(row.get(name), name) for name in ('open', 'high', 'low', 'close')}
    if min(values.values()) <= 0:
        raise ValueError('OHLC prices must be positive')
    if values['high'] < max(values.values()) or values['low'] > min(values.values()):
        raise ValueError('invalid OHLC envelope')
    volume = _number(row.get('volume'), 'volume', nullable=True)
    if volume is not None and volume < 0:
        raise ValueError('volume must not be negative')
    flag = row['is_closed'] if 'is_closed' in row else row.get('closed', True)
    source_index = None
    for field in ('source_index', 'pos', 'index'):
        if field in row:
            source_index = row[field]
            if type(source_index) is not int or source_index < 0:
                raise ValueError(f'{field} must be a nonnegative integer')
            break
    return {'closed_at': moment.isoformat(), 'date': moment.date().isoformat(),
            'is_closed': _closed(flag), 'volume': volume, 'source_index': source_index,
            **values}, moment


class _Window:
    def __init__(self, width, fields=1):
        self.width, self.fields = width, fields
        self.rows = deque()
        self.totals = [0.] * fields
        self.missing = 0

    def append(self, values):
        if self.fields == 1 and values is not None:
            values = (values,)
        self.rows.append(values)
        if values is None:
            self.missing += 1
        else:
            for i, value in enumerate(values):
                self.totals[i] += value
        if len(self.rows) > self.width:
            old = self.rows.popleft()
            if old is None:
                self.missing -= 1
            else:
                for i, value in enumerate(old):
                    self.totals[i] -= value

    @property
    def ready(self):
        return len(self.rows) == self.width and not self.missing

    def mean(self):
        return self.totals[0] / self.width if self.ready else None


class _Extrema:
    def __init__(self, width):
        self.width = width
        self.high = deque()
        self.low = deque()

    def append(self, index, high, low):
        while self.high and self.high[-1][1] <= high:
            self.high.pop()
        while self.low and self.low[-1][1] >= low:
            self.low.pop()
        self.high.append((index, high))
        self.low.append((index, low))
        cutoff = index - self.width
        while self.high[0][0] <= cutoff:
            self.high.popleft()
        while self.low[0][0] <= cutoff:
            self.low.popleft()


class _CostProxy:
    """Volume at one representative price per bar; never a held-share ledger."""
    def __init__(self, config):
        self.width = config.cost_window
        self.step = math.log1p(config.cost_bin_pct)
        self.rows = deque()
        self.histogram = defaultdict(float)
        self.volume = 0.
        self.price_volume = 0.
        self.observations = 0

    def append(self, row):
        volume = row['volume']
        representative = (row['high'] + row['low'] + row['close']) / 3
        bucket = math.floor(math.log(representative) / self.step)
        item = None if volume is None else (bucket, volume, representative * volume)
        self.rows.append(item)
        if item is not None:
            self.histogram[bucket] += volume
            self.volume += volume
            self.price_volume += item[2]
            self.observations += 1
        if len(self.rows) > self.width:
            old = self.rows.popleft()
            if old is not None:
                key, old_volume, old_pv = old
                self.histogram[key] -= old_volume
                if self.histogram[key] <= max(1e-8, old_volume * 1e-12):
                    self.histogram.pop(key, None)
                self.volume -= old_volume
                self.price_volume -= old_pv
                self.observations -= 1

    def summary(self, close):
        value = {'kind': 'rolling_traded_volume_cost_proxy', 'not_actual_chips': True,
                 'window': self.width, 'observed_bars': self.observations,
                 'coverage_bars': len(self.rows), 'median': None, 'p10': None, 'p90': None,
                 'weighted_mean': None, 'central_80_price_band_width_pct': None,
                 'estimated_traded_volume_below_close_ratio': None,
                 'assumptions': 'volume is allocated at (high+low+close)/3; no holder identity, turnover decay or cost-basis data'}
        if self.volume <= 0 or self.observations != len(self.rows):
            value['state'] = 'unavailable' if self.volume <= 0 else 'partial_volume_coverage'
            return value
        ordered = sorted(self.histogram.items())
        quantiles = {}
        acc = below = 0.
        for key, volume in ordered:
            center = math.exp((key + .5) * self.step)
            acc += volume
            below += volume if center <= close else 0.
            for q in (.1, .5, .9):
                if q not in quantiles and acc >= q * self.volume:
                    quantiles[q] = center
        for q, name in ((.1, 'p10'), (.5, 'median'), (.9, 'p90')):
            value[name] = quantiles.get(q, math.exp((ordered[-1][0] + .5) * self.step))
        value.update(state='available_proxy', weighted_mean=self.price_volume / self.volume,
                     central_80_price_band_width_pct=(value['p90'] - value['p10']) / value['median'],
                     estimated_traded_volume_below_close_ratio=max(0., min(1., below / self.volume)))
        return value


class _Context:
    """Same-session context only, with availability known before the bar close."""
    def __init__(self, context=None):
        self.by_date = defaultdict(list)
        if context is None:
            return
        if isinstance(context, Mapping):
            if 'rows' in context:
                rows = context['rows']
            else:
                rows = [{**dict(value), 'date': key} for key, value in context.items()
                        if isinstance(value, Mapping)]
        else:
            rows = context
        if not isinstance(rows, (list, tuple)):
            raise ValueError('context must be date-keyed mappings or a rows sequence')
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError('context row must be a mapping')
            raw_date = row.get('date', row.get('trade_date'))
            if raw_date is None and row.get('closed_at') is not None:
                raw_date = _timestamp(row['closed_at'], 'context.closed_at').date().isoformat()
            try:
                session = date.fromisoformat(str(raw_date)).isoformat()
            except ValueError as exc:
                raise ValueError('context requires an explicit YYYY-MM-DD session date') from exc
            self.by_date[session].append(dict(row))

    def features(self, row, moment):
        source_rows = list(self.by_date.get(row['date'], []))
        embedded = row.get('context')
        if isinstance(embedded, Mapping):
            source_rows.append(embedded)
        empty = lambda: {'state': 'unavailable', 'reason': 'no_session_context'}
        flow, breadth = empty(), empty()
        selected_at = {'flow': None, 'breadth': None}
        for item in source_rows:
            for kind, fields in (('flow', ('net_flow', 'net_flow_yuan')),
                                 ('breadth', ('up_count', 'down_count'))):
                nested = item.get(kind)
                values = nested if isinstance(nested, Mapping) else item
                if not any(field in values for field in fields):
                    continue
                reason = None
                available = values.get('available_at', item.get('available_at'))
                source = values.get('source', item.get('source'))
                instant = None
                try:
                    instant = _timestamp(available, 'context.available_at')
                except ValueError:
                    reason = 'missing_or_invalid_availability_time'
                if instant is not None and instant > moment:
                    reason = 'not_available_at_bar_close'
                if not source and reason is None:
                    reason = 'missing_source'
                current = flow if kind == 'flow' else breadth
                if reason:
                    if current['state'] != 'available':
                        current.update(reason=reason)
                    continue
                if selected_at[kind] is not None and instant < selected_at[kind]:
                    continue
                try:
                    if kind == 'flow':
                        net = _number(values.get('net_flow', values.get('net_flow_yuan')), 'context.net_flow')
                        current = {'state': 'available', 'net_flow': net, 'source': str(source),
                                   'unit': values.get('unit', 'provider_native_unspecified'),
                                   'available_at': instant.isoformat(), 'date': row['date'],
                                   'used_by_state_rules': False}
                    else:
                        up = _number(values.get('up_count'), 'context.up_count')
                        down = _number(values.get('down_count'), 'context.down_count')
                        if up < 0 or down < 0 or up + down <= 0 or not up.is_integer() or not down.is_integer():
                            raise ValueError('breadth counts must be nonnegative integers with nonzero total')
                        current = {'state': 'available', 'up_count': int(up), 'down_count': int(down),
                                   'up_ratio': up / (up + down), 'source': str(source),
                                   'scope': values.get('scope', item.get('scope', 'provider_unspecified_scope')),
                                   'available_at': instant.isoformat(), 'date': row['date'],
                                   'used_by_state_rules': False}
                except ValueError:
                    if (flow if kind == 'flow' else breadth)['state'] != 'available':
                        (flow if kind == 'flow' else breadth).update(reason='invalid_context_value')
                    continue
                selected_at[kind] = instant
                if kind == 'flow':
                    flow = current
                else:
                    breadth = current
        return flow, breadth


RULES = {
    'bottom_candidate': 'drawdown from trailing slow-window high >= threshold; close near trailing low; declining return slows or recent down-day volume weakens versus preceding equal window',
    'basing': 'an earlier bottom candidate survives its low for base_min_bars and current range compresses; recent return is no worse than base_return_floor',
    'breakout_confirmation': 'a prior basing observation exists; current close exceeds prior range-window high with buffer, is above fast MA, and fast MA slope is nonnegative',
    'top_candidate': 'mirror: trailing-low runup >= threshold; close near trailing high; rising return slows or recent up-day volume weakens',
    'topping': 'earlier top candidate survives its high for base_min_bars; range compresses and recent return is no greater than -base_return_floor',
    'breakdown': 'mirror: prior topping exists and close breaks prior range-window low with buffer, below fast MA with nonpositive slope; or prior uptrend breaks trailing support',
    'trend': 'close/fast/slow MAs align and MAs move in the same direction; after a confirmed break, close and fast MA slope may identify early recovery/deterioration',
    'invalidation': 'strict intrabar low below bottom candidate floor or high above top candidate ceiling, observed only when that bar closes',
}


class RegimeSession:
    def __init__(self, symbol='', config=None, context=None):
        self.symbol = str(symbol)
        self.config = _config(config)
        self.context = _Context(context)
        c = self.config
        self.series = []
        self.events = []
        self._fast = _Window(c.ma_fast)
        self._slow = _Window(c.ma_slow)
        self._volume = _Window(c.volume_window)
        self._recent = _Window(c.pressure_window, 4)
        self._preceding = _Window(c.pressure_window, 4)
        self._delay = deque()
        self._closes = deque(maxlen=c.pressure_window * 2 + 1)
        self._fast_history = deque(maxlen=c.slope_window + 1)
        self._range = _Extrema(c.range_window)
        self._trend_range = _Extrema(c.ma_slow)
        self._cost = _CostProxy(c)
        self._last_time = None
        self._open_time = None
        self._previous_close = None
        self._previous_fast = None
        self._previous_slow = None
        self._bottom = None
        self._top = None
        self._digest = hashlib.sha256()
        self.config_sha256 = hashlib.sha256(json.dumps(asdict(c), sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def _event(self, name, row, state, *, watch=None, rules=None):
        index = len(self.series)
        anchor = watch['index'] if watch else index
        stamp = watch['time'] if watch else row['closed_at']
        side = ('risk' if name.endswith(('_invalidated','_expired')) else
                'buy' if name.startswith(('bottom', 'basing', 'breakout', 'uptrend')) else
                'sell' if name.startswith(('top', 'topping', 'breakdown', 'downtrend')) else 'risk')
        invalidation = self._boundary(watch)
        event = {'id': f'{VERSION}:{self.symbol}:{index}:{name}', 'event': name, 'state': state,
                 'side': side, 'observed_index': index, 'observed_at': row['closed_at'],
                 'anchor_index': anchor, 'anchor_time': stamp, 'price': row['close'],
                 'invalidation': invalidation, 'rules': dict(rules or {}),
                 'definition_mode': DEFINITION_MODE, 'execution_allowed': False}
        self.events.append(event)
        return name

    @staticmethod
    def _boundary(watch):
        if not watch:
            return None
        bottom = watch['side'] == 'bottom'
        return {'operator': '<' if bottom else '>', 'price': watch['boundary'],
                'reference': 'bottom_candidate_low' if bottom else 'top_candidate_high',
                'candidate_index': watch['index'], 'candidate_time': watch['time']}

    def append(self, raw_row):
        row, moment = _bar(raw_row)
        if self._last_time is not None and moment <= self._last_time:
            raise ValueError('closed bar timestamps must strictly increase')
        if self._open_time is not None and moment != self._open_time:
            raise ValueError('finalize the pending open bar before appending a later interval')
        if row['source_index'] is not None and row['source_index'] != len(self.series):
            raise ValueError('source indices must form a contiguous prefix without gaps')
        if not row['is_closed']:
            self._open_time = moment
            return None
        # Validate embedded context before mutating rolling state.
        if 'context' in raw_row:
            row['context'] = raw_row['context']
        elif any(field in raw_row for field in ('net_flow', 'net_flow_yuan', 'up_count', 'down_count')):
            row['context'] = raw_row
        flow, breadth = self.context.features(row, moment)
        c = self.config
        index = len(self.series)
        previous_state = self.series[-1]['state'] if self.series else 'warmup'
        prior_resistance = self._range.high[0][1] if self._range.high and index >= c.range_window else None
        prior_support = self._range.low[0][1] if self._range.low and index >= c.range_window else None
        previous_close = self._previous_close
        close, volume = row['close'], row['volume']
        clv = (2 * close - row['high'] - row['low']) / (row['high'] - row['low']) if row['high'] != row['low'] else 0.
        movement = close - previous_close if previous_close is not None else 0.
        item = None if volume is None else (volume, volume if movement < 0 else 0., volume if movement > 0 else 0., clv * volume)
        self._delay.append(item)
        self._recent.append(item)
        if len(self._delay) > c.pressure_window:
            self._preceding.append(self._delay.popleft())
        self._fast.append(close)
        self._slow.append(close)
        self._volume.append(volume)
        self._closes.append(close)
        fast, slow = self._fast.mean(), self._slow.mean()
        self._fast_history.append(fast)
        slope = (fast / self._fast_history[0] - 1 if len(self._fast_history) == c.slope_window + 1
                 and self._fast_history[0] is not None else None)
        self._range.append(index, row['high'], row['low'])
        self._trend_range.append(index, row['high'], row['low'])
        self._cost.append(row)
        trailing_high, trailing_low = self._trend_range.high[0][1], self._trend_range.low[0][1]
        drawdown, runup = close / trailing_high - 1, close / trailing_low - 1
        range_pct = self._range.high[0][1] / self._range.low[0][1] - 1
        recent_return = preceding_return = None
        if len(self._closes) == c.pressure_window * 2 + 1:
            middle = self._closes[c.pressure_window]
            recent_return = close / middle - 1
            preceding_return = middle / self._closes[0] - 1
        pressure = None
        if self._recent.ready and self._recent.totals[0] > 0:
            pressure = max(-1., min(1., self._recent.totals[3] / self._recent.totals[0]))
        weak_sell_volume = bool(self._recent.ready and self._preceding.ready and self._preceding.totals[1] > 0
                                and self._recent.totals[1] <= self._preceding.totals[1] * c.weakening_ratio)
        weak_buy_volume = bool(self._recent.ready and self._preceding.ready and self._preceding.totals[2] > 0
                               and self._recent.totals[2] <= self._preceding.totals[2] * c.weakening_ratio)
        weak_decline = bool(recent_return is not None and preceding_return < 0 and recent_return > preceding_return)
        weak_rise = bool(recent_return is not None and preceding_return > 0 and recent_return < preceding_return)
        ready = slow is not None and slope is not None
        bottom_rule = bool(ready and drawdown <= -c.drawdown_threshold and close / trailing_low - 1 <= c.near_extreme_pct and (weak_sell_volume or weak_decline))
        top_rule = bool(ready and runup >= c.runup_threshold and trailing_high / close - 1 <= c.near_extreme_pct and (weak_buy_volume or weak_rise))
        rules = {'history_ready': ready, 'near_trailing_low': close / trailing_low - 1 <= c.near_extreme_pct,
                 'near_trailing_high': trailing_high / close - 1 <= c.near_extreme_pct,
                 'weakening_sell_volume': weak_sell_volume, 'weakening_buy_volume': weak_buy_volume,
                 'weakening_decline': weak_decline, 'weakening_rise': weak_rise,
                 'bottom_candidate': bottom_rule, 'top_candidate': top_rule,
                 'basing': False, 'topping': False, 'breakout_confirmation': False, 'breakdown': False}
        names = []
        for attr, side in (('_bottom', 'bottom'), ('_top', 'top')):
            watch = getattr(self, attr)
            if not watch:
                continue
            violated = row['low'] < watch['boundary'] if side == 'bottom' else row['high'] > watch['boundary']
            if violated:
                names.append(self._event(side + '_invalidated', row, 'invalidated', watch=watch))
                setattr(self, attr, None)
            elif index - watch['index'] > c.watch_max_bars:
                names.append(self._event(side + '_expired', row, 'expired', watch=watch))
                setattr(self, attr, None)
        for attr, side, passed, boundary in (('_bottom', 'bottom', bottom_rule, trailing_low),
                                              ('_top', 'top', top_rule, trailing_high)):
            if passed and getattr(self, attr) is None:
                watch = {'side': side, 'index': index, 'time': row['closed_at'], 'boundary': boundary,
                         'phase': 'candidate', 'base_seen': None, 'break_index': None}
                setattr(self, attr, watch)
                names.append(self._event(side + '_candidate', row, side + '_candidate', watch=watch, rules=rules))
        base, top = self._bottom, self._top
        if base and base['phase'] != 'broken_out':
            rules['basing'] = bool(index - base['index'] >= c.base_min_bars and range_pct <= c.base_range_pct
                                   and recent_return is not None and recent_return >= c.base_return_floor)
            rules['breakout_confirmation'] = bool(base['base_seen'] is not None and index > base['base_seen']
                and prior_resistance is not None and close > prior_resistance * (1 + c.breakout_buffer_pct)
                and fast is not None and close > fast and slope is not None and slope >= 0)
            if rules['breakout_confirmation']:
                base['phase'], base['break_index'] = 'broken_out', index
            elif rules['basing']:
                base['base_seen'] = index if base['base_seen'] is None else base['base_seen']
                base['phase'] = 'basing'
        if top and top['phase'] != 'broken_down':
            rules['topping'] = bool(index - top['index'] >= c.base_min_bars and range_pct <= c.base_range_pct
                                    and recent_return is not None and recent_return <= -c.base_return_floor)
            rules['breakdown'] = bool(top['base_seen'] is not None and index > top['base_seen']
                and prior_support is not None and close < prior_support * (1 - c.breakout_buffer_pct)
                and fast is not None and close < fast and slope is not None and slope <= 0)
            if rules['breakdown']:
                top['phase'], top['break_index'] = 'broken_down', index
            elif rules['topping']:
                top['base_seen'] = index if top['base_seen'] is None else top['base_seen']
                top['phase'] = 'topping'
        direct_breakdown = bool(ready and previous_state in ('uptrend', 'breakout_confirmation')
            and prior_support is not None and close < prior_support * (1 - c.breakout_buffer_pct) and close < fast)
        rules['breakdown'] = rules['breakdown'] or direct_breakdown
        strict_up = bool(ready and close > fast > slow and self._previous_fast is not None
                         and fast > self._previous_fast and self._previous_slow is not None and slow >= self._previous_slow)
        strict_down = bool(ready and close < fast < slow and self._previous_fast is not None
                           and fast < self._previous_fast and self._previous_slow is not None and slow <= self._previous_slow)
        recovering = bool(base and base['phase'] == 'broken_out' and slope is not None and slope > 0 and close > fast)
        deteriorating = bool(top and top['phase'] == 'broken_down' and slope is not None and slope < 0 and close < fast)
        if not ready:
            state = 'warmup'
        elif rules['breakout_confirmation']:
            state = 'breakout_confirmation'
        elif rules['breakdown']:
            state = 'breakdown'
        elif rules['basing']:
            state = 'basing'
        elif rules['topping']:
            state = 'topping'
        elif 'bottom_candidate' in names:
            state = 'bottom_candidate'
        elif 'top_candidate' in names:
            state = 'top_candidate'
        elif strict_up or recovering:
            state = 'uptrend'
        elif strict_down or deteriorating:
            state = 'downtrend'
        else:
            state = 'neutral'
        invalidation_watch = (base if state in ('bottom_candidate', 'basing', 'breakout_confirmation', 'uptrend') else
                              top if state in ('top_candidate', 'topping', 'breakdown', 'downtrend') else None)
        if state != previous_state and state not in ('warmup', 'neutral') and state not in names:
            names.append(self._event(state, row, state, watch=invalidation_watch, rules=rules))
        volume_average = self._volume.mean()
        features = {'ma_fast': fast, 'ma_slow': slow, 'ma_fast_window': c.ma_fast,
                    'ma_slow_window': c.ma_slow, 'ma20': fast if c.ma_fast == 20 else None,
                    'ma60': slow if c.ma_slow == 60 else None, 'ma_fast_slope': slope,
                    'prior_resistance': prior_resistance, 'prior_support': prior_support,
                    'trailing_high': trailing_high, 'trailing_low': trailing_low,
                    'drawdown': drawdown, 'runup': runup, 'range_pct': range_pct,
                    'recent_return': recent_return, 'preceding_return': preceding_return,
                    'volume_ratio': volume / volume_average if volume is not None and volume_average and volume_average > 0 else None,
                    'clv_pressure_proxy': {'kind': 'price_volume_pressure_proxy', 'not_main_fund_flow': True,
                                           'value': pressure, 'window': c.pressure_window,
                                           'state': 'available_proxy' if pressure is not None else 'unavailable'},
                    'cost_distribution_proxy': self._cost.summary(close),
                    'actual_fund_flow': flow, 'breadth': breadth}
        result = {'index': index, 'closed_at': row['closed_at'], 'date': row['date'], 'state': state,
                  'close': close, 'features': features, 'rules': rules, 'events': names,
                  'invalidation': self._boundary(invalidation_watch), 'evidence_available_at': row['closed_at'],
                  'definition_mode': DEFINITION_MODE, 'execution_allowed': False}
        self.series.append(result)
        digest_row = [row[key] for key in ('closed_at', 'open', 'high', 'low', 'close', 'volume')]
        self._digest.update(json.dumps(digest_row, allow_nan=False, separators=(',', ':')).encode() + b'\n')
        self._last_time, self._open_time = moment, None
        self._previous_close, self._previous_fast, self._previous_slow = close, fast, slow
        return copy.deepcopy(result)

    def snapshot(self, *, include_series=True):
        result = {'version': VERSION, 'symbol': self.symbol, 'config': asdict(self.config),
                'config_sha256': self.config_sha256,
                'events': copy.deepcopy(self.events), 'latest': copy.deepcopy(self.series[-1]) if self.series else None,
                'as_of': self.series[-1]['closed_at'] if self.series else None,
                'rule_definitions': dict(RULES), 'execution_allowed': False,
                'definition_mode': DEFINITION_MODE,
                'provenance': {'closed_bars': len(self.series), 'input_sha256': self._digest.hexdigest(),
                               'open_bar_excluded': self._open_time is not None,
                               'processing': 'append-only; rolling windows; no full-history recomputation on append',
                               'context_alignment': 'same session date; source and available_at required; availability must not exceed bar close',
                               'context_changes_state_rules': False, 'probability_calibrated': False},
                'approximation_loss': ['regime rules are price-volume research proxies, independent of strict Chan structure confirmation',
                                       'cost proxy is recent traded volume at representative price, not held-share chips or a holder cost basis',
                                       'CLV pressure is not actual main-fund flow; missing/future context stays unavailable',
                                       'no calibrated probability or guarantee of a subsequent price rise; daily states are first available after that close']}
        if include_series:
            result['series']=copy.deepcopy(self.series)
        return result


def analyze_regimes(rows, symbol='', config=None, context=None):
    """Analyze one supplied ordered history using exactly the incremental path."""
    session = RegimeSession(symbol=symbol, config=config, context=context)
    for row in rows:
        session.append(row)
    return session.snapshot()
