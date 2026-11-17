/* Run: node test_chart_explainer.js. Standard library only. */
const assert = require('node:assert/strict');
const { explainFrame, describeObject, periodInfo } = require('./chart_explainer.js');

const tests=[];
const test=(name,fn)=>{fn();tests.push(name);};
const bars=Array.from({length:90},(_,i)=>({index:i,open:10,high:12,low:8,close:11,time:`2026-01-05T${String(9+Math.floor(i/60)).padStart(2,'0')}:${String(i%60).padStart(2,'0')}:00+08:00`}));
const center={id:'c1:4:30',rank:1,start:4,end:30,zd:9,zg:11,dd:8,gg:12,formed_at:38,available_at:39,member_ids:['u0:a','u0:b','u0:c'],state:'formed',certificate:{passed:true,sublevel_types_verified:false}};
const type={id:'u1:4:30',rank:1,kind:'consolidation',direction:'up',state:'complete',start:4,end:30,start_price:9,end_price:11,components:['u0:a','u0:b','u0:c'],completed_at:39,completion:{rule:'same_level_completed_center_cut_v1',is_turn_confirmation:false}};
const signal={id:'b1:third_buy:c1:4:30:35',class:'third_buy',side:'buy',rank:1,anchor:35,price:12,terminal_range:[30,35],center_id:center.id,available_at:40,invalidation:11,state:'awaiting_lower_confirmation',lower_level_trigger:'missing'};
const nativeReport={period:'5m',as_of_index:49,input_audit:{bars_used:50},base:{merged:[],fractals:[{id:'f:top:12',kind:'top',source:12,price:12,basis_at:14}],strokes:[{id:'p:4:12',direction:'up',start:4,end:12,start_price:9,end_price:12,state:'confirmed',basis_at:25},{id:'p:40:45',direction:'down',start:40,end:45,start_price:12,end_price:10,state:'provisional',basis_at:47}],segments:[{id:'s0:4:30',start:4,end:30,start_price:9,end_price:12,state:'confirmed',basis_at:38,confirmation:{path:'feature_gap'}}]},hierarchy:{levels:[{rank:1,centers:[center],completed_types:[type],pending:[],comparisons:[],signals:[signal],movement_views:{completed_types:[],pending:[]}}]},signals:[signal],divergence_comparisons:[],certificate_audit:{state:'passed'}};
const context=(extras={})=>({period:'5m',rank:1,as_of:49,bars,report:nativeReport,source_group:'minute_source',synthetic:true,...extras});

