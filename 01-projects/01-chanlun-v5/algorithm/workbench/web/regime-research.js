(function(global){
  'use strict';
  const labels={warmup:'历史不足',neutral:'方向未明',downtrend:'下跌趋势',bottom_candidate:'底部观察',basing:'筑底观察',breakout_confirmation:'向上突破确认',uptrend:'上升趋势',top_candidate:'顶部观察',topping:'顶部整理',breakdown:'向下破位',bottom_invalidated:'底部条件失效',top_invalidated:'顶部条件失效',bottom_expired:'底部观察过期',top_expired:'顶部观察过期'};
  const number=(value,places=2)=>value==null||!Number.isFinite(Number(value))?'—':Number(value).toFixed(places);
  function node(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n;}
  function render(holder,research,symbol,enableFlow=true){
    if(!holder)return;holder.replaceChildren();
    const head=node('div','regime-head');head.append(node('strong','','走势研究 · 日线'),node('span','regime-version',research?.version||'等待数据'));holder.append(head);
    if(!research?.latest){holder.append(node('p','','尚无日线研究结果；先获取真实已收盘K线。'));return;}
    const state=research.latest,f=state.features||{},cost=f.cost_distribution_proxy||{},runtime=research.runtime||{};
    const status=node('div','regime-state');status.append(node('b',state.state==='downtrend'||state.state==='breakdown'?'down':'',labels[state.state]||state.state),node('span','',`依据 ${state.closed_at?.slice(0,16).replace('T',' ')||research.as_of||'—'}`));holder.append(status);
    const grid=node('dl','regime-facts');
    const rows=[['MA20 / MA60',number(f.ma20)+' / '+number(f.ma60)],['距阶段高点',number((f.drawdown??0)*100)+'%'],['成交量 / 均量',number(f.volume_ratio)+' 倍'],['价量成本中位代理',number(cost.median)],['价量分布80%区间',number(cost.p10)+' — '+number(cost.p90)],['失效边界',state.invalidation?state.invalidation.operator+' '+number(state.invalidation.price):'当前无活动候选边界']];
    for(const [label,value]of rows){const box=node('div');box.append(node('dt','',label),node('dd','',value));grid.append(box);}holder.append(grid);
    const breadth=research.market_observation;
    if(breadth)holder.append(node('p','regime-note',`指数成分上涨 ${breadth.up_count} / 下跌 ${breadth.down_count} · 上涨占比 ${number(breadth.advance_share*100)}%（不等于全市场情绪）`));
    const actual=f.actual_fund_flow;
    holder.append(node('p','regime-note',`资金流时点证据：${actual?.state==='available'?number(actual.net_flow)+' 元':'未进入当前历史信号'} · 筹码为价格成交量分布代理，缺少真实持仓成本。`));
    holder.append(node('p','regime-note',`驻留状态 ${runtime.session_reused?'复用':'初始化'} · 本次推进 ${runtime.new_closed_bars??0} 根 · 已收盘 ${runtime.closed_bars??0} 根 · 规则 ${research.config_sha256?.slice(0,12)||'—'}`));
    if(enableFlow&&/^(sh|sz|bj)\d{6}$/.test(symbol)&&!research.market_observation){
      const button=node('button','button small','获取独立资金流证据');button.type='button';const output=node('div','regime-flow');holder.append(button,output);
      button.onclick=async()=>{button.disabled=true;output.textContent='正在获取供应商资金流…';try{const response=await fetch('/api/research-context/'+encodeURIComponent(symbol));const data=await response.json();if(!response.ok)throw Error(data.error||'查询失败');if(data.state!=='ready'){output.textContent='资金流不可用：'+(data.reason||'来源没有数据');return;}const latest=data.latest;output.textContent=`${latest.date} 主力净流估计 ${number(latest.main_net_flow)} 元 · ${data.rows_count} 日 · 获取 ${data.received_at}；未验证历史发布时间，禁止倒灌回测。`;}catch(error){output.textContent=error.message;}finally{button.disabled=false;}};
    }
    holder.append(node('p','regime-note','观察条件只使用当时已收盘数据。突破确认发生在突破之后；没有“提前确定底部”或确定收益的含义。'));
  }
  function draw({group,research,x,y,width,height}){
    if(!research)return;
    const ns='http://www.w3.org/2000/svg',items=[];
    for(const event of research.events||[]){
      const kind=event.event||event.state;
      if(!['bottom_candidate','breakout_confirmation','breakdown','downtrend','top_candidate'].includes(kind))continue;
      const px=x(event.observed_index),py=y(event.price);if(![px,py].every(Number.isFinite)||px<0||px>width)continue;
      items.push({id:event.id,point:event,x:px,y:py,label:labels[kind]||kind,side:['breakdown','downtrend','top_candidate'].includes(kind)?'sell':'buy'});
    }
    const positions=global.SignalChart.layoutMarkers(items,width,height);
    for(const item of positions){
      const event=item.point,kind=event.event||event.state,px=item.x,py=item.y;
      const color=item.side==='sell'?'#168e7c':'#b77924';
      const g=document.createElementNS(ns,'g');g.setAttribute('class','regime-event');g.setAttribute('data-kind',kind);
      const circle=document.createElementNS(ns,'circle');circle.setAttribute('cx',px);circle.setAttribute('cy',py);circle.setAttribute('r','4');circle.setAttribute('fill','#fff');circle.setAttribute('stroke',color);
      const title=document.createElementNS(ns,'title');title.textContent=`${labels[kind]||kind} · ${event.observed_at} · 研究规则，非下单指令`;g.append(circle,title);
      if(item.box){const text=document.createElementNS(ns,'text');text.setAttribute('x',item.box.x+4);text.setAttribute('y',item.box.y+13);text.setAttribute('fill',color);text.setAttribute('font-size','10');text.setAttribute('stroke','#fff');text.setAttribute('stroke-width','3');text.setAttribute('paint-order','stroke');text.textContent=item.label;g.append(text);}
      group.append(g);
    }
    return {markers:positions.length,labels:positions.filter(item=>item.box).length};
  }
  global.RegimeResearch={render,draw,labels};
})(window);

