'use strict';
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
function initialPeriod(search){const period=new URLSearchParams(search).get('period');return ['all','day','30m','5m','1m','15m','60m','5d','week','month','quarter','year','timeshare','five_days'].includes(period)?period:'all';}
const S={view:'market',q:'',exchange:'',filter:'',job:new URLSearchParams(location.search).get('job')||'',offset:0,limit:40,total:0,selected:new URLSearchParams(location.search).get('symbol')||'sz300949',data:null,period:initialPeriod(location.search),range:'recent',rank:'all',signalSide:'all',signalSelected:'',charts:[],overview:null,layers:{strokes:false,segments:true,centers:true,signals:true,merged:false,fractals:false,types:false},stockRequest:0,marketRequest:0,benchmarkRequest:0,benchmarkLayers:{strokes:false,segments:true,centers:true,signals:true,merged:true,fractals:true,types:true,showReview:true},benchmarkSelectedSignal:''};
const PERIOD={day:'日线','5d':'5日K线','1m':'1分钟','5m':'5分钟','15m':'15分钟','30m':'30分钟','60m':'60分钟',week:'周K线',month:'月K线',quarter:'季K线',year:'年K线',timeshare:'历史分时',five_days:'五日分时',auction:'竞价历史'};
S.layers.research=true;S.benchmarkLayers.research=true;
const MODE={day:'日线扫描',multi:'三周期校验',replay:'逐日回放',full:'全周期历史',live:'实时K线'};
const JOB_STATE={queued:'排队中',starting:'准备中',running:'运行中',pausing:'暂停中 · 等待当前股票结束',paused:'已暂停',completed:'已完成',interrupted:'已中断 · 可继续',cancelling:'停止中',cancelled:'已停止'};
const STATE={structure_complete:'本级结构完成·待多周期',local_structure_complete:'本级结构完成·待多周期',needs_review:'待复核',withdrawn:'已撤回',calculated:'三周期已计算',blocked_data_contract:'数据校验未通过',day_only:'仅日线结构',waiting_lower_confirmation:'待低级别确认',blocked_terminal_history:'分钟历史不足',invalidated:'已失效',waiting_trigger:'待细级别触发',structurally_triggered_under_profile:'模型研究触发',awaiting_lower_confirmation:'待低级别确认'};
const fmt=(v,n=2)=>v==null?'—':Number(v).toFixed(n);
const integer=v=>Number(v||0).toLocaleString('zh-CN');
function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function text(selector,value){$(selector).textContent=value;}
function toast(message){text('#toast',message);$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,5000);}
async function api(path,body,options={}){const response=await fetch(path,{...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),...options});const data=await response.json();if(!response.ok)throw Error(data.error||'请求失败');return data;}
function button(label,action,cls='button small'){const b=node('button',cls,label);b.type='button';b.onclick=action;return b;}
function view(name){S.view=name;$$('[id^=view-]').filter(n=>n.tagName==='SECTION').forEach(n=>n.hidden=n.id!=='view-'+name);$$('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===name));text('#view-title',{market:'全市场工作台',indices:'大盘行业',tasks:'任务中心',data:'数据与口径',signals:'扫描与提醒',backtests:'全市场回测'}[name]);if(name==='signals')refreshMonitor();if(name==='backtests')refreshBacktests(true);if(name==='indices')refreshMarketContext();if(name==='market')requestAnimationFrame(()=>S.charts.forEach(c=>c.resize()));}
function statusBadge(label,kind=''){return node('span','badge '+kind,label);}

let marketContextBusy=false;
let benchmarkChart=null;
let benchmarkOverlay=null;
let benchmarkResizeObserver=null;
let benchmarkDraw=null;
let industrySnapshot=[];
let industryPage=0;
const INDUSTRY_PAGE_SIZE=100;
function renderIndustryPage(){
  const query=$('#industry-search').value.trim().toLowerCase(),sort=$('#industry-sort').value;
  const rows=industrySnapshot.filter(item=>!query||`${item.name} ${item.code}`.toLowerCase().includes(query));
  rows.sort((a,b)=>sort==='name-asc'?a.name.localeCompare(b.name,'zh-CN'):
    sort==='change-asc'?(a.change_pct??Infinity)-(b.change_pct??Infinity):
      (b.change_pct??-Infinity)-(a.change_pct??-Infinity));
  const pageCount=Math.max(1,Math.ceil(rows.length/INDUSTRY_PAGE_SIZE));industryPage=Math.min(industryPage,pageCount-1);
  const start=industryPage*INDUSTRY_PAGE_SIZE,visible=rows.slice(start,start+INDUSTRY_PAGE_SIZE),body=$('#industry-rows');body.replaceChildren();
  for(const sector of visible){const tr=node('tr'),name=node('td');name.append(node('span','',sector.name),node('small','industry-code',sector.code||''));const change=sector.change_pct;
    tr.append(name,node('td',change==null?'':change>=0?'up':'down',change==null?'—':(change>=0?'+':'')+fmt(change)+'%'),node('td','',fmt(sector.price)),node('td','',sector.source||'—'));body.append(tr);}
  $('#industry-page-label').textContent=rows.length?`${integer(start+1)}–${integer(start+visible.length)} / ${integer(rows.length)} · 第 ${industryPage+1} / ${pageCount} 页`:'0 个行业';
  $('#industry-prev').disabled=industryPage===0;$('#industry-next').disabled=industryPage>=pageCount-1;
  body.closest('.table-scroll').hidden=rows.length===0;
}
async function refreshMarketContext(period='day',force=false){
  if(marketContextBusy){S.marketContextQueued=period;return;}
  if(!force&&S.marketContextAt&&Date.now()-S.marketContextAt<30000&&S.marketContextPeriod===period)return;
  marketContextBusy=true;text('#market-context-status','正在读取指数与行业板块行情…');
  try{
    const result=await api('/api/market-context?period='+encodeURIComponent(period)+'&industries=1');
    S.marketContextAt=Date.now();S.marketContextPeriod=period;S.marketContextResult=result;const grid=$('#market-indices');grid.replaceChildren();
    for(const index of result.indices||[]){
      const card=node('button','benchmark-item');card.type='button';card.dataset.code=index.code;card.disabled=index.state==='unavailable'||!index.bars?.length;card.setAttribute('aria-label',`${index.name} ${PERIOD[index.period]}指数K线详情`);card.onclick=()=>openBenchmark(index.code);card.append(node('h2','',index.name));
      if(index.state==='unavailable')card.append(node('p','industry-state','指数暂不可用 · '+(index.error_detail||index.error||'')));
      else{const quote=node('div','benchmark-quote');quote.append(node('strong','',fmt(index.price)),node('b',index.change_pct>=0?'up':'down',(index.change_pct>=0?'+':'')+fmt(index.change_pct)+'%'));const state=index.state==='stale'?'缓存 '+integer(index.cache_age_seconds)+'秒':index.latest_bar_is_closed===false?'当前K形成中':'已收盘';card.append(quote,node('small','',state+' · '+PERIOD[index.period]+' · K线时间 '+index.latest_bar_at.slice(0,16).replace('T',' ')+' · 获取 '+index.received_at.slice(11,19)),node('small','benchmark-action','点击查看指数K线 →'));}
      grid.append(card);
    }
    const industries=result.industries||{};
    text('#industry-updated',industries.received_at?'获取于 '+industries.received_at.slice(11,19):'—');
    if(industries.state==='ready'||industries.state==='stale'){
      industrySnapshot=industries.boards||industries.leaders||[];industryPage=0;
      text('#industry-status',industries.source+' · '+(industries.state==='stale'?'缓存快照':'当前快照')+' · '+integer(industries.count)+' / 上游 '+integer(industries.provider_total??industries.count)+' 个行业'+(industries.complete===false?' · 数据不完整':'')+(industries.error_detail||industries.error?' · 刷新失败 '+(industries.error_detail||industries.error):''));
    }else{text('#industry-status',(industries.source||'行业数据源')+' · '+(industries.error_detail||industries.error||'不可用')+' · 没有生成替代数据');industrySnapshot=[];industryPage=0;}
    renderIndustryPage();
    const failed=(result.indices||[]).filter(x=>x.state==='unavailable').length;
    const stale=(result.indices||[]).filter(x=>x.state==='stale').length,ready=(result.indices||[]).filter(x=>x.state!=='unavailable'&&x.state!=='stale').length;
    text('#market-context-status','指数新鲜 '+ready+' · 缓存 '+stale+' · 不可用 '+failed+' · 北京时间 '+result.received_at.slice(11,19)+' · 行业 '+(industries.state==='ready'?'已连接':industries.state==='stale'?'显示缓存':'不可用')+(result.breadth?' · 上证成分上涨 '+integer(result.breadth.up_count)+' / 下跌 '+integer(result.breadth.down_count):''));
  }catch(error){text('#market-context-status','市场行情获取失败：'+error.message+'；不使用旧价格冒充当前值');}
  finally{marketContextBusy=false;if(S.marketContextQueued&&S.marketContextQueued!==period){const queued=S.marketContextQueued;S.marketContextQueued=null;refreshMarketContext(queued);}}
}

let benchmarkRange='recent';

function setBenchmarkRange(range){
  const panel=S.benchmarkDetail?.panel;if(!panel?.bars?.length||!benchmarkChart)return;
  benchmarkRange=range==='all'?'all':'recent';
  if(benchmarkRange==='all')benchmarkChart.timeScale().setVisibleLogicalRange({from:0,to:panel.bars.length-1});
  else{const visible=Math.min(panel.bars.length,Math.max(1,Number(panel.default_visible)||300));benchmarkChart.timeScale().setVisibleLogicalRange({from:Math.max(0,panel.bars.length-visible),to:panel.bars.length-1});}
  $$('#benchmark-range-controls button').forEach(button=>button.classList.toggle('primary',button.dataset.range===benchmarkRange));
}

function renderBenchmarkProof(point){
  S.benchmarkSelectedSignal=point?.id||null;const target=$('#benchmark-signal-proof');target.replaceChildren();
  if(!point)return;
  target.append(node('strong',point.side==='buy'?'up':'down',`${point.label} · ${point.state_label} · L${point.rank}`));
  const values=[['价格端点',`${point.anchor_time} / ${fmt(point.price)}`],['结构依据',point.available_time],
    ['失效边界',`${point.invalidation_operator} ${fmt(point.invalidation)}`],['级别口径',point.native_engine+' · '+point.native_type]];
  const grid=node('dl','benchmark-proof-grid');for(const [name,value]of values){const item=node('div');item.append(node('dt','',name),node('dd','',value));grid.append(item);}target.append(grid);
}

function drawBenchmarkStructure(detail){
  const panel=detail?.panel,svg=benchmarkOverlay,chart=benchmarkChart,container=$('#benchmark-chart');
  if(!panel||!svg||!chart||!container)return;
  const width=container.clientWidth,height=container.clientHeight,plotWidth=chart.timeScale().width();
  if(!width||!height||!plotWidth)return;
  svg.setAttribute('width',width);svg.setAttribute('height',height);svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.replaceChildren();
  const defs=svgElement('defs'),clip=svgElement('clipPath',{id:'benchmark-clip'});clip.append(svgElement('rect',{x:0,y:0,width:plotWidth,height:height-22}));defs.append(clip);svg.append(defs);
  const group=svgElement('g',{'clip-path':'url(#benchmark-clip)'});svg.append(group);
  const x=index=>{const bar=panel.bars[index];return bar?chart.timeScale().timeToCoordinate(bar.time):null;};
  const y=price=>detail.series.priceToCoordinate(price);
  const inside=(...values)=>values.every(Number.isFinite);
  if(S.benchmarkLayers.research&&window.RegimeResearch)RegimeResearch.draw({group,research:panel.regime_research,x,y,width:plotWidth,height:height-25});
  const visibleRange=chart.timeScale().getVisibleLogicalRange();
  const isVisible=(start,end=start)=>!visibleRange||!(end<visibleRange.from-1||start>visibleRange.to+1);
  const showReview=S.benchmarkLayers.showReview;
  if(S.benchmarkLayers.merged)for(const bar of panel.merged||[]){
    if(!isVisible(bar.start,bar.end))continue;
    const a=x(bar.start),b=x(bar.end);if(!inside(a,b)||Math.max(a,b)<0||Math.min(a,b)>plotWidth)continue;
    const high=y(bar.high),low=y(bar.low);if(!inside(high,low))continue;
    group.append(svgElement('rect',{x:Math.min(a,b)-2,y:Math.min(high,low),width:Math.max(Math.abs(b-a)+4,4),height:Math.max(Math.abs(low-high),1),fill:'#7e8d99','fill-opacity':.035,stroke:'#7e8d99','stroke-opacity':.36,'stroke-width':.7}));
  }
  if(S.benchmarkLayers.centers){
    const centers=(panel.structure_layers||[]).flatMap(layer=>layer.centers||[]);
    for(const center of centers){if(!showReview&&center.review_issues?.length)continue;const a=x(center.start),b=x(center.end),top=y(center.zg),bottom=y(center.zd);if(!inside(a,b,top,bottom))continue;
      const rank=center.rank||1,color=rank===1?'#278f85':'#b17c32';
      group.append(svgElement('rect',{x:Math.min(a,b),y:Math.min(top,bottom),width:Math.max(1,Math.abs(b-a)),height:Math.max(1,Math.abs(bottom-top)),fill:color,'fill-opacity':rank===1?.08:.035,stroke:color,'stroke-width':rank===1?1.1:1,'stroke-dasharray':rank===1?'none':'4 3'}));
      if(b>=0&&a<=plotWidth)svgLabel(group,Math.max(4,Math.min(a+4,plotWidth-90)),Math.max(13,top-5),`L${rank} ${fmt(center.zd)}–${fmt(center.zg)}`,color,9);
    }
  }
  if(S.benchmarkLayers.strokes)for(const stroke of panel.strokes||[]){if(!showReview&&stroke.review_issues?.length)continue;const a=x(stroke.start),b=x(stroke.end),ya=y(stroke.start_price),yb=y(stroke.end_price);if(!inside(a,b,ya,yb))continue;
    const disputed=!!stroke.review_issues?.length;group.append(svgElement('line',{x1:a,y1:ya,x2:b,y2:yb,stroke:disputed?'#b87925':'#7d93a7','stroke-width':1,'stroke-opacity':.8,'stroke-dasharray':stroke.state==='confirmed'&&!disputed?'none':'3 3'}));
  }
  if(S.benchmarkLayers.types)for(const layer of panel.structure_layers||[])for(const type of layer.completed_types||[]){if(!isVisible(type.start,type.end))continue;const a=x(type.start),b=x(type.end),ya=y(type.start_price),yb=y(type.end_price);if(!inside(a,b,ya,yb))continue;
    group.append(svgElement('line',{x1:a,y1:ya,x2:b,y2:yb,stroke:(type.rank||layer.rank)===1?'#a3793a':'#8171a7','stroke-width':(type.rank||layer.rank)===1?3.5:2.5,'stroke-opacity':.8}));
  }
  if(S.benchmarkLayers.segments){
    const lineSets=[{rank:1,items:panel.segments||[]},{rank:2,items:panel.higher_segments||[]}];
    for(const set of lineSets)for(const segment of set.items){if(!showReview&&segment.review_issues?.length)continue;const a=x(segment.start),b=x(segment.end),ya=y(segment.start_price),yb=y(segment.end_price);if(!inside(a,b,ya,yb))continue;
      const disputed=!!segment.review_issues?.length,color=disputed?'#b87925':set.rank===1?'#2869ad':'#6b65a8';
      group.append(svgElement('line',{x1:a,y1:ya,x2:b,y2:yb,stroke:color,'stroke-width':set.rank===1?2:1.6,'stroke-dasharray':segment.state==='confirmed'&&!disputed?'none':'6 4'}));
      const ex=b,ey=yb;if(ex>=0&&ex<=plotWidth)svgLabel(group,Math.max(4,Math.min(ex+4,plotWidth-60)),ey+(segment.direction==='up'?-8:13),`L${set.rank}`,color,9);
    }
  }
  if(S.benchmarkLayers.fractals)for(const fractal of panel.fractals||[]){if(!isVisible(fractal.source))continue;const px=x(fractal.source),py=y(fractal.price);if(!inside(px,py)||px<0||px>plotWidth)continue;
    group.append(svgElement('circle',{cx:px,cy:py,r:2.5,fill:fractal.kind==='top'?'#d54d53':'#168c79',stroke:'#fff','stroke-width':.7}));
  }
  let markerStats={visible_markers:0,visible_labels:0};
  const signals=(panel.signal_chart?.objects||[]).filter(point=>showReview||point.state!=='needs_review');
  if(S.benchmarkLayers.signals)markerStats=SignalChart.draw({group,items:signals,x,y,width:plotWidth,height:height*.82,
    selected:S.benchmarkSelectedSignal,showTimes:false,showRank:true,
    onSelect:point=>{renderBenchmarkProof(point);benchmarkDraw?.();}});
  const status=detail.structure;
  const returned=panel.coverage?.returned_bars??panel.bars?.length??0;
  text('#benchmark-structure-status',`覆盖 ${returned} 根（已收盘 ${status.closed_bars}） · 笔 ${status.stroke_count} · 线段 ${status.segment_count} · 中枢 ${status.center_count} · 买卖点 ${status.signal_count} · ${status.profile}`);
  $('#benchmark-structure-status').title=status.coverage_semantics;
  $('#benchmark-render-count').textContent=`图中信号 ${markerStats.visible_markers} · 待复核结构 ${panel.geometry_review?.issues?.length||0}`;
}

function renderBenchmarkDetail(detail){
  const index=detail?.index,container=$('#benchmark-chart');if(!index||!container)return;
  benchmarkResizeObserver?.disconnect();benchmarkChart?.remove();benchmarkChart=null;benchmarkOverlay=null;benchmarkDraw=null;
  S.benchmarkDetail=detail;S.benchmarkSelectedSignal=null;
  text('#benchmark-title',index.name);text('#benchmark-code',index.code.toUpperCase()+' · '+PERIOD[index.period]);
  text('#benchmark-quote',fmt(index.price));$('#benchmark-change').className=index.change_pct>=0?'up':'down';
  text('#benchmark-change',(index.change_pct>=0?'+':'')+fmt(index.change_pct)+'%');
  text('#benchmark-source',`${index.source} · ${detail.panel.coverage?.claim||'数据源实际范围'} · 起始 ${detail.panel.coverage?.first_bar_at?.slice(0,10)||'—'} · 截止 ${index.latest_closed_bar_at?.slice(0,16).replace('T',' ')||'—'} · 获取 ${index.received_at.slice(11,19)}`);
  $$('#benchmark-period button').forEach(button=>button.classList.toggle('active',button.dataset.period===index.period));
  $$('#benchmark-layers input').forEach(input=>input.checked=!!S.benchmarkLayers[input.dataset.indexLayer]);
  renderBenchmarkProof(null);
  const panel=detail.panel;
  $('#benchmark-regime-summary').hidden=index.period!=='day';
  const researchLayer=$('#benchmark-layers input[data-index-layer="research"]');
  researchLayer.disabled=index.period!=='day';researchLayer.title=index.period==='day'?'闭合日线价格成交量研究':'该研究规则仅对日线验证，分钟图保留原生缠论结构';
  if(window.RegimeResearch)RegimeResearch.render($('#benchmark-regime-summary'),panel.regime_research,index.code,false);
  if(!window.LightweightCharts||!panel?.bars?.length){container.replaceChildren(node('div','empty','该指数没有足够的真实K线用于结构分析。'));text('#benchmark-structure-status',detail.error||'指数结构不可用。');return;}
  container.replaceChildren();container.classList.add('index-chartbox');
  const host=node('div','index-chart-canvas');benchmarkOverlay=svgElement('svg',{'class':'index-structure-overlay','aria-label':index.name+'缠论笔线段中枢与买卖点'});container.append(host,benchmarkOverlay);
  benchmarkChart=LightweightCharts.createChart(host,{width:host.clientWidth,height:host.clientHeight,
    layout:{background:{type:'solid',color:'#fff'},textColor:'#8293a3',fontSize:11,fontFamily:'Microsoft YaHei, sans-serif',attributionLogo:true},
    grid:{vertLines:{color:'#f0f3f7'},horzLines:{color:'#edf2f6'}},
    rightPriceScale:{borderColor:'#e4eaf0',minimumWidth:62},
    timeScale:{borderColor:'#e4eaf0',timeVisible:index.period!=='day',secondsVisible:false,minBarSpacing:.001},
    localization:{locale:'zh-CN',priceFormatter:value=>value.toFixed(2)}});
  const series=benchmarkChart.addSeries(LightweightCharts.CandlestickSeries,{upColor:'#d54d53',downColor:'#168e7c',borderUpColor:'#d54d53',borderDownColor:'#168e7c',wickUpColor:'#d54d53',wickDownColor:'#168e7c'});
  detail.series=series;
  series.setData(panel.bars.map(bar=>({time:bar.time,open:bar.open,high:bar.high,low:bar.low,close:bar.close})));
  const draw=()=>drawBenchmarkStructure(detail);benchmarkDraw=draw;
  benchmarkChart.timeScale().subscribeVisibleLogicalRangeChange(()=>requestAnimationFrame(draw));
  benchmarkResizeObserver=new ResizeObserver(()=>{if(host.clientWidth&&host.clientHeight){benchmarkChart?.resize(host.clientWidth,host.clientHeight);requestAnimationFrame(draw);}});
  benchmarkResizeObserver.observe(container);setBenchmarkRange(benchmarkRange);requestAnimationFrame(draw);
}

async function loadBenchmarkDetail(code,period){
  S.benchmarkCode=code;const token=++S.benchmarkRequest;
  if(!$('#benchmark-dialog').open)$('#benchmark-dialog').showModal();
  benchmarkResizeObserver?.disconnect();benchmarkResizeObserver=null;benchmarkChart?.remove();benchmarkChart=null;benchmarkOverlay=null;
  $('#benchmark-chart').replaceChildren();$('#benchmark-chart').classList.add('index-chartbox');
  text('#benchmark-title',S.marketContextResult?.indices?.find(row=>row.code===code)?.name||'大盘指数');
  text('#benchmark-code',code.toUpperCase()+' · '+(PERIOD[period]||period));text('#benchmark-source','正在获取指数结构窗口…');
  text('#benchmark-structure-status','正在按固定原生引擎计算笔、线段、中枢和买卖点…');
  $('#benchmark-render-count').textContent='';
  try{const detail=await api(`/api/index-structure/${encodeURIComponent(code)}?period=${encodeURIComponent(period)}`);if(token!==S.benchmarkRequest)return;S.marketContextPeriod=period;renderBenchmarkDetail(detail);}
  catch(error){if(token!==S.benchmarkRequest)return;text('#benchmark-source','指数来源数据/结构计算不可用 · '+error.message);text('#benchmark-structure-status','没有可用结构；详情未使用股票代理数据。');}
}

function openBenchmark(code){loadBenchmarkDetail(code,S.marketContextPeriod||'day');}

async function refreshOverview(){
  try{
    if(S.overviewPending)return;S.overviewPending=true;
    const data=await api('/api/overview');S.overview=data;text('#connection','● 本地服务已连接');
    text('#stat-total',integer(data.total));text('#stat-computed',integer(data.stats.computed));text('#stat-multi','三周期 '+integer(data.stats.multi)+' 只');text('#stat-triggered',integer(data.stats.triggered));
    text('#stat-date',data.stats.newest_date?(data.stats.oldest_date===data.stats.newest_date?data.stats.newest_date:data.stats.oldest_date+' ~ '+data.stats.newest_date):'尚未计算');
    const active=data.jobs.filter(j=>['queued','starting','running','pausing','cancelling'].includes(j.state));text('#queue-badge',active.length);
    const running=active.find(j=>j.state!=='queued')||active[0];const strip=$('#run-strip');strip.replaceChildren();strip.hidden=!running;
    if(running){const stage=running.progress?.[0];strip.append(node('span','dot'),node('b','',running.title),node('span','',stage?`${stage.name||stage.symbol} · ${stage.message}`:`${JOB_STATE[running.state]}　${integer(running.done)} / ${integer(running.total)}`));const progress=node('progress');progress.max=stage?.total||running.total;progress.value=stage?.completed??running.done;strip.append(progress,button('查看任务 →',()=>view('tasks')));}
    const filter=$('#job-filter');const before=S.job;filter.replaceChildren(new Option('每只股票的最新结果',''));for(const j of data.jobs)filter.add(new Option(j.title+' · '+j.created.slice(5,16).replace('T',' '),j.id));filter.value=before;
    renderJobs(data.jobs);
    if(S.followJob){
      const followed=data.jobs.find(j=>j.id===S.followJob);
      if(followed&&['completed','interrupted','cancelled'].includes(followed.state)){
        S.followJob=null;sessionStorage.removeItem('chanlun-follow-job');
        if(followed.success){await showJobResults(followed);toast('计算完成，已打开'+(followed.result_symbol||'对应股票')+'的图表');}
        else if(followed.failed){view('tasks');showErrors(followed.id);toast('任务未完成：下方显示具体失败原因，可重试失败项');}
      }
    }
  }catch(error){text('#connection','连接中断 · 自动重试');console.error(error);}finally{S.overviewPending=false;}
}

async function showJobResults(job){
  S.job=job.id;S.q='';S.exchange='';S.filter='';S.offset=0;S.period='day';
  $('#search').value='';$('#exchange').value='';$('#result-filter').value='';$('#job-filter').value=job.id;
  view('market');S.selected='';clearStockDetail('正在打开所选任务的结果…');await refreshMarket({selectFirst:true});
}

async function refreshMarket(options={}){
  const request=++S.marketRequest,job=S.job;
  try{
    const params=new URLSearchParams({q:S.q,exchange:S.exchange,filter:S.filter,job:S.job,offset:S.offset,limit:S.limit});
    const data=await api('/api/stocks?'+params);if(request!==S.marketRequest||job!==S.job)return;S.total=data.total;S.marketRows=data.rows;
    text('#market-count',integer(data.total)+' 只');const body=$('#market-body');body.replaceChildren();$('#market-empty').hidden=!!data.rows.length;
    for(const r of data.rows){
      const tr=node('tr',r.symbol===S.selected?'selected':'');tr.dataset.symbol=r.symbol;
      const title=node('td');const link=button(r.name,()=>selectStock(r.symbol),'stock-link');link.append(node('small','',r.code+' · '+{sh:'沪',sz:'深',bj:'京'}[r.exchange]));title.append(link);
      const label=r.item_state==='failed'?'计算失败':r.item_state==='running'?'正在计算':r.mode?(r.triggered>0?'模型触发':r.analysis_state==='blocked_data_contract'?'校验未通过':r.mode==='full'?'全周期 · '+(r.algorithm||'原版本'):r.mode==='multi'?'三周期 · '+(r.algorithm||'原版本'):r.mode==='replay'?'回放完成 · '+(r.algorithm||'原版本'):'日线 · '+(r.algorithm||'原版本')):'待计算';
      title.append(node('span','row-state',label));const color=r.change_pct>0?'up':r.change_pct<0?'down':'';
      tr.append(title,node('td',color,fmt(r.price)),node('td',color,r.change_pct==null?'—':(r.change_pct>=0?'+':'')+fmt(r.change_pct)+'%'));
      tr.onclick=e=>{if(!e.target.closest('button'))selectStock(r.symbol);};body.append(tr);
    }
    text('#page-label',data.total?`${S.offset+1}–${Math.min(S.offset+S.limit,data.total)} / ${integer(data.total)}`:'0 / 0');$('#prev-page').disabled=S.offset===0;$('#next-page').disabled=S.offset+S.limit>=data.total;
    const selectedRow=data.rows.find(row=>row.symbol===S.selected);
    if((job||options.selectFirst)&&!selectedRow){
      const first=data.rows.find(row=>row.item_state==='success')||data.rows[0];
      if(first)await selectStock(first.symbol);
      else {S.selected='';clearStockDetail('当前筛选没有股票结果，请调整筛选条件。');}
    }else if(selectedRow&&S.detailJob!==job&&!S.stockLoading&&!S.stockFailedKey){
      await selectStock(selectedRow.symbol);
    }else if(selectedRow?.item_state==='success'&&!S.data?.available&&!S.stockLoading&&!S.stockFailedKey){
      await selectStock(selectedRow.symbol);
    }

  }catch(error){toast(error.message);}
}

function disposeCharts(){S.charts.forEach(c=>{c.observer.disconnect();c.chart.remove();});S.charts=[];$('#charts').replaceChildren();}
function clearStockDetail(message){
  S.stockController?.abort();S.stockController=null;S.quoteController?.abort();S.quoteController=null;S.quotePending=false;
  S.periodController?.abort();S.periodController=null;S.periodRequest=(S.periodRequest||0)+1;
  ++S.stockRequest;S.data=null;S.detailJob=null;S.stockLoading=false;S.loadingLive=false;S.stockFailedKey=null;S.stockRetryAt=null;window.chartReady=false;
  $('#view-market').classList.remove('has-stock');
  disposeCharts();$('#stock-detail').hidden=true;$('#stock-empty').hidden=false;
  $('#stock-empty').replaceChildren(node('h3','',message));
}
async function selectStock(symbol){
  if(!symbol)return;
  const job=S.job;
  if(job)$('#live-quote').checked=false;
  const live=!job&&$('#live-quote').checked,period=['day','30m','5m','1m','all'].includes(S.period)?S.period:'day';
  const key=JSON.stringify([symbol,job,live,live?period:'saved']);
  if(S.stockLoading&&S.loadingKey===key)return;
  S.selected=symbol;
  const name=S.marketRows?.find(row=>row.symbol===symbol)?.name||symbol;
  let loadingTitle='正在加载 '+name+(live?' 的已保存快照，随后更新实时K线…':' 的已保存结果…');
  clearStockDetail(loadingTitle);
  const token=++S.stockRequest,controller=new AbortController();S.stockController=controller;S.stockLoading=true;S.loadingJob=job;S.loadingKey=key;S.loadingLive=live;
  let timedOut=false,snapshotShown=false;const started=Date.now();
  const timeout=setTimeout(()=>{timedOut=true;controller.abort();},60000);
  const ticker=setInterval(()=>{if(token!==S.stockRequest)return;const seconds=Math.floor((Date.now()-started)/1000);if(seconds>=3){if(snapshotShown)text('#live-quote-status',`已显示历史快照，实时K线与结构更新中 · 已等待 ${seconds} 秒；当前价格日期以图表标注为准`);else $('#stock-empty').replaceChildren(node('h3','',loadingTitle),node('p','',`已等待 ${seconds} 秒，服务器尚未返回。可以切换其他股票；60 秒未返回将停止等待并显示重试。`));}},1000);
  $$('#market-body tr').forEach(row=>row.classList.toggle('selected',row.dataset.symbol===symbol));
  try{
    if(live){
      try{
        const snapshot=await api('/api/stock/'+symbol,undefined,{signal:controller.signal});
        if(token!==S.stockRequest||S.selected!==symbol||S.job!==job)return;
        if(snapshot.available){
          if(snapshot.summary?.symbol&&snapshot.summary.symbol!==symbol)throw Error('已保存结果股票与选择不一致');
          S.data=snapshot;S.detailJob=job;$('#stock-empty').hidden=true;$('#stock-detail').hidden=false;
          prepareSignalDisplay();renderStock(false,true);renderLiveStatus();snapshotShown=true;
          text('#live-quote-status','已显示历史快照'+(period!=='all'&&!snapshot.chart.panels.some(panel=>panel.period===period)?'，保存结果不含所选周期':'')+'；正在更新实时K线与结构，当前价格日期以图表标注为准');
        }
      }catch(snapshotError){
        if(controller.signal.aborted)throw snapshotError;
        if(token!==S.stockRequest||S.selected!==symbol||S.job!==job)return;
      }
      if(!snapshotShown){loadingTitle='正在获取 '+name+' 的实时K线与结构…';$('#stock-empty').replaceChildren(node('h3','',loadingTitle),node('p','','没有可立即展示的已保存结果，正在请求实时数据。'));}
    }
    const data=await api(live?'/api/live-stock/'+symbol+'?period='+period:'/api/stock/'+symbol+(job?'?job='+encodeURIComponent(job):''),undefined,{signal:controller.signal});
    if(token!==S.stockRequest||S.selected!==symbol||S.job!==job)return;
    if(data.available&&data.summary?.symbol&&data.summary.symbol!==symbol)throw Error('结果股票与选择不一致，请刷新重试');
    if(live&&!data.available)throw Error(data.reason||'实时数据暂不可用');
    S.data=data;S.detailJob=job;$('#stock-empty').hidden=data.available;$('#stock-detail').hidden=!data.available;
    if(!data.available){
      const row=S.marketRows?.find(item=>item.symbol===symbol);
      const state=row?.item_state;
      const note=state==='running'?'该股票正在计算，完成后会自动加载结果。':state==='failed'?'该任务计算失败，可到任务中心查看原因并重试。':job?'该股票在所选任务中尚无成功结果。':'该股票尚未计算，可以新建计算任务。';
      const box=$('#stock-empty');box.replaceChildren(node('h3','',(data.record?.name||row?.name||symbol)+' · '+(state==='running'?'正在计算':state==='failed'?'计算失败':'暂无结果')),node('p','',note));
      if(state==='running'||state==='failed')box.append(button('查看任务',()=>view('tasks'),'button primary'));
      else box.append(button('计算该股',()=>openJob(symbol),'button primary'));
      return;
    }
    prepareSignalDisplay();renderStock(false,live);renderLiveStatus();
  }catch(error){
    if(token!==S.stockRequest||S.selected!==symbol||S.job!==job)return;
    S.stockFailedKey=key;S.stockRetryAt=live?Date.now()+60000:null;
    if(live&&snapshotShown){const message=(timedOut?'实时更新等待超过60秒':error.message)+'；实时尚未更新，保留已显示的历史快照，价格日期以图表标注为准。60秒后自动重试。';$('#live-quote-status').replaceChildren(node('span','',message),button('重试实时更新',()=>selectStock(symbol),'button small'));return;}
    disposeCharts();S.data=null;S.detailJob=job;$('#stock-detail').hidden=true;$('#stock-empty').hidden=false;
    const message=(timedOut?'等待服务器超过60秒，已停止本次页面请求；可重新加载或切换其他股票。':error.message)+(live?' 60秒后自动重试实时更新。':'');
    $('#stock-empty').replaceChildren(node('h3','','结果加载失败'),node('p','',message),button('重新加载',()=>selectStock(symbol),'button primary'));toast(message);
  }finally{clearTimeout(timeout);clearInterval(ticker);if(token===S.stockRequest){S.stockLoading=false;S.loadingLive=false;if(S.stockController===controller)S.stockController=null;}}
}

function renderStock(preserve=false,keepPeriod=false){
  const {chart:c,summary:s}=S.data;
  if(window.RegimeResearch)RegimeResearch.render($('#regime-summary'),c.panels.find(p=>p.period==='day')?.regime_research,s.symbol);
  $('#view-market').classList.add('has-stock');
  text('#stock-name',s.name);text('#stock-code',s.symbol.slice(2)+' · '+{sh:'SSE',sz:'SZSE',bj:'BSE'}[s.symbol.slice(0,2)]);
  text('#stock-price',fmt(s.price));text('#stock-change',(s.change_pct>=0?'+':'')+fmt(s.change_pct)+'%');
  $('.stock-quote').className='stock-quote '+(s.change_pct>=0?'up':'down');
  text('#stock-date',s.live?`最新交易日 ${s.live.latest_bar_at.slice(0,10)}${s.live.forming?' · 今日K线形成中':''} · 获取 ${s.live.received_at.slice(11,19)} · 确认结构截止 ${s.live.confirmed_through.slice(0,16).replace('T',' ')} · 北京时间`:`历史快照 · 行情截止 ${s.last_close_time} · TDX不复权 · 北京时间`);
  text('#stock-version',(s.algorithm||'原版本')+' · 4.4.2 固定引擎 / '+(MODE[s.mode]||'三周期校验'));
  let message=s.result_text||'结构研究结果';const states=s.multiframe_states||{};
  if(states.waiting_lower_confirmation)message+=`；${states.waiting_lower_confirmation}个历史候选待低级别确认`;
  if(states.blocked_terminal_history)message+=`；${states.blocked_terminal_history}个候选缺少终结段分钟历史`;
  const per=s.period_candidate_counts||{};
  const native=Object.entries(per).filter(([,v])=>v.active>0).map(([p,v])=>`${PERIOD[p]||p} ${v.active}个本级候选`);
  if(native.length&&!message.includes('本级候选'))message+=`；${native.join('、')}，但尚无完整多周期触发`;
  if(s.live?.period_errors){const errors=Object.entries(s.live.period_errors).map(([period,error])=>`${PERIOD[period]}不可用：${error}`).join('；');message+=`；${errors}`;}
  if(s.replay)message+=`；逐日回放 ${integer(s.replay.bars)} 根 / ${integer(s.replay.events)} 条事件，最终状态一致`;
  text('#stock-message',message);$('#stock-message').className='message'+(s.state==='blocked_data_contract'?' warning':'');
  $$('#period-tabs button').forEach(b=>{b.disabled=b.dataset.period!=='all'&&!c.panels.some(p=>p.period===b.dataset.period);});
  if(!keepPeriod&&S.period!=='all'&&!c.panels.some(p=>p.period===S.period))S.period='all';
  renderCharts(preserve);renderEvidence(s);renderKlineSummary();
}

function renderEvidence(s){
  const holder=$('#history-coverage');holder.replaceChildren();
  const coverageRows=s.history_coverage||Object.entries(s.periods||{}).map(([period,d])=>({period,label:PERIOD[period],count:d.bars,first:d.first_close,last:d.last_close,source:'该任务原始行情'}));
  holder.append(node('h3','','历史覆盖 · 每个周期独立列出'));
  for(const row of coverageRows){const line=node('div','coverage-row');const label=button(row.label||PERIOD[row.period],()=>selectPeriod(row.period),'coverage-period');line.append(label,node('span','',row.status==='unsupported'?'接口未提供':`${integer(row.count)}${row.period==='timeshare'?'点':'根/点'}`),node('span','',row.status==='unsupported'?row.reason:`${row.first||'—'} → ${row.last||'—'}`));if(row.forming_count)line.append(statusBadge(row.forming_count+'根形成中','amber'));holder.append(line);}
  const container=$('#contract-detail');container.replaceChildren();
  if(!s.comparison_contract){container.append(node('p','','尚未运行多周期数据校验。日线结果不能代替三周期确认。'));}
  else{
    const defaultPass=s.default_contract?.state==='verified';
    const head=node('div','contract-line');head.append(node('span','','默认1股成交量容差'),statusBadge(defaultPass?'通过':'未通过',defaultPass?'green':'amber'));container.append(head);
    const compare=s.comparison_contract;const row=node('div','contract-line');row.append(node('span','',`本次所选容差 ${s.volume_tolerance??s.volume_tolerance_shares??100} 股`),statusBadge(compare.state==='verified'?'通过':'未通过',compare.state==='verified'?'green':'amber'));container.append(row);
    for(const pair of compare.pairs||[]){const line=node('div','contract-line');line.append(node('span','',`${PERIOD[pair.parent_period]} → ${PERIOD[pair.child_period]}`),node('span','',`${integer(pair.matched_parent_bars)}个匹配 / ${integer(pair.mismatched_parent_bars)}个不匹配 / ${integer(pair.incomplete_parent_bars)}个缺口`));container.append(line);}
  }
  const coverage=node('div','');coverage.style.marginTop='10px';for(const [p,d]of Object.entries(s.periods||{}))coverage.append(node('div','',`${PERIOD[p]}：${integer(d.bars)}根 · ${d.first_close?.slice(0,10)} 至 ${d.last_close?.slice(0,10)}`));container.append(coverage);
  const candidates=$('#candidate-detail');candidates.replaceChildren();let count=0;
  for(const [period,p]of Object.entries(s.periods||{}))for(const point of (p.active_candidates||[]).slice(0,6)){
    const card=node('div','candidate');card.append(node('b','',`${PERIOD[period]} · L${point.rank} · ${point.label||({third_buy:'三买候选',third_sell:'三卖候选',first_buy:'一买候选',first_sell:'一卖候选',second_buy:'二买候选',second_sell:'二卖候选'}[point.class]||point.class)}`),node('div','',`锚点 ${point.anchor_time} / ${fmt(point.price)}元 · 可见于 ${point.available_time}`),node('div','',`${STATE[point.state]||point.state} · 失效边界 ${fmt(point.invalidation)}元`));candidates.append(card);count++;
  }
  if(!count)candidates.append(node('p','','当前没有未失效候选。'));
}

const NS='http://www.w3.org/2000/svg';
function svgElement(name,attrs,value){const n=document.createElementNS(NS,name);for(const [k,v]of Object.entries(attrs||{}))n.setAttribute(k,v);if(value!==undefined)n.textContent=value;return n;}
function svgLabel(g,x,y,value,color,size=11){if(!Number.isFinite(x)||!Number.isFinite(y))return;g.append(svgElement('text',{x,y,fill:color,'font-size':size,'font-family':'Microsoft YaHei, sans-serif','font-weight':500,stroke:'#fff','stroke-width':3,'paint-order':'stroke'},value));}
function renderCharts(preserve=false){
  const ranges=new Map(preserve===true?S.charts.map(c=>[c.p.period,{range:c.chart.timeScale().getVisibleLogicalRange(),time:c.chart.timeScale().getVisibleRange(),first:c.p.bars[0]?.time,count:c.p.bars.length}]):[]);
  disposeCharts();renderSignalPicker();$$('#period-tabs button').forEach(b=>b.classList.toggle('active',b.dataset.period===S.period));
  const panels=S.data.chart.panels.filter(p=>S.period==='all'?p.kind!=='line':p.period===S.period);
  $('#charts').classList.toggle('single-chart',panels.length===1);
  if(!panels.length)$('#charts').append(node('div','empty panel',`当前结果没有${PERIOD[S.period]||S.period}K线；所选周期已保留，请查看上方数据状态或重试获取。`));
  panels.forEach((original,index)=>{
    if(original.kline_audit?.state==='invalid'){$('#charts').append(node('div','empty panel','原始K线校验失败，已停止绘图：'+original.kline_audit.errors.join('；')));return;}
    const selectedRank=S.rank==='all'?1:Number(S.rank);
    const includeAllRanks=S.rank==='all';
    const layer=(original.structure_layers||[]).find(x=>x.rank===selectedRank);
    const childLayer=(original.structure_layers||[]).find(x=>x.rank===selectedRank-1);
    const referenceNative=!!original.engine_provenance;
    const rankSegments=referenceNative?(selectedRank===1?original.segments:original.higher_segments||[]):(selectedRank===1?original.segments:(childLayer?.completed_types||[]).map(t=>({...t,state:'confirmed'})));
    const rankStrokes=referenceNative?(selectedRank===1?original.strokes:original.segments):original.strokes;
    const p={...original,strokes:rankStrokes.filter(s=>$('#show-review-objects').checked||!s.review_issues?.length),segments:rankSegments.filter(s=>$('#show-review-objects').checked||!s.review_issues?.length),centers:(original.structure_layers?(layer?layer.centers:[]):original.centers).filter(c=>$('#show-review-objects').checked||!c.review_issues?.length),signals:original.all_signals?original.all_signals.filter(s=>(includeAllRanks||s.rank===selectedRank)&&s.state!=='invalidated'):original.signals};
    const annotations=(original.signal_chart?.objects||[]).filter(point=>($('#show-review-objects').checked||point.state!=='needs_review')&&(includeAllRanks||point.rank===selectedRank)&&(S.signalSide==='all'||point.side===S.signalSide)&&($('#signal-show-invalid').checked||!['invalidated','withdrawn'].includes(point.state)));
    p.visible_signal_annotations=annotations;
    const isLine=p.kind==='line';if(isLine){p.bars=p.points.map((b,i)=>({...b,source_index:i,is_closed:true}));p.input_bars=p.bars.length;p.visible_start=0;p.strokes=[];p.segments=[];p.centers=[];p.signals=[];}
    const card=node('section','chart-panel');const head=node('div','chart-head');const title=node('div');title.append(node('strong','',PERIOD[p.period]),node('small','',`${integer(p.bars.length)}${isLine?'点':'根'}已载入 · 当前缩放不截断数据`));head.append(title,node('span','chart-note',p.note||''));
    const box=node('div','chartbox');const container=node('div','chart');const svg=svgElement('svg',{'aria-label':PERIOD[p.period]+'结构标注'});const tooltip=node('div','chart-tooltip');tooltip.hidden=true;box.append(container,svg,tooltip);card.append(head,box,node('div','chart-foot',`${p.bars[0]?.date_cn} — ${p.bars.at(-1)?.date_cn}　·　${p.coverage?.source||'TDX原始行情'}　·　可拖动/滚轮缩放${p.coverage?.forming_count?' · '+p.coverage.forming_count+'根形成中，不参与结构':''}`));$('#charts').append(card);
    const intraday=isLine||p.period.endsWith('m');
    const priceDecimals=Math.max(2,p.kline_audit?.price_precision||2);const priceFormat={type:'price',precision:priceDecimals,minMove:10**(-priceDecimals)};
    const chart=LightweightCharts.createChart(container,{width:container.clientWidth,height:container.clientHeight,layout:{background:{type:'solid',color:'#fff'},textColor:'#8293a3',fontSize:10,fontFamily:'Microsoft YaHei, sans-serif',attributionLogo:true},grid:{vertLines:{color:'#f0f3f7'},horzLines:{color:'#edf2f6'}},rightPriceScale:{borderColor:'#e4eaf0',minimumWidth:56,scaleMargins:{top:.15,bottom:.23}},timeScale:{minBarSpacing:.001,borderColor:'#e4eaf0',timeVisible:intraday,secondsVisible:false,tickMarkFormatter:(t,type)=>{const d=new Date(t*1000).toISOString();return !intraday?(type<2?d.slice(0,7):d.slice(5,10)):type<3?d.slice(0,10):d.slice(11,16);}},localization:{locale:'zh-CN',priceFormatter:v=>v.toFixed(2),timeFormatter:t=>new Date(t*1000).toISOString().replace('T',' ').slice(0,16)},crosshair:{mode:0}});
    const candles=chart.addSeries(isLine?LightweightCharts.LineSeries:LightweightCharts.CandlestickSeries,{color:'#2869ad',lineWidth:2,upColor:'#d54d53',downColor:'#168e7c',borderUpColor:'#d54d53',borderDownColor:'#168e7c',wickUpColor:'#d54d53',wickDownColor:'#168e7c',priceLineColor:S.data.summary.change_pct>=0?'#d54d53':'#168e7c',priceLineStyle:2,priceFormat});
    candles.setData(p.bars.map(b=>isLine?{time:b.time,value:b.value}:{time:b.time,open:b.open,high:b.high,low:b.low,close:b.close}));
    const volume=chart.addSeries(LightweightCharts.HistogramSeries,{priceScaleId:'volume',priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false});
    volume.setData(p.bars.filter(b=>b.volume!=null).map(b=>({time:b.time,value:b.volume,color:b.close>=b.open?'#e8a2a580':'#80c4b780'})));volume.priceScale().applyOptions({scaleMargins:{top:.87,bottom:.01},visible:false});
    const initial=SignalChart.presentation(annotations,{period:p.period,rank:S.rank,side:S.signalSide,showInvalid:true}).latest;
    chart.timeScale().setVisibleLogicalRange(S.range==='signals'&&initial?SignalChart.markerRange(initial,p.bars.length):{from:S.range==='recent'?Math.max(0,p.bars.length-300):-2,to:p.bars.length+8});
    const previous=ranges.get(p.period);if(previous?.range){if(previous.first===p.bars[0]?.time){const delta=previous.range.to>=previous.count-1?p.bars.length-previous.count:0;chart.timeScale().setVisibleLogicalRange({from:previous.range.from+delta,to:previous.range.to+delta});}else if(previous.time)chart.timeScale().setVisibleRange(previous.time);}
    const lookup=new Map(p.bars.map(b=>[b.time,b]));
    chart.subscribeCrosshairMove(param=>{const bar=lookup.get(param.time);if(!bar||!param.point){tooltip.hidden=true;return;}tooltip.hidden=false;tooltip.replaceChildren(node('b','',bar.date_cn));
      for(const [key,value]of (isLine?[['价格',fmt(bar.value)],['成交量',integer(bar.volume)+'股']]:[['开盘',fmt(bar.open)],['最高',fmt(bar.high)],['最低',fmt(bar.low)],['收盘',fmt(bar.close)],['成交量',integer(bar.volume)+'股'],['状态',bar.is_closed===false?'形成中':'已收盘']])){const line=node('div');line.append(node('span','',key),node('span','',value));tooltip.append(line);}
      tooltip.style.left=Math.max(6,Math.min(param.point.x+18,container.clientWidth-210))+'px';tooltip.style.top='12px';});
    function draw(){
      const w=container.clientWidth,h=container.clientHeight,pw=chart.timeScale().width();if(!w)return;
      svg.setAttribute('width',w);svg.setAttribute('height',h);svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.replaceChildren();const defs=svgElement('defs');const clip=svgElement('clipPath',{id:'clip-'+index});clip.append(svgElement('rect',{x:0,y:0,width:pw,height:h-24}));defs.append(clip);svg.append(defs);const g=svgElement('g',{'clip-path':`url(#clip-${index})`});svg.append(g);
      const x=i=>chart.timeScale().logicalToCoordinate(i-p.visible_start);const y=v=>candles.priceToCoordinate(v);const valid=a=>a.every(v=>v!==null&&Number.isFinite(v));
      if(S.layers.research&&window.RegimeResearch)RegimeResearch.draw({group:g,research:p.regime_research,x,y,width:pw,height:h*.83});
      if(S.layers.merged)for(const b of p.merged||[]){const a=x(b.start),end=x(b.end),hi=y(b.high),lo=y(b.low);if(!valid([a,end,hi,lo]))continue;g.append(svgElement('rect',{x:a-2,y:hi,width:Math.max(end-a+4,4),height:Math.max(lo-hi,1),fill:'none',stroke:'#7e8d99','stroke-width':.8}));}
      if(S.layers.fractals)for(const f of p.fractals||[]){const a=x(f.source),v=y(f.price);if(!valid([a,v]))continue;g.append(svgElement('circle',{cx:a,cy:v,r:2.5,fill:f.kind==='top'?'#d54d53':'#168e7c'}));}
      if(S.layers.types&&layer)for(const t of layer.completed_types){const a=x(t.start),b=x(t.end),ya=y(t.start_price),yb=y(t.end_price);if(!valid([a,b,ya,yb]))continue;g.append(svgElement('line',{x1:a,y1:ya,x2:b,y2:yb,stroke:'#a3793a','stroke-width':3.5}));}
      if(S.layers.centers)for(const c of p.centers){const a=x(c.start),b=x(c.end),hi=y(c.zg),lo=y(c.zd);if(!valid([a,b,hi,lo]))continue;g.append(svgElement('rect',{x:Math.min(a,b),y:Math.min(hi,lo),width:Math.abs(b-a),height:Math.abs(lo-hi),fill:'#2a9d8e','fill-opacity':.09,stroke:'#50a99e','stroke-width':1}));if(b>=0&&a<=pw)svgLabel(g,Math.max(6,Math.min(a+6,pw-130)),Math.max(16,hi-7),`${c.zd.toFixed(2)}–${c.zg.toFixed(2)}`,'#288d81',10);}
      if(S.layers.strokes){const ends=new Map();for(const s of p.strokes){const a=x(s.start),b=x(s.end),ya=y(s.start_price),yb=y(s.end_price);if(!valid([a,b,ya,yb]))continue;g.append(svgElement('line',{x1:a,y1:ya,x2:b,y2:yb,stroke:'#8c9fb3','stroke-width':1,'stroke-opacity':.7,'stroke-dasharray':s.state==='confirmed'?'none':'3 3'}));ends.set(s.end,{price:s.end_price,top:s.direction==='up'});}for(const [i,e]of ends){const xx=x(i),yy=y(e.price);if(!valid([xx,yy])||xx<0||xx>pw)continue;const cy=yy+(e.top?-5:5);g.append(svgElement('path',{d:e.top?`M ${xx-2} ${cy-2} L ${xx+2} ${cy-2} L ${xx} ${cy+2} Z`:`M ${xx-2} ${cy+2} L ${xx+2} ${cy+2} L ${xx} ${cy-2} Z`,fill:'#5d7992'}));}}
      if(S.layers.segments)for(const s of p.segments){const a=x(s.start),b=x(s.end),ya=y(s.start_price),yb=y(s.end_price);if(!valid([a,b,ya,yb]))continue;const disputed=!!s.review_issues?.length;const color=s.state==='confirmed'&&!disputed?'#2869ad':'#bc791e';g.append(svgElement('line',{x1:a,y1:ya,x2:b,y2:yb,stroke:color,'stroke-width':2.3,'stroke-dasharray':s.state==='confirmed'&&!disputed?'none':'7 4'}));if(s===p.segments.at(-1)&&b>5&&b<pw-40){g.append(svgElement('circle',{cx:b,cy:yb,r:2.5,fill:'#fff',stroke:color,'stroke-width':1.5}));svgLabel(g,b+5,yb+(s.direction==='up'?-10:15),s.end_price.toFixed(2),color);}}
      p.signal_render_stats=S.layers.signals?SignalChart.draw({group:g,items:annotations,x,y,width:pw,height:h*.83,selected:S.signalSelected,showTimes:$('#signal-show-time').checked,showRank:includeAllRanks,onSelect:selectChartSignal}):{visible_markers:0,visible_labels:0};updateSignalVisibility();
      svgLabel(svg,9,h-40,'成交量','#9ba9b6',9);
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(()=>requestAnimationFrame(draw));
    const resize=()=>{if(container.clientWidth){const range=chart.timeScale().getVisibleLogicalRange();chart.resize(container.clientWidth,container.clientHeight);if(range)chart.timeScale().setVisibleLogicalRange(range);requestAnimationFrame(draw);}};
    const observer=new ResizeObserver(resize);observer.observe(container);S.charts.push({chart,candles,svg,draw,resize,observer,p,container,card});requestAnimationFrame(draw);
  });
  updateSignalVisibility();renderSignalRail();window.chartReady=true;window.workbenchProof=()=>({selected:S.selected,version:'4.4.2',live:S.data?.summary?.live||null,panels:S.charts.map(c=>({period:c.p.period,bars:c.p.bars.length,segments:c.p.segments.length,first:c.p.bars[0]?.date_cn,last:c.p.bars.at(-1)?.date_cn,forming:c.p.bars.at(-1)?.is_closed===false,visible:c.chart.timeScale().getVisibleLogicalRange(),signal_annotations:c.p.visible_signal_annotations?.length||0,signal_render:c.p.signal_render_stats||null})),executionAllowed:false});
}

async function selectPeriod(period,date=null){
  if(!S.data?.available)return;const symbol=S.selected,job=S.job,stockRequest=S.stockRequest;
  const liveContext=(!job&&$('#live-quote').checked)||S.data.summary.live||(S.stockLoading&&S.loadingLive);
  if(liveContext&&['day','30m','5m','1m','all'].includes(period)){S.period=period;await selectStock(symbol);return;}
  if(liveContext){
    $('#live-quote').checked=false;S.period=period;const loading=selectStock(symbol),request=S.stockRequest;await loading;
    if(S.selected!==symbol||S.job!==job||S.stockRequest!==request||!S.data?.available)return;
    text('#live-quote-status','扩展周期查看历史快照；点击刷新实时K线返回日/30分/5分/1分实时图');return selectPeriod(period,date);
  }
  S.periodController?.abort();S.periodController=null;const periodRequest=S.periodRequest=(S.periodRequest||0)+1,bundle=S.data;
  if(period!=='all'&&(!S.data.chart.panels.some(p=>p.period===period)||['timeshare','five_days'].includes(period))){
    const controller=new AbortController();S.periodController=controller;const timeout=setTimeout(()=>controller.abort(),60000);
    try{const params=new URLSearchParams({period});if(S.job)params.set('job',S.job);if(date)params.set('date',date);const result=await api('/api/stock/'+symbol+'?'+params,undefined,{signal:controller.signal});if(S.selected!==symbol||S.job!==job||S.stockRequest!==stockRequest||S.periodRequest!==periodRequest||S.data!==bundle)return;
      if(!result.available){disposeCharts();$('#charts').append(node('div','empty panel',result.reason));toast(result.reason);return;}
      S.data.chart.panels=S.data.chart.panels.filter(p=>p.period!==period);S.data.chart.panels.push(result.panel);
    }catch(error){if(S.periodRequest===periodRequest&&S.selected===symbol&&S.job===job&&S.stockRequest===stockRequest)toast(error.name==='AbortError'?'周期数据等待超过60秒，请重试':error.message);return;}
    finally{clearTimeout(timeout);if(S.periodController===controller)S.periodController=null;}
  }
  S.period=period;$('#extended-period').value=period==='all'?'':period;renderCharts();renderKlineSummary();
}
function setRange(kind){S.range=kind;for(const c of S.charts)c.chart.timeScale().setVisibleLogicalRange({from:kind==='recent'?Math.max(0,c.p.bars.length-300):-2,to:c.p.bars.length+8});}
function zoom(factor){for(const c of S.charts){const r=c.chart.timeScale().getVisibleLogicalRange();if(!r)continue;const center=(r.from+r.to)/2;const half=(r.to-r.from)*factor/2;c.chart.timeScale().setVisibleLogicalRange({from:center-half,to:center+half});}}
async function locateDate(){const date=$('#history-date').value;if(!date){toast('请选择要查看的日期');return;}if(['timeshare','five_days'].includes(S.period)){await selectPeriod(S.period,date);return;}
  for(const c of S.charts){const first=c.p.bars[0].date_cn.slice(0,10),last=c.p.bars.at(-1).date_cn.slice(0,10);if(date<first||date>last){toast(`${PERIOD[c.p.period]}可取范围是 ${first} 至 ${last}`);continue;}
    const at=c.p.bars.findIndex(b=>b.date_cn.slice(0,10)>=date);c.chart.timeScale().setVisibleLogicalRange({from:Math.max(-2,at-60),to:Math.min(c.p.bars.length+5,at+80)});}
}

function renderJobs(jobs){
  const list=$('#jobs-list');list.replaceChildren();if(!jobs.length){list.append(node('div','empty panel','还没有任务。新建任务，开始全市场研究。'));return;}
  for(const j of jobs){
    const card=node('article','job-card panel');const header=node('div','job-header');const title=node('div');title.append(node('h3','',j.title),node('div','job-meta',`${j.created.replace('T',' ').slice(0,19)} · ${j.settings.refresh?'重新获取TDX行情':'使用历史缓存'} · ${j.settings.workers}并发 · 容差${j.settings.volume_tolerance}股`));header.append(title,statusBadge(JOB_STATE[j.state]||j.state,j.state==='completed'?'green':j.state==='running'?'':'amber'));card.append(header);
    const progress=node('div','job-progress');const bar=node('progress');bar.max=j.total;bar.value=j.done;progress.append(bar,node('strong','',((j.done/j.total)*100).toFixed(1)+'%'));card.append(progress);
    for(const p of j.progress||[]){const phase=node('div','stock-progress');phase.append(node('b','',p.name||p.symbol),node('span','',p.message));if(p.total){const inner=node('progress');inner.max=p.total;inner.value=p.completed||0;phase.append(inner);}phase.append(node('small','',`本股已用 ${Math.floor(p.elapsed_seconds||0)} 秒${p.remaining_seconds>0?' · 分时采集预计还需约 '+Math.ceil(p.remaining_seconds/60)+' 分钟':''}`));card.append(phase);}
    const bottom=node('div','job-bottom');bottom.append(node('span','',`${integer(j.done)} / ${integer(j.total)}　成功 ${integer(j.success)}　失败 ${integer(j.failed)}`));const controls=node('div','job-controls');
    const action=async a=>{try{await api('/api/jobs/'+j.id+'/'+a,{});await refreshOverview();toast(a==='pause'?'已请求暂停，当前股票完成后保留断点':'任务状态已更新');}catch(e){toast(e.message);}};
    if(['running','starting','queued'].includes(j.state))controls.append(button('暂停',()=>action('pause')));
    if(['paused','interrupted','cancelled'].includes(j.state)&&j.done<j.total)controls.append(button('继续',()=>action('resume')));
    if(j.failed&&['completed','interrupted','paused','cancelled'].includes(j.state))controls.append(button('重试失败项',()=>action('retry')));
    if(['running','queued','paused','interrupted'].includes(j.state))controls.append(button('停止',()=>action('cancel')));
    controls.append(button(j.total===1?'打开该股图表':'查看结果',()=>showJobResults(j)));
    if(j.failed)controls.append(button('失败原因',()=>showErrors(j.id)));bottom.append(controls);card.append(bottom);
    if(j.message)card.append(node('div','job-message',j.message));
    if(j.mode==='replay')card.append(node('div','job-meta','逐日回放逐前缀重算，历史较长的单股耗时较多；暂停会等待正在处理的股票完成。'));
    list.append(card);
  }
}
async function showErrors(job){try{const data=await api('/api/errors?job='+encodeURIComponent(job));const box=$('#errors-content');box.replaceChildren();for(const e of data.rows){const row=node('div','error-row');row.append(node('b','',e.symbol+' '+e.name),node('div','',e.error));box.append(row);}$('#errors-panel').hidden=false;$('#errors-panel').scrollIntoView({behavior:'smooth'});}catch(e){toast(e.message);}}

function openJob(symbol=null){$('#job-form').reset();text('#form-error','');$('#job-cutoff').max=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});$('#job-scope').value=symbol?'selected':'all';$('#job-symbols').value=symbol||'';$('#symbols-field').hidden=!symbol;updateJobNote();$('#job-dialog').showModal();}
function updateJobNote(){const mode=$('#job-mode').value;if(mode==='full')$('#job-refresh').checked=true;text('#job-note',mode==='full'?'重新取10种原生K线、日线聚合5日K线，并逐交易日存档历史分时；各周期可能有不同历史上限，竞价历史不可用。全市场此任务耗时较长，并发最多3只。':mode==='replay'?'将从每只股票最早可取记录逐日重算。全市场回放计算量很大，进度按完成股票计数，可暂停后继续。':'使用截止时点前的全部可取历史；结果逐只保存。默认1股校验和所选容差对照分别保留。');}
async function submitJob(e){e.preventDefault();const b=$('#submit-job');b.disabled=true;b.textContent='正在检查行情服务…';text('#form-error','');try{const date=$('#job-cutoff').value;const body={mode:$('#job-mode').value,scope:$('#job-scope').value,symbols:$('#job-symbols').value.split(/[\s,，;；]+/).filter(Boolean),workers:Number($('#job-workers').value),refresh:$('#job-refresh').checked,volume_tolerance:Number($('#job-tolerance').value)};if(date)body.cutoff=date+'T15:00:00+08:00';const result=await api('/api/jobs',body);S.followJob=result.id;sessionStorage.setItem('chanlun-follow-job',result.id);$('#job-dialog').close();view('tasks');await refreshOverview();toast(`任务已创建，共${integer(result.total)}只；完成后自动打开结果`);}catch(error){text('#form-error',error.message);}finally{b.disabled=false;b.textContent='加入任务队列 →';}}
function download(blob,name){const a=document.createElement('a');const url=URL.createObjectURL(blob);a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}
async function pngWithEvidence(blob,metadata){
  const bytes=new Uint8Array(await blob.arrayBuffer());
  const prefix=new TextEncoder().encode('Description\0\0\0\0\0');
  const value=new TextEncoder().encode(JSON.stringify(metadata));
  const payload=new Uint8Array(prefix.length+value.length);payload.set(prefix);payload.set(value,prefix.length);
  const chunk=new Uint8Array(payload.length+12);const view=new DataView(chunk.buffer);view.setUint32(0,payload.length);chunk.set(new TextEncoder().encode('iTXt'),4);chunk.set(payload,8);
  let crc=0xffffffff;for(const byte of chunk.subarray(4,chunk.length-4)){crc^=byte;for(let bit=0;bit<8;bit++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}view.setUint32(chunk.length-4,(crc^0xffffffff)>>>0);
  return new Blob([bytes.subarray(0,bytes.length-12),chunk,bytes.subarray(bytes.length-12)],{type:'image/png'});
}
async function exportPNG(){
  if(!S.charts.length)return;const control=$('#export-png');control.disabled=true;
  try{
    await document.fonts.ready;S.charts.forEach(c=>c.draw());await new Promise(requestAnimationFrame);
    const width=1800,scale=2,margin=40;const chartHeight=380;const height=190+S.charts.length*(chartHeight+76)+100;
    const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;const ctx=canvas.getContext('2d');ctx.fillStyle='#f3f5f8';ctx.fillRect(0,0,width,height);
    const {summary:s,chart:data}=S.data;ctx.fillStyle='#1c3046';ctx.font='600 32px Microsoft YaHei';ctx.fillText(s.name+'  '+s.symbol.slice(2)+' · '+(s.algorithm||'原版本'),margin,65);ctx.font='16px Microsoft YaHei';ctx.fillStyle='#74889c';ctx.fillText(`TDX不复权 · 行情截止 ${s.last_close_time} · 北京时间`,margin,99);
    ctx.fillStyle=s.change_pct>=0?'#d24b52':'#168e7c';ctx.font='bold 36px Consolas';ctx.textAlign='right';ctx.fillText(`${fmt(s.price)}  ${s.change_pct>=0?'+':''}${fmt(s.change_pct)}%`,width-margin,65);ctx.textAlign='left';ctx.font='16px Microsoft YaHei';ctx.fillStyle='#657f94';ctx.fillText(`灰：笔　 蓝：线段　 框：L${S.rank}中枢　 △买侧 ▽卖侧　 ◇依据 ◆触发`,margin,142);
    let top=170;
    for(const c of S.charts){
      ctx.fillStyle='#fff';ctx.fillRect(margin,top,width-margin*2,chartHeight+65);ctx.fillStyle='#28465f';ctx.font='600 21px Microsoft YaHei';ctx.fillText(PERIOD[c.p.period],margin+16,top+32);ctx.font='14px Microsoft YaHei';ctx.fillStyle='#8c753e';ctx.textAlign='right';ctx.fillText(c.p.note||'',width-margin-16,top+31);ctx.textAlign='left';
      const screenshot=c.chart.takeScreenshot();ctx.drawImage(screenshot,margin,top+45,width-margin*2,chartHeight);
      const serialized=new XMLSerializer().serializeToString(c.svg);const blob=new Blob([serialized],{type:'image/svg+xml;charset=utf-8'});const url=URL.createObjectURL(blob);const img=new Image();await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=reject;img.src=url;});ctx.drawImage(img,margin,top+45,width-margin*2,chartHeight);URL.revokeObjectURL(url);
      top+=chartHeight+76;
    }
    ctx.fillStyle='#5b758b';ctx.font='15px Microsoft YaHei';ctx.fillText(s.result_text||'',margin,top+20);const tolerance=s.volume_tolerance??s.volume_tolerance_shares;ctx.font='12px Microsoft YaHei';ctx.fillText(`${s.algorithm||'原版本'}研究口径 · execution_allowed=false · 容差 ${tolerance??'未校验'} 股 · 默认校验 ${s.default_contract?.state||'未运行'} · TradingView Lightweight Charts™`,margin,top+47);
    const hashes=Object.entries(data.input_sha256||{}).map(([k,v])=>`${k}:${v.slice(0,12)}`).join('  ');ctx.fillText('输入 SHA256 '+hashes+' · 完整证据请导出JSON',margin,top+69);
    const rawPNG=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!rawPNG)throw Error('PNG导出失败');
    const png=await pngWithEvidence(rawPNG,{symbol:s.symbol,as_of:data.as_of||s.as_of,market_as_of:s.last_close_time,definition_mode:data.definition_mode,approximation_loss:data.approximation_loss,input_sha256:data.input_sha256,execution_allowed:false,volume_tolerance:tolerance,default_contract:s.default_contract,comparison_contract:s.comparison_contract,visible_layers:S.layers,signal_chart:{rank:S.rank,selected:S.signalSelected,show_invalid:$('#signal-show-invalid').checked,show_times:$('#signal-show-time').checked},history_coverage:s.history_coverage,visible_ranges:window.workbenchProof().panels});
    download(png,`${s.name}_${s.algorithm||'原版本'}_${S.period==='all'?'多周期':PERIOD[S.period]}.png`);window.lastExport={width,height,bytes:png.size,symbol:s.symbol};toast('PNG已导出');
  }catch(error){toast('导出失败：'+(error.message||'图层渲染失败'));console.error(error);}finally{control.disabled=false;}
}