test('全部10种周期名称与职责完整',()=>{
  const expected={'1m':'1分钟','5m':'5分钟','15m':'15分钟','30m':'30分钟','60m':'60分钟',day:'日线',week:'周线',month:'月线',quarter:'季线',year:'年线'};
  for(const [period,label] of Object.entries(expected)){
    const result=explainFrame(context({period}));
    assert.match(result.title,new RegExp(label));
    assert.equal(periodInfo(period).label,label);
    assert.ok(result.periodRole.length>15);
  }
});
test('真实当前报告产生11条短讲解',()=>{
  const result=explainFrame(context());
  assert.equal(result.steps.length,11);
  assert.equal(result.availability.status,'ready');
  assert.equal(result.counts.bars,50);
  assert.equal(result.counts.centers,1);
  assert.equal(result.counts.types,1);
  assert.equal(result.sourceGroup,'minute_source');
});
test('结构秩和周期不互换',()=>{
  const result=explainFrame(context({period:'week',rank:2}));
  assert.match(result.rankRole,/不是周线的别名/);
  assert.equal(result.availability.status,'rank_not_available');
  assert.equal(result.counts.centers,0);
  assert.match(result.speech,/L2尚未形成/);
});
test('L0明确为基础线段，null为全部',()=>{
  assert.match(explainFrame(context({rank:0})).rankRole,/最低边界/);
  assert.equal(explainFrame(context({rank:0})).counts.centers,0);
  assert.match(explainFrame(context({rank:null})).title,/全部已有结构层/);
  assert.equal(explainFrame(context({rank:null})).counts.centers,1);
});
test('无报告或历史太短必须解释缺项',()=>{
  const missing=explainFrame({period:'year',rank:3,bars:bars.slice(0,3),as_of:2,synthetic:true});
  assert.equal(missing.availability.status,'no_report');
  assert.match(missing.speech,/没有当前周期的计算报告/);
  const short=explainFrame({period:'year',rank:0,bars:bars.slice(0,3),as_of:2,report:{as_of:2},synthetic:true});
  assert.equal(short.availability.status,'insufficient_history');
  assert.match(short.speech,/目前只有3根K线/);
});
test('不读取未来时点完整报告来讲过去',()=>{
  const result=explainFrame(context({as_of:20}));
  assert.equal(result.availability.status,'report_after_cutoff');
  assert.equal(result.counts.centers,0);
  assert.equal(result.counts.signals,0);
  assert.doesNotMatch(result.speech,/12个|c1:4:30|b1:third_buy/);
});
test('逐对象过滤未来确认和未来比较ID',()=>{
  const report=JSON.parse(JSON.stringify(nativeReport));
  report.base.segments.push({id:'FUTURE_SECRET',start:30,end:48,basis_at:52,state:'confirmed'});
  report.divergence_comparisons.push({id:'future_comparison',rank:1,available_at:51,anchor:45,a:{unit_id:'FUTURE_SECRET_A'},c:{unit_id:'FUTURE_SECRET_C'}});
  const result=explainFrame(context({report}));
  assert.equal(result.counts.segments,1);
  assert.equal(result.counts.comparisons,0);
  assert.doesNotMatch(result.speech,/FUTURE_SECRET/);
});
test('原始K线多于cutoff时不泄漏总数量',()=>{
  const result=explainFrame(context());
  assert.equal(result.counts.bars,50);
  assert.doesNotMatch(result.speech,/90根K线/);
});
test('同级分解完成不冒充反转确认',()=>{
  const result=describeObject('完成分解单元',type,bars);
  assert.match(result.text,/不等于价格已经反转/);
  assert.equal(result.objectId,type.id);
  assert.deepEqual(result.range,[4,30]);
});
test('null confirmed_at不回填available_at',()=>{
  const result=describeObject('笔',{id:'p:tail',direction:'up',start:40,end:45,start_price:10,end_price:12,confirmed_at:null,available_at:47,finalized:false},bars);
  assert.equal(result.confirmationIndex,null);
  assert.equal(result.availableIndex,47);
  assert.equal(result.rows.find(r=>r.label==='确认时间').value,'尚未确认');
  assert.match(result.text,/未完成末笔/);
});
test('线段说明具体缺口路径与时间',()=>{
  const result=describeObject('线段',nativeReport.base.segments[0],bars);
  assert.match(result.text,/第二特征序列/);
  assert.equal(result.confirmationIndex,38);
  assert.match(result.text,/价格终点和取得确认的时间分开/);
});
test('中枢讲清核心边界和整体极值及下级',()=>{
  const result=describeObject('中枢',center,bars);
  assert.match(result.text,/下沿ZD是9/);
  assert.match(result.text,/上沿ZG是11/);
  assert.match(result.text,/DD\/GG是8到12/);
  assert.match(result.text,/3个命名下级组件/);
  assert.match(result.text,/最低边界/);
});
test('候选和失效按当前时点实际状态讲解',()=>{
  const report=JSON.parse(JSON.stringify(nativeReport));
  report.signals[0].state='invalidated';
  const result=explainFrame(context({report}));
  assert.equal(result.counts.invalidated,1);
  assert.match(result.speech,/1个已失效/);
  assert.equal(result.counts.sixClasses.third_buy,1);
  const item=describeObject('signal',report.signals[0],bars);
  assert.match(item.text,/已经失效/);
  assert.match(item.text,/失效边界是11/);
});
test('选中对象可独立说明并提供高亮范围',()=>{
  const result=explainFrame(context({selectedObject:{kind:'线段',item:nativeReport.base.segments[0]}}));
  assert.equal(result.selected.objectId,'s0:4:30');
  assert.deepEqual(result.selected.highlight,{start:4,end:30,price:undefined});
});
test('旧快照适配正常且六类计数不补造',()=>{
  const old={as_of:49,input_bars:50,merged_count:42,fractals:nativeReport.base.fractals,strokes:nativeReport.base.strokes,segments:nativeReport.base.segments,centers:[center],types:[type],signal_candidates:[{...signal,signal_class:'third_buy_candidate',status:'candidate'}],signal_states:{[signal.id]:'candidate'}};
  const result=explainFrame(context({report:old}));
  assert.equal(result.counts.merged,42);
  assert.equal(result.counts.signals,1);
  assert.equal(result.counts.sixClasses.first_buy,0);
  assert.match(result.speech,/一买0个/);
});
test('每步objectId链接实际现有结构',()=>{
  const result=explainFrame(context());
  assert.equal(result.steps.find(s=>s.key==='segments').objectId,'s0:4:30');
  assert.equal(result.steps.find(s=>s.key==='centers').objectId,center.id);
  assert.equal(result.steps.find(s=>s.key==='signals').objectId,signal.id);
});
test('输出文字没有undefined或NaN字段污染',()=>{
  const variants=[context(),{period:'year',rank:8,as_of:0,bars:bars.slice(0,1),report:{as_of:0}},{}];
  for(const input of variants){
    const result=explainFrame(input);
    const words=[result.title,result.subtitle,result.overview,result.speech,...result.steps.map(s=>s.text)].join('\n');
    assert.doesNotMatch(words,/undefined|NaN|\bnull\b/);
  }
});
test('带时间截止的报告不能引用未来报告时间',()=>{
  const report=JSON.parse(JSON.stringify(nativeReport));
  delete report.as_of_index;report.as_of='2026-01-05T12:00:00+08:00';
  const result=explainFrame(context({as_of:'2026-01-05T09:40:00+08:00',report}));
  assert.equal(result.availability.status,'report_after_cutoff');
});
test('无组件的递归占位层不当作已经形成',()=>{
  const report=JSON.parse(JSON.stringify(nativeReport));
  report.hierarchy.levels.push({rank:2,input_ids:['u1:4:30'],centers:[],completed_types:[],pending:[],movement_views:{completed_types:[],pending:[]}});
  const result=explainFrame(context({rank:2,report}));
  assert.equal(result.availability.status,'rank_not_available');
  assert.deepEqual(result.availability.availableRanks,[0,1]);
});
test('早于第一根的索引不会回退到最后报告',()=>{
  const result=explainFrame(context({as_of:-1}));
  assert.equal(result.counts.bars,0);
  assert.equal(result.counts.segments,0);
  assert.equal(result.availability.status,'report_after_cutoff');
});

console.log(JSON.stringify({tests:tests.length,passed:tests},null,2));
