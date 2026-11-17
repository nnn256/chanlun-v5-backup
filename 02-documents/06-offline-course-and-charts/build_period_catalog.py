"""Explicit synthetic charts for all common sampling periods and structure ranks.

Minute and long-term sources are separate teaching experiments. Calendar
aggregation is complete against this stated weekday-only synthetic calendar;
it does not assert a real exchange holiday calendar or a cross-group identity.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'engine'))

from chanmodel.model import Candle, Config
from chanmodel.structure import merge_bars, fractals_at, strokes_at
from chanmodel.segments import build_segments
from chanmodel.signals import macd, attach_ranges
from chanmodel.v2.recursive import base_units, build_hierarchy, audit_hierarchy
from chanmodel.v2.divergence import compare_divergences, make_signals
from chanmodel.v2.series import CN, derive_series
from run_multiframe import make_demo_series

CONFIG=Config(stroke_mode='strict',second_policy='conservative',third_boundary='strict_outside',max_depth=3)
ORDER=('1m','5m','15m','30m','60m','day','week','month','quarter','year')
LABELS={'1m':'1分钟','5m':'5分钟','15m':'15分钟','30m':'30分钟','60m':'60分钟',
        'day':'日线','week':'周线','month':'月线','quarter':'季线','year':'年线'}
ROLES={
    '1m':'更细的触发观察；噪声多，不能单独定义高级别反转。',
    '5m':'短周期结构与局部确认；先检查所属操作级背景。',
    '15m':'日内结构观察；与更高周期配合，不预设固定倍数对应。',
    '30m':'操作级结构示例；中枢和走势关系要先明确。',
    '60m':'较大的日内波动框架；内部小级别回调不等于本级别终结。',
    'day':'较长背景和波段结构；低级别只帮助确认时点。',
    'week':'多日结构背景；结构秩仍与周期名称分开。',
    'month':'长期结构与历史位置；确认更慢，所需历史更长。',
    'quarter':'跨季度背景；样本少时不能强行画完整中枢。',
    'year':'多年历史背景；几根年度K线通常不足以确认笔和线段。',
}


def long_daily_bars(count=1800):
    current=date(2018,1,2);result=[]
    while len(result)<count:
        if current.weekday()<5:
            i=len(result)
            close=100+.012*i+20*math.sin(i/150)+12*math.sin(i/35)+3*math.sin(i/6)
            prior=result[-1].close if result else close-.15
            open_=prior+.05*math.sin(i/1.7)
            high=max(open_,close)+.4+.08*(1+math.sin(i/3))
            low=min(open_,close)-.4-.08*(1+math.cos(i/3))
            closed=datetime.combine(current,time(15,0),CN).isoformat()
            result.append(Candle(i,round(open_,6),round(high,6),round(low,6),round(close,6),closed,
                                 float(10000+(i*37)%2000),True))
        current+=timedelta(days=1)
    return tuple(result)


def day_value(bar):
    return datetime.fromisoformat(bar.closed_at).astimezone(CN).date()


def bounds(day,period):
    if period=='week':
        start=day-timedelta(days=day.weekday());end=start+timedelta(days=6)
    elif period=='month':
        start=day.replace(day=1);end=day.replace(day=calendar.monthrange(day.year,day.month)[1])
    elif period=='quarter':
        first=(day.month-1)//3*3+1
        start=date(day.year,first,1);last=first+2
        end=date(day.year,last,calendar.monthrange(day.year,last)[1])
    elif period=='year':
        start=date(day.year,1,1);end=date(day.year,12,31)
    else:raise ValueError('calendar period must be week/month/quarter/year')
    return start,end


def weekdays(start,end):
    result=[]
    while start<=end:
        if start.weekday()<5:result.append(start)
        start+=timedelta(days=1)
    return result


def aggregate_calendar(source,period):
    groups=defaultdict(list)
    for bar in source:groups[bounds(day_value(bar),period)].append(bar)
    bars=[];lineage=[];excluded=[]
    for (start,end),parts in sorted(groups.items()):
        expected=weekdays(start,end)
        observed=[day_value(bar) for bar in parts]
        if expected!=observed:
            excluded.append({'start':start.isoformat(),'end':end.isoformat(),'observed_daily_bars':len(parts),
                             'expected_daily_bars':len(expected),'reason':'incomplete_synthetic_weekday_bucket'})
            continue
        index=len(bars)
        bars.append(Candle(index,parts[0].open,max(b.high for b in parts),min(b.low for b in parts),
                           parts[-1].close,parts[-1].closed_at,math.fsum(b.volume for b in parts),True))
        lineage.append({'index':index,'source_start':parts[0].pos,'source_end':parts[-1].pos,
                        'source_count':len(parts),'calendar_start':start.isoformat(),'calendar_end':end.isoformat(),
                        'calendar':'synthetic_weekdays_without_exchange_holidays','complete':True})
    return tuple(bars),{'rule':'complete_calendar_bucket_OHLCV','calendar':'synthetic_weekdays_without_exchange_holidays',
                        'source_period':'day','source_group':'daily_source','lineage':lineage,
                        'excluded_partial_buckets':excluded,'missing_children_filled':False}


def analyze_sequence(bars,period,max_rank=3):
    """Compute structure without pretending week/month is a day sampling label."""
    if not bars:raise ValueError('need at least one completed candle')
    bars=list(bars);as_of=len(bars)-1
    merged=merge_bars(bars,CONFIG);fractals=fractals_at(merged)
    strokes,rejections=strokes_at(fractals,CONFIG)
    histogram=macd(bars,CONFIG);segments=build_segments(strokes,0)
    attach_ranges(segments,bars,histogram)
    children=base_units(segments,as_of);hierarchy=build_hierarchy(children,max_rank,as_of)
    audit=audit_hierarchy(hierarchy,as_of)
    if audit['errors']:raise ValueError('recursive certificate error')
    comparisons=[];signals=[]
    for layer in hierarchy['levels']:
        comp=compare_divergences(children,layer['centers'],bars,histogram,layer['rank'],as_of)
        points=make_signals(children,layer['centers'],comp,bars,layer['rank'],histogram,
                            second_policy='conservative',third_boundary='strict_outside')
        comparisons.extend(comp);signals.extend(points)
        children=layer['completed_types']
    return {'schema':'chanlun.period_catalog.structure.v1','period':period,'sampling_period':period,
            'as_of':as_of,'as_of_time':bars[-1].closed_at,'input_count':len(bars),
            'base':{'merged':merged,'fractals':fractals,'strokes':strokes,'segments':segments,
                    'stroke_rejections':rejections},
            'hierarchy':hierarchy,'signals':signals,'divergence_comparisons':comparisons,
            'certificate_audit':audit,'macd':histogram,
            'history_state':'insufficient_history' if len(bars)<30 else 'available',
            'sampling_validation':'calendar_aggregated_source' if period in {'week','month','quarter','year'} else 'explicit_completed_source_bars',
            'definition_mode':'declared_recursive_profile','profile':'course_feature_sequence_recursive_v2',
            'structural_rank_is_not_timeframe_ratio':True,'strict_original_equivalence_proven':False,
            'lower_level_trigger':'not_joined_in_period_catalog','execution_allowed':False}


def schedule(count,limit=10):
    if count<=1:return [1] if count else []
    positions={count,1,min(5,count),min(30,count)}
    positions.update(max(1,round(count*i/(limit-1))) for i in range(limit))
    return sorted(positions)


def bar_dict(bar):
    return {'index':bar.pos,'time':bar.closed_at,'open':bar.open,'high':bar.high,
            'low':bar.low,'close':bar.close,'volume':bar.volume}


def make_catalog(snapshot_limit=10,progress=False):
    minute=make_demo_series(8)['1m'];cut=minute.bars[-1].closed_at
    sources={'1m':minute.bars}
    for period in ('5m','15m','30m','60m'):
        sources[period]=derive_series(minute,period,cut).bars
    sources['day']=long_daily_bars()
    aggregation={}
    for period in ('week','month','quarter','year'):
        sources[period],aggregation[period]=aggregate_calendar(sources['day'],period)
    result={}
    for period in ORDER:
        bars=sources[period];group='minute_source' if period.endswith('m') else 'daily_source'
        snapshots=[]
        for n in schedule(len(bars),snapshot_limit):
            report=analyze_sequence(bars[:n],period)
            snapshots.append({'as_of':n-1,'input_count':n,'as_of_time':bars[n-1].closed_at,'report':report})
        raw=json.dumps([asdict(b) for b in bars],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        result[period]={'label':LABELS[period],'period':period,'role':ROLES[period],'source_group':group,
                        'synthetic':True,'input_sha256':hashlib.sha256(raw).hexdigest(),
                        'bars':[bar_dict(b) for b in bars],'snapshots':snapshots,
                        'aggregation_audit':aggregation.get(period,{'rule':'exact_complete_session_buckets' if period!='1m' and period!='day' else 'source',
                            'source_group':group,'source_period':'1m' if group=='minute_source' else 'day',
                            'source_count':len(minute.bars) if group=='minute_source' else len(sources['day']),
                            'calendar':'CN_A_session_clock_synthetic_weekdays','missing_children_filled':False}),
                        'replay_schedule':{'observations':len(snapshots),'indices':[x['as_of'] for x in snapshots],
                                           'semantics':'scheduled literal prefixes, not every source bar; full earlier history retained'},
                        'cross_group_link_allowed':False}
        if progress:
            r=snapshots[-1]['report']
            print(json.dumps({'period':period,'bars':len(bars),'snapshots':len(snapshots),
                               'segments':len(r['base']['segments']),
                               'ranks':[(l['rank'],len(l['completed_types']),len(l['centers'])) for l in r['hierarchy']['levels']]},ensure_ascii=False),flush=True)
    return {'meta':{'schema':'chanlun.period_catalog.v1','synthetic':True,
                    'period_order':list(ORDER),'source_groups':{
                        'minute_source':{'label':'短周期合成教学源','source_period':'1m','bars':len(minute.bars),
                                         'note':'8个工作日，按A股分钟收盘时钟生成；非真实股票行情。'},
                        'daily_source':{'label':'长期独立合成教学源','source_period':'day','bars':len(sources['day']),
                                        'note':'1800个合成工作日，忽略交易所节假日；周月季年仅合成日历完整组。'}},
                    'cross_group_evidence':'forbidden: minute and long-term sources are independent teaching experiments',
                    'profile':'course_feature_sequence_recursive_v2','rank_is_not_period':True,
                    'strict_original_equivalence_proven':False,'execution_allowed':False},'periods':result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=HERE/'period_catalog.js')
    parser.add_argument('--snapshots',type=int,default=10)
    args=parser.parse_args()
    if not 3<=args.snapshots<=16:parser.error('--snapshots must be3..16')
    catalog=make_catalog(args.snapshots,True)
    encoded=json.dumps(catalog,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    args.output.write_text('window.CHAN_PERIOD_CATALOG='+encoded+';\n',encoding='utf-8')
    (HERE/'period_catalog_manifest.json').write_text(json.dumps({'meta':catalog['meta'],'periods':{
        key:{k:v for k,v in value.items() if k not in {'bars','snapshots'}} for key,value in catalog['periods'].items()}},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output),'bytes':args.output.stat().st_size},ensure_ascii=False))


if __name__=='__main__':main()