$$('.nav').forEach(b=>b.onclick=()=>view(b.dataset.view));$$('.pin').forEach(b=>b.onclick=()=>{view('market');S.job='';$('#job-filter').value='';selectStock(b.dataset.symbol);refreshMarket();});
$('#go-tasks').onclick=()=>view('tasks');$('#new-job').onclick=()=>openJob();$('#new-job-2').onclick=()=>openJob();$('#rerun-stock').onclick=()=>openJob(S.selected);
$('#close-dialog').onclick=$('#cancel-dialog').onclick=()=>$('#job-dialog').close();$('#job-form').onsubmit=submitJob;$('#job-scope').onchange=()=>$('#symbols-field').hidden=$('#job-scope').value!=='selected';$('#job-mode').onchange=updateJobNote;
$('#search').oninput=e=>{clearTimeout(S.searchTimer);S.searchTimer=setTimeout(()=>{S.q=e.target.value.trim();S.offset=0;refreshMarket({selectFirst:true});},220);};
for(const [id,key]of [['#exchange','exchange'],['#result-filter','filter'],['#job-filter','job']])$(id).onchange=e=>{S[key]=e.target.value;S.offset=0;if(key==='job'){S.selected='';clearStockDetail('正在打开所选任务的结果…');}refreshMarket({selectFirst:true});};
$('#prev-page').onclick=()=>{S.offset=Math.max(0,S.offset-S.limit);refreshMarket();};$('#next-page').onclick=()=>{S.offset+=S.limit;refreshMarket();};
$$('#period-tabs button').forEach(b=>b.onclick=()=>selectPeriod(b.dataset.period));$$('[data-layer]').forEach(input=>input.onchange=()=>{S.layers[input.dataset.layer]=input.checked;S.charts.forEach(c=>c.draw());});
$('#extended-period').onchange=e=>{if(e.target.value)selectPeriod(e.target.value);};$('#range-all').onclick=()=>setRange('all');$('#range-recent').onclick=()=>setRange('recent');$('#zoom-in').onclick=()=>zoom(.65);$('#zoom-out').onclick=()=>zoom(1.5);$('#locate-date').onclick=locateDate;
function renderLiveStatus(){const m=S.data?.summary?.live;const current=S.data?.chart?.panels?.find(p=>p.period===S.period)||S.data?.chart?.panels?.[0];const session=current?.live_session;const closed=current?.bars?.filter(b=>b.is_closed!==false).length??m?.confirmed_history_bars;text('#live-quote-status',m?`K线获取 ${m.received_at.slice(11,19)} · 最新交易日 ${m.latest_bar_at.slice(0,10)} · ${m.forming?'今日K线形成中':'最新K线已收盘'}${m.latest_session_is_today?'':' · 尚无今日K线，可能休市/停牌/行情未更新'} · ${PERIOD[current?.period]||'当前周期'}闭合K线 ${integer(closed)} 根 · ${session?.rebuilt?'全量初始化/修订重建':session?.restored?'热会话恢复，追加 '+integer(session.appended)+' 根':'已预热'} · TDX不复权`:'历史任务快照；点击刷新实时K线查看最新行情');}
async function quoteTick(force=false){
  if(!S.selected||S.job||S.stockLoading||(!force&&((S.stockFailedKey&&(!S.stockRetryAt||Date.now()<S.stockRetryAt))||!$('#live-quote').checked||document.hidden||S.view!=='market'))||S.quotePending)return;
  if(!S.data?.available){await selectStock(S.selected);return;}
  S.quotePending=true;const symbol=S.selected,token=S.stockRequest,period=S.period,controller=new AbortController();S.quoteController=controller;let timedOut=false;const timeout=setTimeout(()=>{timedOut=true;controller.abort();},60000);
  try{
    const q=await api('/api/live-stock/'+symbol+'?period='+(['day','30m','5m','1m','all'].includes(period)?period:'day')+(force?'&fresh=1':''),undefined,{signal:controller.signal});
    if(symbol===S.selected&&token===S.stockRequest&&period===S.period&&$('#live-quote').checked){
      if(!q.available)throw Error(q.reason||'实时数据暂不可用');
      if(q.summary?.symbol&&q.summary.symbol!==symbol)throw Error('实时结果股票与选择不一致');
      S.stockFailedKey=null;S.stockRetryAt=null;S.data=q;renderStock(true,true);renderLiveStatus();
    }
  }catch(e){
    if(symbol===S.selected&&token===S.stockRequest&&(timedOut||e.name!=='AbortError')){S.stockFailedKey=JSON.stringify([symbol,S.job,true,period]);S.stockRetryAt=Date.now()+60000;$('#live-quote-status').replaceChildren(node('span','','K线更新失败：'+(timedOut?'等待服务器超过60秒':e.message)+'；保留上次数据，获取时间未更新。60秒后自动重试。'),button('重试实时更新',()=>quoteTick(true),'button small'));}
  }finally{clearTimeout(timeout);if(S.quoteController===controller){S.quoteController=null;S.quotePending=false;}}
}
$('#refresh-now').onclick=()=>{S.job='';$('#job-filter').value='';$('#live-quote').checked=true;if(!['day','30m','5m','1m','all'].includes(S.period))S.period='day';if(S.data?.summary?.live)quoteTick(true);else selectStock(S.selected);};
$('#live-quote').onchange=()=>{if($('#live-quote').checked){S.job='';$('#job-filter').value='';if(!['day','30m','5m','1m','all'].includes(S.period))S.period='day';selectStock(S.selected);}else selectStock(S.selected);};setInterval(()=>quoteTick(),15000);
$('#export-json').onclick=async()=>{if(!S.data?.available)return;const b=$('#export-json');b.disabled=true;try{const params=new URLSearchParams({full:'1'});if(S.job)params.set('job',S.job);const full=await api(S.data.summary.live?'/api/live-stock/'+S.selected+'?period='+(['day','30m','5m','1m','all'].includes(S.period)?S.period:'day')+'&full=1':'/api/stock/'+S.selected+'?'+params);download(new Blob([JSON.stringify(full,null,2)],{type:'application/json'}),S.data.summary.name+'_'+(S.data.summary.algorithm||'原版本')+'_结构证据.json');}catch(e){toast(e.message);}finally{b.disabled=false;}};$('#export-png').onclick=exportPNG;
$('#close-errors').onclick=()=>$('#errors-panel').hidden=true;
$('#market-day').onclick=()=>{S.marketContextPeriod='day';$$('#view-indices .segmented button').forEach(x=>x.classList.toggle('active',x.id==='market-day'));refreshMarketContext('day',true);};
$('#market-30m').onclick=()=>{S.marketContextPeriod='30m';$$('#view-indices .segmented button').forEach(x=>x.classList.toggle('active',x.id==='market-30m'));refreshMarketContext('30m',true);};
$('#market-5m').onclick=()=>{S.marketContextPeriod='5m';$$('#view-indices .segmented button').forEach(x=>x.classList.toggle('active',x.id==='market-5m'));refreshMarketContext('5m',true);};
$('#benchmark-lookup-form').onsubmit=event=>{event.preventDefault();let code=$('#benchmark-lookup-input').value.trim();if(/^\d{6}$/.test(code))code=(code.startsWith('399')?'sz':'sh')+code;else if(code.startsWith('^'))code=code.toUpperCase();else code=code.toLowerCase();if(!/^(sh|sz)\d{6}$|^\^[A-Z0-9.]+$/.test(code)){toast('请输入 sh/sz 指数代码或已配置的全球指数代码');return;}openBenchmark(code);};
$('#industry-search').oninput=()=>{industryPage=0;renderIndustryPage();};$('#industry-sort').onchange=()=>{industryPage=0;renderIndustryPage();};
$('#industry-prev').onclick=()=>{industryPage=Math.max(0,industryPage-1);renderIndustryPage();};$('#industry-next').onclick=()=>{industryPage++;renderIndustryPage();};
$('#benchmark-close').onclick=()=>$('#benchmark-dialog').close();
$('#benchmark-dialog').addEventListener('close',()=>{S.benchmarkRequest++;benchmarkResizeObserver?.disconnect();benchmarkResizeObserver=null;benchmarkChart?.remove();benchmarkChart=null;benchmarkOverlay=null;benchmarkDraw=null;});
$('#benchmark-period').onclick=event=>{const choice=event.target.closest('button[data-period]');if(!choice||!S.benchmarkCode)return;const period=choice.dataset.period;if(S.benchmarkDetail?.index?.period===period)return;S.marketContextPeriod=period;$$('#view-indices .segmented button').forEach(button=>button.classList.toggle('active',button.id==={'day':'market-day','30m':'market-30m','5m':'market-5m'}[period]));loadBenchmarkDetail(S.benchmarkCode,period);};
$('#benchmark-layers').onchange=event=>{const input=event.target.closest('input[data-index-layer]');if(!input)return;S.benchmarkLayers[input.dataset.indexLayer]=input.checked;benchmarkDraw?.();};
$('#benchmark-range-controls').onclick=event=>{const choice=event.target.closest('button[data-range]');if(choice)setBenchmarkRange(choice.dataset.range);};
window.addEventListener('resize',()=>{if($('#benchmark-dialog')?.open&&benchmarkChart){const host=$('#benchmark-chart .index-chart-canvas');if(host?.clientWidth){benchmarkChart.resize(host.clientWidth,host.clientHeight);benchmarkDraw?.();}}});
$('#start-data').onclick=async()=>{const b=$('#start-data');b.disabled=true;text('#data-status','正在检查行情服务，请稍候…');try{const result=await api('/api/data-service',{});text('#data-status',result.ready?'行情服务可用，真实报价请求已通过。':'行情暂无返回');}catch(e){text('#data-status',e.message);}finally{b.disabled=false;}};
$('#refresh-universe').onclick=async()=>{const b=$('#refresh-universe');b.disabled=true;try{const data=await api('/api/universe/refresh',{});text('#data-status',`已更新供应商股票池：${integer(data.count)}只。已有任务保持原股票范围。`);refreshOverview();refreshMarket();}catch(e){text('#data-status',e.message);}finally{b.disabled=false;}};
window.addEventListener('error',e=>console.error(e.message));
S.followJob=sessionStorage.getItem('chanlun-follow-job');
(async()=>{try{const h=await api('/api/health');if(h.offline_start)$('#live-quote').checked=false;}catch(e){text('#live-quote-status',e.message);}await Promise.all([refreshOverview(),refreshMarket(),selectStock(S.selected)]);window.workbenchReady=true;})();
setInterval(()=>{if(!document.hidden){if(S.view==='market'||S.view==='tasks'||S.followJob)refreshOverview();if(S.view==='market')refreshMarket();}},2500);

