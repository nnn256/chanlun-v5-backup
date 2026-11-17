'use strict';
const assert=require('node:assert/strict');
const test=require('node:test');
const fs=require('node:fs'),vm=require('node:vm');
require('../workbench/web/signal-chart.js');
const point=(id,period,anchor,availableAt,availableTime,extra={})=>({id,period,anchor,available_at:availableAt,available_time:availableTime,rank:1,side:'buy',state:'structure_complete',...extra});

test('latest cross-period marker follows observed time rather than incompatible bar indices',()=>{
  const olderMinute=point('minute-old','1m',24000,24005,'2026-11-12T14:00:00+08:00');
  const newerDaily=point('daily-new','day',1400,1405,'2026-11-13T15:00:00+08:00');
  const input=[olderMinute,newerDaily];
  const result=SignalChart.presentation(input,{rank:'all'});
  assert.equal(result.latest.id,'daily-new');
  assert.deepEqual(result.items.map(p=>p.id),['daily-new','minute-old']);
  assert.deepEqual(input.map(p=>p.id),['minute-old','daily-new']);
});

test('all periods includes every loaded OHLC period and explicit period remains exclusive',()=>{
  const input=['day','30m','5m','1m','15m','60m','week'].map((period,i)=>point(period,period,i,i+1,'2026-11-13T15:00:00+08:00'));
  assert.equal(SignalChart.presentation(input,{rank:'all'}).items.length,input.length);
  assert.deepEqual(SignalChart.presentation(input,{period:'1m',rank:'all'}).items.map(p=>p.id),['1m']);
});

test('same-period legacy snapshots without timestamps retain numerical ordering',()=>{
  const input=[point('early','5m',20,22),point('late','5m',50,55)];
  assert.equal(SignalChart.presentation(input).latest.id,'late');
});

test('instant comparison handles equivalent timezone encodings and tie-breaks deterministically',()=>{
  const a=point('a','day',10,12,'2026-11-13T15:00:00+08:00');
  const b=point('b','1m',400,410,'2026-11-13T07:00:00Z');
  assert.deepEqual([b,a].sort(SignalChart.compareNewest).map(p=>p.id),['a','b']);
});

test('both sides remain visible by default and review/history switches still apply',()=>{
  const input=[point('buy','1m',1,2,'2026-11-13T10:00:00+08:00'),point('sell','1m',3,4,'2026-11-13T11:00:00+08:00',{side:'sell'}),point('review','1m',5,6,'2026-11-13T12:00:00+08:00',{state:'needs_review'}),point('old','1m',7,8,'2026-11-13T13:00:00+08:00',{state:'invalidated'})];
  assert.deepEqual(new Set(SignalChart.presentation(input,{showInvalid:false}).items.map(p=>p.id)),new Set(['buy','sell']));
  assert.equal(SignalChart.presentation(input,{showReview:true}).items.length,4);
  assert.equal(SignalChart.presentation(input,{showReview:true}).active,2);
  assert.equal(SignalChart.presentation(input,{showReview:true}).review,1);
});

test('initial query period preserves 1m and rejects unsupported values without resetting on refresh',()=>{
  const source=fs.readFileSync(require('node:path').join(__dirname,'../workbench/web/app.js'),'utf8');
  const start=source.indexOf('function initialPeriod('),end=source.indexOf('\nconst S=',start);
  const context={URLSearchParams};vm.createContext(context);vm.runInContext(source.slice(start,end),context);
  assert.equal(context.initialPeriod('?symbol=sz300949&period=1m'),'1m');
  assert.equal(context.initialPeriod('?period=unsupported'),'all');
  assert.equal(context.initialPeriod(''),'all');
  assert.equal(context.initialPeriod('?period=1m&fresh=1'),'1m');
});

test('minute live status uses the displayed panel count, not daily summary count',()=>{
  const source=fs.readFileSync(require('node:path').join(__dirname,'../workbench/web/app.js'),'utf8');
  const start=source.indexOf('function renderLiveStatus()'),end=source.indexOf('\nasync function quoteTick(',start);
  let rendered='';
  const context={S:{period:'1m',data:{summary:{live:{received_at:'2026-11-15T12:12:10+08:00',latest_bar_at:'2026-11-13T15:00:00+08:00',confirmed_history_bars:1386}},chart:{panels:[{period:'1m',bars:Array.from({length:23761},(_,i)=>({is_closed:i<23760})),live_session:{rebuilt:false,restored:false}}]}}},PERIOD:{'1m':'1分钟'},integer:x=>String(x),text:(s,v)=>rendered=v};
  vm.createContext(context);vm.runInContext(source.slice(start,end),context);context.renderLiveStatus();
  assert.ok(rendered.includes('1分钟闭合K线 23760 根'));
  assert.ok(!rendered.includes('1386'));
});