$('#structure-rank').onchange=()=>{S.rank=$('#structure-rank').value==='all'?'all':Number($('#structure-rank').value);if(S.data?.chart)renderCharts();};
$('#signal-side-filter').onclick=event=>{const choice=event.target.closest('button[data-side]');if(!choice)return;S.signalSide=choice.dataset.side;$$('#signal-side-filter button').forEach(button=>button.classList.toggle('active',button===choice));if(S.data?.chart)renderCharts();};
$('#signal-rail-latest').onclick=()=>$('#signal-latest').click();

const SIGNAL_LABELS={bottom_reversal:'底部反转研究',top_reversal:'顶部反转研究',first_buy:'一买候选',second_buy:'二买候选',third_buy:'三买候选',first_sell:'一卖候选',second_sell:'二卖候选',third_sell:'三卖候选'};
let monitorLoaded=false,alertBaseline=null,monitorPoll=false;
async function refreshMonitor(){if(monitorPoll)return;monitorPoll=true;try{const m=await api('/api/monitor');
 text('#monitor-quote-count',integer(m.counts.quotes));text('#monitor-structure-count',integer(m.counts.structures));text('#monitor-alert-count',integer(m.counts.unread));text('#monitor-session',m.session.state==='session_window'?'交易窗口':'非交易时段');
 if(!monitorLoaded){$('#monitor-scope').value=m.config.scope;$('#monitor-symbols').value=m.config.symbols.join(',');$('#monitor-mode').value=m.config.structure_mode;if($('#monitor-intraday-period'))$('#monitor-intraday-period').value=m.config.intraday_period||'1m';$('#monitor-quote-interval').value=m.config.quote_interval;$('#monitor-structure-interval').value=m.config.structure_interval;$('#monitor-enabled').checked=m.config.enabled;$('#monitor-history').checked=m.config.refresh_history;monitorLoaded=true;}
 const runs=$('#monitor-runs');runs.replaceChildren();for(const r of m.runs){const p=r.payload;const line=node('div','monitor-line');line.textContent=`${r.state} · ${p.kind} · ${integer(p.done)}/${integer(p.total)} · 失败 ${p.failed} · 新提醒 ${p.alerts} · ${r.updated}`;if(p.quotes)line.append(node('p','caption',`报价 ${p.quotes.observed}/${p.quotes.requested}，失败批次 ${p.quotes.failed_batches.length}，缺失 ${p.quotes.missing.length}`));if(p.error)line.append(node('p','',p.error));runs.append(line);}if(!m.runs.length)runs.append(node('p','','尚未扫描。'));
 const signals=$('#monitor-signals');signals.replaceChildren();for(const row of m.signals){const p=row.payload,tr=node('tr');for(const value of [row.symbol+' / '+p.period,SIGNAL_LABELS[p.class]||p.class,STATE[row.state]||row.state,`${fmt(p.price)} / ${p.invalidation_operator} ${fmt(p.invalidation)}`,p.available_time])tr.append(node('td','',value));tr.onclick=async()=>{view('market');S.job='';$('#job-filter').value='';$('#live-quote').checked=true;S.period=p.period;S.rank=p.rank;S.signalSide='all';await selectStock(row.symbol);if(!S.data?.available)return;$('#structure-rank').value=String(p.rank);renderCharts();const marker=signalObjects().find(x=>x.id===(p.source_signal_id||p.signal_id)||x.signal_id===p.native_signal_id);if(marker){if(['invalidated','withdrawn'].includes(marker.state)){$('#signal-show-invalid').checked=true;renderCharts();}selectChartSignal(marker);$('#signal-focus').click();}};signals.append(tr);}if(!m.signals.length){const tr=node('tr');const td=node('td','','尚无已扫描的活动候选。');td.colSpan=5;tr.append(td);signals.append(tr);}
 const alerts=$('#monitor-alerts');alerts.replaceChildren();for(const a of m.alerts){const p=a.payload,line=node('div','monitor-line');line.textContent=`${a.symbol} · ${a.kind==='intraday_research_alert'?'盘中结构研究提醒':a.kind==='quote_boundary_crossed'?'实时报价越界（待闭合确认）':a.kind==='signal_withdrawn'?'结构撤回':'结构变化'} · ${SIGNAL_LABELS[p.class]||p.class||''} · ${a.created}`;alerts.append(line);}
 const latest=m.alerts[0]?.id||0;if(alertBaseline!==null&&latest>alertBaseline&&window.Notification&&Notification.permission==='granted'){const fresh=m.alerts.filter(a=>a.id>alertBaseline);for(const a of fresh.slice(0,3)){const n=new Notification('缠论V4 研究信号提醒',{body:a.symbol+' · '+(SIGNAL_LABELS[a.payload.class]||a.kind),tag:String(a.id)});n.onclick=()=>{window.focus();view('market');selectStock(a.symbol);};}}alertBaseline=latest;
 text('#monitor-status',m.busy?'扫描正在运行，结果逐股保存。':`扫描待命 · ${m.config.enabled?'自动扫描已开启':'自动扫描未开启'}`);
 }catch(e){text('#monitor-status',e.message);}finally{monitorPoll=false;}}
$('#monitor-refresh').onclick=refreshMonitor;
$('#monitor-save').onclick=async()=>{try{await api('/api/monitor/config',{scope:$('#monitor-scope').value,symbols:$('#monitor-symbols').value.split(/[，,\s]+/).filter(Boolean),structure_mode:$('#monitor-mode').value,intraday_period:$('#monitor-intraday-period')?.value||'1m',quote_interval:Number($('#monitor-quote-interval').value),structure_interval:Number($('#monitor-structure-interval').value),enabled:$('#monitor-enabled').checked,refresh_history:$('#monitor-history').checked});toast('扫描配置已保存');refreshMonitor();}catch(e){toast(e.message);}};
for(const[id,kind]of [['#monitor-quotes','quotes'],['#monitor-structures','structures']])$(id).onclick=async()=>{try{await api('/api/monitor/scan',{kind});refreshMonitor();}catch(e){toast(e.message);}};
$('#monitor-stop').onclick=async()=>{await api('/api/monitor/stop',{});refreshMonitor();};
$('#monitor-ack').onclick=async()=>{await api('/api/monitor/acknowledge',{});refreshMonitor();};
$('#monitor-notify').onclick=async()=>{if(!window.Notification){toast('当前浏览器不支持桌面提醒');return;}const permission=await Notification.requestPermission();toast(permission==='granted'?'桌面提醒已启用；保持程序和页面运行':'桌面提醒未授权，应用内提醒仍可查看');};
let backtestPollInFlight=false,backtestPollingActive=false,backtestLastSnapshot='';
const backtestFailureState=new Map();
function backtestStateLabel(run,summary){
  if(run.state==='running')return '运行中';
  if(run.state==='interrupted')return '已中断 · 可续跑';
  if(run.state==='stopping')return '停止中 · 等待当前股票';
  if(run.state==='completed_with_errors'||(run.state==='complete'&&((summary.failed||0)>0||(summary.skipped_missing_count||0)>0)))return '已完成 · 有失败或缺失';
  if(run.state==='complete'||run.state==='completed')return '已完成';
  return run.state||'未知状态';
}
function renderBacktestRun(run){
  const summary=run.summary||{},metrics=summary.metrics||{},total=Number(run.total)||0;
  const success=Math.max(0,Number(summary.completed)||0),failed=Math.max(0,Number(summary.failed)||0);
  const processed=Math.min(total,Number(summary.completed??0)+Number(summary.failed??0));
  const requested=Math.max(total,Number(summary.requested_total??run.requested_total??total)||total);
  const skipped=Math.max(0,Number(summary.skipped_missing_count??run.skipped_missing_count)||0);
  const remaining=Math.max(0,total-processed),successComplete=(summary.successful_coverage_complete??(success===requested))&&success===requested&&failed===0&&skipped===0;
  const native=run.engine==='native'||String(summary.profile||'').startsWith('v4_native_chan_next_open_t1_');
  const confirmations=summary.confirmations??summary.signals??0,box=node('section','panel backtest-run');
  box.append(node('h2','',run.id),node('p','',`${backtestStateLabel(run,summary)} · ${native?'V4原生固定引擎':'历史代理模型'}`));
  box.append(node('p','backtest-coverage',`处理进度 ${integer(processed)} / ${integer(total)} · 失败 ${integer(failed)} · 待处理 ${integer(remaining)}`));
  const cacheVerified=summary.cache_preflight_verified??run.cache_selection==='frozen_per_symbol_whole_sources';
  box.append(node('p','backtest-coverage',cacheVerified?`缓存预检通过 ${integer(total)} / ${integer(requested)} 只 · 跳过缺失/历史不足 ${integer(skipped)} 只`:'旧批次未做缓存预检；不能由任务总数推定有数据的股票数。'));
  box.append(node('p','backtest-coverage',`成功覆盖 ${integer(success)} / ${integer(requested)} 只${successComplete?' · 完整':' · 不完整'}`));
  if(failed||skipped){
    box.append(node('p','backtest-warning',`成功 ${integer(success)} 只 · 失败 ${integer(failed)} 只 · 未进入任务（缺缓存）${integer(skipped)} 只；统计只汇总成功股票。`));
    const details=node('details','backtest-failure-details'),summaryNode=node('summary','',`查看失败明细 (${integer(failed)})${skipped?' · 缺失 '+integer(skipped):''}`);
    const state=backtestFailureState.get(run.id)||{open:false,offset:0,page:null};
    if(state.failureCount!==failed){state.page=null;state.offset=0;state.failureCount=failed;}
    details.open=state.open;
    details.append(summaryNode);const content=node('div','backtest-failure-content','展开后按页读取失败明细。');
    const paint=page=>{content.replaceChildren();for(const row of page.rows||[]){const item=node('div','backtest-failure-row');item.append(node('b','',row.symbol||'未知代码'),node('span','',row.error||'未记录失败原因'));content.append(item);}const bar=node('div','backtest-failure-page');bar.append(button('上一页',()=>load(Math.max(0,state.offset-20))));bar.append(node('span','caption',`${integer(page.total?state.offset+1:0)}–${integer(Math.min(page.total,state.offset+(page.rows||[]).length))} / ${integer(page.total)}`));bar.append(button('下一页',()=>load(state.offset+20)));bar.children[0].disabled=state.offset===0;bar.children[2].disabled=state.offset+(page.rows||[]).length>=page.total;content.append(bar);};
    const load=async(next=0)=>{if(state.loading)return;state.loading=true;state.open=true;state.offset=next;backtestFailureState.set(run.id,state);content.replaceChildren(node('p','caption','读取失败明细…'));try{const page=await api(`/api/backtests/errors?id=${encodeURIComponent(run.id)}&offset=${state.offset}&limit=20`);state.page=page;paint(page);}catch(error){content.replaceChildren(node('p','backtest-warning',`失败明细读取失败：${error.message}`));}finally{state.loading=false;}};
    details.addEventListener('toggle',()=>{state.open=details.open;backtestFailureState.set(run.id,state);if(details.open){if(state.page)paint(state.page);else load(state.offset||0);}});details.append(content);box.append(details);
    if(details.open&&state.page)paint(state.page);else if(details.open)load(state.offset||0);
  }
  box.append(node('p','',`缓存K线 ${integer(summary.bars)} · 候选 ${integer(summary.candidates)} · 当时确认 ${integer(confirmations)} · 确认撤回 ${integer(summary.withdrawals)} · 边界失效 ${integer(summary.invalidations)} · 完整交易 ${integer(summary.completed_trades??metrics.completed_trades)} · 零交易股票 ${integer(summary.zero_trade_securities)}`));
  box.append(node('p','',`成功股票独立账户均值 ${summary.mean_independent_account_return==null?'—':fmt(summary.mean_independent_account_return*100)+'%'} · 最差回撤 ${summary.worst_account_drawdown==null?'—':fmt(summary.worst_account_drawdown*100)+'%'} · 费用 ${fmt(summary.total_fees??metrics.total_fees)}元`));
  box.append(node('p','caption',`本地结果：${run.output||'—'} · ${summary.processing_complete?'已处理完本次排入任务的股票':'任务处理未完成'} · ${successComplete?'全市场目标均成功':'全市场目标覆盖不完整'}`));
  if(summary.processing_complete&&!successComplete)box.append(node('p','backtest-warning','处理结束不等于成功覆盖全市场；当前结果不是完整全市场回测。'));
  if(run.state==='interrupted')box.append(button('从断点继续',async()=>{try{await api('/api/backtests/resume',{id:run.id});backtestLastSnapshot='';await refreshBacktests(true);}catch(error){toast(error.message);}}));
  if(run.state==='running')box.append(button('停止派发，保留进度',async()=>{try{await api('/api/backtests/stop',{id:run.id});backtestLastSnapshot='';await refreshBacktests(true);}catch(error){toast(error.message);}}));
  return box;
}
async function refreshBacktests(force=false){
  if(backtestPollInFlight)return;backtestPollInFlight=true;
  try{const data=await api('/api/backtests'),runs=data.runs||[],snapshot=JSON.stringify(runs);backtestPollingActive=runs.some(run=>['running','queued','starting','stopping'].includes(run.state));
    text('#backtest-status',runs.length?`最近刷新 ${new Date().toLocaleTimeString('zh-CN',{hour12:false})} · ${backtestPollingActive?'自动轮询进行中':'无运行中任务'}`:'');
    if(force||snapshot!==backtestLastSnapshot){const holder=$('#backtest-runs'),fragment=document.createDocumentFragment();for(const run of runs)fragment.append(renderBacktestRun(run));if(!runs.length)fragment.append(node('div','panel','尚未运行回测。'));holder.replaceChildren(fragment);backtestLastSnapshot=snapshot;}
  }catch(error){text('#backtest-status','回测状态获取失败：'+error.message);}finally{backtestPollInFlight=false;}
}
function backtestRequestBody(){const body={scope:'all',engine:'native',workers:Number($('#backtest-workers').value),cache_policy:$('#backtest-cache-policy').value};if($('#backtest-cache').value.trim())body.cache=$('#backtest-cache').value.trim();if($('#backtest-date').value)body.cutoff=$('#backtest-date').value+'T15:00:00+08:00';return body;}
function renderBacktestPreflight(value,policy=$('#backtest-cache-policy').value){const missing=value.missing_symbols||[];const complete=value.available===value.total;const target=$('#backtest-preflight');target.className='message'+(!complete?' warning':'');target.replaceChildren(node('b','',`可回测缓存 ${integer(value.available)} / ${integer(value.total)} 只`),node('span','',complete?' · 每只证券至少有一份可用来源K线':policy==='complete'?' · 当前策略要求全部目标证券有数据，启动将被阻止':' · 仅运行有足够K线的证券；其余单列未覆盖'));if(value.insufficient_history_count)target.append(node('p','',`其中 ${integer(value.insufficient_history_count)} 只少于 ${integer(value.minimum_closed_bars)} 根闭合K线`));if(missing.length)target.append(node('p','',`缺失/历史不足示例：${missing.slice(0,5).join('、')}${value.missing_count>5?' 等':''}`));if(value.invalid_sources_count)target.append(node('p','',`无效缓存来源 ${integer(value.invalid_sources_count)} 个`));}
async function preflightBacktest(){const params=new URLSearchParams();const cache=$('#backtest-cache').value.trim(),date=$('#backtest-date').value;if(cache)params.set('cache',cache);if(date)params.set('cutoff',date+'T15:00:00+08:00');return api('/api/backtests/coverage'+(params.size?'?'+params:''));}
$('#backtest-refresh').onclick=()=>refreshBacktests(true);$('#backtest-preflight-run').onclick=async()=>{const button=$('#backtest-preflight-run');button.disabled=true;$('#backtest-preflight').replaceChildren(node('span','','正在读取本地缓存清单，请稍候；页面可继续操作。'));try{const coverage=await preflightBacktest();renderBacktestPreflight(coverage);}catch(error){$('#backtest-preflight').replaceChildren(node('span','backtest-warning','缓存核对失败：'+error.message));}finally{button.disabled=false;}};$('#backtest-start').onclick=async()=>{const start=$('#backtest-start');if(start.disabled)return;start.disabled=true;text('#backtest-status','正在检查全市场历史缓存覆盖…');$('#backtest-preflight').replaceChildren();try{const coverage=await preflightBacktest(),policy=$('#backtest-cache-policy').value;renderBacktestPreflight(coverage,policy);if(policy==='complete'&&coverage.available!==coverage.total){text('#backtest-status','全量缓存未齐，未启动。补齐缓存，或明确选择“运行有数据的股票并报告缺失”。');return;}const result=await api('/api/backtests/start',backtestRequestBody());text('#backtest-status',`回测已启动 · 入队 ${integer(result.total)} / 全市场 ${integer(result.requested_total??result.total)} 只 · 缓存已冻结`);backtestLastSnapshot='';await refreshBacktests(true);}catch(error){text('#backtest-status','回测未启动：'+error.message);}finally{start.disabled=false;}};
setInterval(()=>{if(S.view==='signals'||window.Notification&&Notification.permission==='granted')refreshMonitor();if(S.view==='backtests'&&backtestPollingActive)refreshBacktests();},4000);

$('#monitor-download').onclick=async()=>{try{await api('/api/jobs',{scope:'all',mode:'day',workers:6,refresh:true,volume_tolerance:1});toast('全市场完整日线获取与结构任务已加入队列');view('tasks');refreshOverview();}catch(e){toast(e.message);}};

function signalObjects(){return (S.data?.chart?.panels||[]).flatMap(p=>p.signal_chart?.objects||[]);}
function signalInCurrentFilter(point){return ($('#show-review-objects').checked||point.state!=='needs_review')&&(S.rank==='all'||point.rank===Number(S.rank))&&(S.signalSide==='all'||point.side===S.signalSide)&&SignalChart.matchesPeriod(point,S.period)&&($('#signal-show-invalid').checked||!['invalidated','withdrawn'].includes(point.state));}
function renderSignalPicker(){const picker=$('#signal-picker');if(!picker)return;const selected=S.signalSelected;picker.replaceChildren();const placeholder=node('option','','选择信号查看依据');placeholder.value='';picker.append(placeholder);const items=signalObjects().filter(signalInCurrentFilter).sort(SignalChart.compareNewest);for(const p of items){const option=node('option','',`${PERIOD[p.period]} L${p.rank} · ${p.label} · ${p.state_label} · ${p.anchor_time.slice(0,10)} / ${fmt(p.price)}`);option.value=p.id;picker.append(option);}picker.value=items.some(p=>p.id===selected)?selected:'';if(!picker.value){S.signalSelected='';$('#signal-proof-content').replaceChildren();}}
function renderSignalRail(){
  const holder=$('#terminal-signal-list'),count=$('#terminal-signal-count'),scope=$('#terminal-signal-scope');if(!holder||!count)return;
  const items=signalObjects().filter(signalInCurrentFilter).sort(SignalChart.compareNewest);
  count.textContent=integer(items.length)+'点';
  scope.textContent=`${S.period==='all'?'所有周期':PERIOD[S.period]||S.period} · ${S.rank==='all'?'全部级别':`L${S.rank}`} · ${S.signalSide==='all'?'买卖点':S.signalSide==='buy'?'买点':'卖点'}`;
  holder.replaceChildren();
  if(!items.length){holder.append(node('div','terminal-signal-empty','当前筛选没有结构点。可切换方向、周期或复核状态。'));return;}
  for(const point of items){
    const row=node('button','terminal-signal-row');row.type='button';row.dataset.signalId=point.id;
    const head=node('div','terminal-signal-row-head');
    head.append(node('strong',point.state==='needs_review'?'review-label':point.side==='buy'?'buy-label':'sell-label',`${PERIOD[point.period]||point.period} · L${point.rank} ${point.label}`),node('span','',fmt(point.price)));
    const meta=node('div','terminal-signal-row-meta');meta.append(node('span','',`${point.anchor_time.slice(0,16).replace('T',' ')} · ${point.state_label}`),node('span','',`依据 ${point.available_time.slice(0,16).replace('T',' ')}`));
    row.append(head,meta);
    row.onclick=()=>{
      S.signalSelected=point.id;S.layers.signals=true;
      const layerToggle=document.querySelector('[data-layer="signals"]');if(layerToggle)layerToggle.checked=true;
      if(S.period!=='all'&&S.period!==point.period){S.period=point.period;renderCharts();}
      selectChartSignal(point);
      const chart=S.charts.find(item=>item.p.period===point.period);
      if(chart){chart.chart.timeScale().setVisibleLogicalRange(SignalChart.markerRange(point,chart.p.bars.length));chart.draw();}
    };
    holder.append(row);
  }
}
function selectChartSignal(point){S.signalSelected=point.id;$('#signal-picker').value=point.id;const holder=$('#signal-proof-content');holder.replaceChildren();const title=node('p','',`${PERIOD[point.period]||point.period} · ${point.native_engine?(point.rank===1?'笔级':'线段级'):'L'+point.rank} · ${point.label} · ${point.state_label}`);holder.append(title);if(point.native_engine)holder.append(node('p','',`固定引擎类型${point.native_type}；1p是盘整一类，2s是二类延伸，3a/3b按上游不同三类定义分开保留。`));const grid=node('dl','signal-proof-grid');for(const[label,value]of [['价格端点',point.anchor_time+' / '+fmt(point.price)],['实际观测到位',point.available_time+' / 比端点晚'+point.delay_bars+'根'],['首次出现',point.first_seen_time||'旧快照未保留首次观测'],['本级结构确定',point.local_completed_time||'尚无已完成的本级反向结构凭据'],['多周期触发',point.confirmed_time||'尚无有效触发凭据'],['失效边界',point.invalidation_operator+' '+fmt(point.invalidation)],['关联中枢',point.center?point.center.id+' / '+fmt(point.center.zd)+'—'+fmt(point.center.zg):'无已保存中枢对象'],['定义口径',point.native_engine?point.native_engine+' / 类型 '+point.native_type:point.definition_mode]]){const cell=node('div');cell.append(node('dt','',label),node('dd','',value));grid.append(cell);}holder.append(grid);const references=node('div','signal-proof-references');for(const r of point.references)references.append(node('span','',r.label+' K'+r.start+'—'+r.end));holder.append(references);if(point.comparison){const c=point.comparison;holder.append(node('p','',`同级力度比较：A面积 ${fmt(c.a.macd_area,4)}，C面积 ${fmt(c.c.macd_area,4)}；未通过条件 ${(c.blocked_gates||[]).join('、')||'无'}。`));}if(point.first_context)holder.append(node('p','',`二类点前置：${point.first_context.label} K${point.first_context.anchor} / ${fmt(point.first_context.price)}`));holder.append(node('p','',point.state==='triggered'?'已关联下级确认与细级触发凭据；标记仍属于模型结构研究。':(point.state==='structure_complete'?'固定引擎本级结构已确定；未建立跨周期触发，不等于下单信号。':'当前标记为结构候选/历史状态；价格端点早于依据，不应按端点时间倒用确认结果。')));if(point.anchor_correction&&(point.anchor_correction.anchor!==point.anchor||point.anchor_correction.price!==point.price))holder.append(node('p','',`已纠正旧标记：原K${point.anchor_correction.anchor} / ${fmt(point.anchor_correction.price)}，现指向原始区间真实${point.side==='buy'?'最低':'最高'}价。`));if(point.invalidated_time)holder.append(node('p','',`失效依据：${point.invalidated_time}，实际${point.side==='buy'?'最低':'最高'}价 ${fmt(point.invalidated_price)} ${point.invalidation_operator} 边界 ${fmt(point.invalidation)}。历史形成不等于永远有效。`));if(point.rule_audit){const reasons={'independent_geometry_review_required':'基础结构有极值解释分歧或中枢关系不能唯一映射，暂停确认','native_stroke_or_segment_is_provisional':'该笔/线段尚未确定','completed_child_types':'当前是线段基础边界，缺少严格次级别走势类型','terminal_is_completed_type':'末端尚未证明为完整次级走势','opposite_child_boundary_confirmed':'反向组件尚未完成','signal_not_invalidated_at_observation':'后续K线已越过失效边界','conservative_extreme_held':'首次回试未守住前极值','first_source_context_passed':'前置一类结构条件未全部通过','terminal_sublevel_context_present':'末端内部缺少下级中枢组织'};const missing=point.rule_audit.missing||[];holder.append(node('p','',point.rule_audit.passed?'本级结构条款已通过；仍需核对跨周期确认与触发。':'严格确认未通过的原因：'+missing.map(k=>reasons[k]||k).join('；')));}
const detail=node('details');detail.append(node('summary','','查看机器证据'));detail.append(node('pre','signal-proof-raw',JSON.stringify(point,null,2)));holder.append(detail);S.charts.forEach(c=>c.draw());}
$('#signal-picker').onchange=()=>{const point=signalObjects().find(p=>p.id===$('#signal-picker').value);if(point)selectChartSignal(point);else{S.signalSelected='';$('#signal-proof-content').replaceChildren();S.charts.forEach(c=>c.draw());}};
$('#signal-show-invalid').onchange=renderCharts;$('#signal-show-time').onchange=()=>S.charts.forEach(c=>c.draw());
$('#signal-focus').onclick=()=>{const p=signalObjects().find(p=>p.id===S.signalSelected);if(!p){toast('先选择一项买卖标记');return;}const chart=S.charts.find(c=>c.p.period===p.period);if(!chart)return;const starts=[p.anchor,...p.references.map(r=>r.start),...(p.center?[p.center.start]:[])];const ends=[p.anchor,p.available_at,p.confirmed_index??p.available_at,...p.references.map(r=>r.end)];chart.chart.timeScale().setVisibleLogicalRange({from:Math.min(...starts)-15,to:Math.max(...ends)+15});chart.draw();};

function prepareSignalDisplay(){
  const all=signalObjects();const display=SignalChart.presentation(all,{period:S.period,rank:S.rank,side:S.signalSide,showInvalid:$('#signal-show-invalid').checked,showReview:$('#show-review-objects').checked});
  const ranks=[...new Set(all.map(point=>point.rank))].sort((a,b)=>a-b),rankSelect=$('#structure-rank');
  if(S.rank!=='all'&&!ranks.includes(Number(S.rank)))S.rank='all';
  rankSelect.replaceChildren(new Option(`全部级别（${all.length}点）`,'all'));
  for(const rank of ranks){const count=all.filter(point=>point.rank===rank).length;const label=S.data?.chart?.display_engine?(rank===1?'笔级 L1':rank===2?'线段级 L2':`原生级别 L${rank}`):`L${rank}`;rankSelect.add(new Option(`${label}（${count}点）`,String(rank)));}
  rankSelect.value=String(S.rank);
  $$('#signal-side-filter button').forEach(button=>button.classList.toggle('active',button.dataset.side===S.signalSide));
  S.range='recent';S.signalSelected='';
  const source=S.data?.chart?.panels?.find(p=>p.period===display.latest?.period);if(display.latest&&source&&display.latest.anchor<source.bars.length-300){S.range='signals';S.signalSelected=display.latest.id;}
}
function updateSignalVisibility(){
  const target=$('#signal-visibility');if(!target||!S.data?.chart)return;
  const summary=SignalChart.presentation(signalObjects(),{period:S.period,rank:S.rank,side:S.signalSide,showInvalid:$('#signal-show-invalid').checked,showReview:$('#show-review-objects').checked});
  const visible=S.charts.reduce((n,c)=>n+(c.p.signal_render_stats?.visible_markers||0),0);
  const rankLabel=S.rank==='all'?'全部级别':S.data?.chart?.display_engine?(Number(S.rank)===1?'笔级 L1':'线段级 L2'):'L'+S.rank;
  const sideLabel=S.signalSide==='all'?'买卖点':S.signalSide==='buy'?'买点':'卖点';
  let message=`${rankLabel} · ${sideLabel} ${summary.buys}买/${summary.sells}卖 · 有效 ${summary.active} · 历史 ${summary.historical} · 复核 ${summary.review} · 图中 ${visible}`;
  if(!summary.total){message=summary.ranks.length?`当前筛选没有${sideLabel}；存在买卖点的级别：${summary.ranks.map(n=>'L'+n).join('、')}。`:'当前周期尚无已识别结构点；请选择其他周期或检查历史覆盖。';}
  else if(!$('#signal-show-invalid').checked&&!summary.items.length)message+=' 当前标记全部是历史失效点，勾选“显示历史失效点”即可复盘。';
  else if(!S.layers.signals)message+=' “买卖标记”图层已关闭。';
  else if(!visible)message+=' 标记位于当前视野之外，点击“最近买卖点”定位。';
  else if(!summary.active)message+=' 当前显示的是历史复盘点，灰叉表示已失效。';
  target.textContent=message;target.classList.toggle('empty',!summary.total);
}
$('#signal-latest').onclick=()=>{
  let display=SignalChart.presentation(signalObjects(),{period:S.period,rank:S.rank,side:S.signalSide,showInvalid:$('#signal-show-invalid').checked,showReview:$('#show-review-objects').checked});
  if(!display.items.length&&display.total&&!$('#signal-show-invalid').checked){$('#signal-show-invalid').checked=true;renderCharts();display=SignalChart.presentation(signalObjects(),{period:S.period,rank:S.rank,side:S.signalSide,showInvalid:true,showReview:$('#show-review-objects').checked});}
  if(!display.latest){toast('当前周期、级别和方向没有可见结构点');return;}
  S.layers.signals=true;document.querySelector('[data-layer="signals"]').checked=true;selectChartSignal(display.latest);
  const chart=S.charts.find(c=>c.p.period===display.latest.period);if(chart){chart.chart.timeScale().setVisibleLogicalRange(SignalChart.markerRange(display.latest,chart.p.bars.length));chart.draw();}
};

function currentKlinePanel(){const panels=S.data?.chart?.panels||[];return panels.find(p=>p.period===S.period)||panels.find(p=>p.period==='day')||panels[0];}
function renderKlineSummary(){const p=currentKlinePanel(),target=$('#kline-integrity');if(!p){target.textContent='尚未加载原始K线。';return;}const a=p.kline_audit||{};const corrections=p.anchor_corrections?.length||0;const review=p.geometry_review;const reviewText=review?` · 独立几何复核：${review.stroke_issues}笔/${review.segment_issues}段待复核`:'';target.textContent=`${PERIOD[p.period]||p.period} · 原始K线 ${integer(p.bars.length)} / 声明 ${integer(p.input_bars)} 根 · ${p.bars[0]?.date_cn||'—'} 至 ${p.bars.at(-1)?.date_cn||'—'} · ${S.data.chart.adjustment||'不复权'} · ${a.state==='invalid'?'数据校验失败：'+(a.errors||[]).join('；'):'OHLC与时间顺序已检查'}${corrections?' · 已纠正旧买卖标记 '+corrections+' 项':''}${reviewText}。全部原始K线已加载；视窗默认近期300根以保证可辨。`;}
$('#kline-audit').onclick=async()=>{const p=currentKlinePanel();if(!p)return;try{const q=new URLSearchParams({audit_period:p.period});if(S.data.summary.live)q.set('live','1');if(S.job)q.set('job',S.job);const a=await api('/api/kline-audit/'+S.selected+'?'+q);$('#kline-integrity').textContent=a.source_state==='matched'?`${PERIOD[p.period]}完整原始K线逐条核对通过：${integer(a.compared_rows)}根，开/高/低/收/量及时间全部匹配保存的${a.source_kind==='provider_raw_response'?'原始行情响应':'来源CSV'}。输入SHA256 ${a.source_csv_sha256}。可得历史不自动等于上市以来无缺失。`:`来源核对：${a.source_state||a.state}。${(a.errors||[]).join('；')} 保存的来源文件不可用时，不能声称已完成源头比对。`;}catch(e){toast(e.message);}};
$('#kline-csv').onclick=async()=>{const p=currentKlinePanel();if(!p)return;const q=new URLSearchParams({period:p.period});if(S.data.summary.live)q.set('live','1');if(S.job)q.set('job',S.job);try{const r=await fetch('/api/kline-csv/'+S.selected+'?'+q);if(!r.ok)throw Error((await r.json()).error||'K线导出失败');download(await r.blob(),S.selected+'_'+p.period+'_完整原始K线.csv');toast('已导出完整原始K线');}catch(e){toast(e.message);}};
$('#kline-table-open').onclick=()=>{const p=currentKlinePanel();if(!p)return;$('#kline-table-title').textContent=`${PERIOD[p.period]} · 全部 ${integer(p.bars.length)} 根原始K线（表格列出最近300根，CSV包含全部）`;const body=$('#kline-table-body');body.replaceChildren();for(const b of p.bars.slice(-300).reverse()){const tr=node('tr');for(const v of [b.source_index,b.date_cn,fmt(b.open,p.kline_audit?.price_precision||2),fmt(b.high,p.kline_audit?.price_precision||2),fmt(b.low,p.kline_audit?.price_precision||2),fmt(b.close,p.kline_audit?.price_precision||2),integer(b.volume),b.is_closed===false?'未闭合':'已闭合'])tr.append(node('td','',v));body.append(tr);}$('#kline-table-dialog').showModal();};$('#kline-table-close').onclick=()=>$('#kline-table-dialog').close();

$('#chart-focus-mode').onclick=()=>{document.body.classList.toggle('chart-focus-mode');$('#chart-focus-mode').textContent=document.body.classList.contains('chart-focus-mode')?'退出看图专注':'看图专注';setTimeout(()=>S.charts.forEach(c=>c.resize()),60);};

$('#show-review-objects').onchange=renderCharts;
