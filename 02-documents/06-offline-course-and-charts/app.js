/* Offline lesson player and causal Python-snapshot chart viewer. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const lessons = window.CHAN_LESSONS || [];
  const data = window.CHAN_DATA;
  const media = window.CHAN_MEDIA || { chapters: [] };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = n => Number.isFinite(+n) ? (+n).toFixed(2) : '—';
  const mmss = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  const col = { ink:'#102c2b', text:'#eaf5ef', mute:'#91aea3', grid:'#284540', teal:'#65d2ba', coral:'#ed9c77', gold:'#e1c07c', rise:'#d56860', fall:'#439b80' };
  let chapter = 0, lessonPlaying = false, lessonElapsed = 0, lastFrame = 0;
  let count = 130, chartPlaying = false, chartLast = 0, activeView = 'lesson';
  let selected = null, visiblePicks = [], lessonProgress = 0, chartNarrator=null;
  const layers = {candles:true,fractals:true,strokes:true,segments:true,centers:true,types:false,signals:true};
  const audio = $('narration-audio');
  const stateNames = { untradable_unclear:'结构尚未清楚',center_oscillation:'中枢内观察',uptrend_proxy:'上行趋势代理',downtrend_proxy:'下行趋势代理',higher_level_overlap:'更高层级重叠候选' };
  const signalNames = {first_buy_candidate:'一买候选',second_buy_candidate:'二买候选',third_buy_candidate:'三买候选',first_sell_candidate:'一卖候选',second_sell_candidate:'二卖候选',third_sell_candidate:'三卖候选'};
  const timeName = index => index == null ? '尚未确认' : `第 ${index + 1} 根`;
  const line = (points, color=col.teal, width=4, extra='') => `<polyline points="${points.map(p=>p.join(',')).join(' ')}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" ${extra}/>`;
  const text = (x,y,label,size=16,color=col.text,extra='')=>`<text x="${x}" y="${y}" font-size="${size}" fill="${color}" ${extra}>${esc(label)}</text>`;
  const dot = (x,y,color=col.teal,r=5)=>`<circle cx="${x}" cy="${y}" r="${r}" fill="${color}"/>`;
  const rect = (x,y,w,h,fill,extra='')=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" ${extra}/>`;
  const partial = (points, progress) => {
    const pos = Math.max(0.08,Math.min(1,progress))*(points.length-1), whole=Math.floor(pos);
    const result=points.slice(0,whole+1), t=pos-whole;
    if(whole<points.length-1) result.push([points[whole][0]+(points[whole+1][0]-points[whole][0])*t, points[whole][1]+(points[whole+1][1]-points[whole][1])*t]);
    return result;
  };
  function candle(x, high, low, open, close, width=18, color=col.teal) {
    return `<line x1="${x}" x2="${x}" y1="${high}" y2="${low}" stroke="${color}" stroke-width="2"/>${rect(x-width/2,Math.min(open,close),width,Math.max(3,Math.abs(open-close)),color)}`;
  }
  function lessonDiagram(kind, progress) {
    const q=.38+.62*Math.min(1,progress*1.5), wave=[[50,210],[145,90],[215,155],[315,60],[385,145],[475,45],[545,120],[655,45],[750,100]];
    let v='';
    for(let i=1;i<5;i++)v+=`<line x1="35" y1="${i*55}" x2="785" y2="${i*55}" stroke="${col.grid}" stroke-width="1"/>`;
    if(kind==='map'||kind==='algorithm'){
      v+=line(partial(wave,q),col.teal,4);
      const names=kind==='map'?['K线','分型','笔','线段','中枢','买卖点']:['前缀数据','结构计算','确认时间','失效记录'];
      names.forEach((s,i)=>{const x=45+i*(730/names.length);v+=rect(x,245,730/names.length-8,34,i<=Math.floor(q*names.length)?col.grid:col.ink,'rx="3"');v+=text(x+12,267,s,14,i<=Math.floor(q*names.length)?col.teal:col.mute);});
    }else if(kind==='inclusion'){
      v+=candle(150,55,215,155,95,25)+candle(220,85,185,140,110,25,col.coral);
      v+=text(135,245,'[5, 10]',16)+text(205,245,'[6, 9]',16,col.coral);
      v+=text(350,137,'→',55,col.mute);v+=candle(520,55,185,160,100,30)+text(475,245,'向上：[6, 10]',18,col.teal);
      v+=text(420,282,'向下则保留 [5, 9]；方向不能倒推',15,col.mute);
    }else if(kind==='fractal'){
      v+=candle(200,110,220,190,140,30,col.teal)+candle(390,40,140,110,65,30,col.coral)+candle(580,95,205,130,175,30,col.teal);
      v+=text(355,25,'顶分型',22,col.coral)+text(147,260,'左侧',17,col.mute)+text(337,185,'高点和低点都更高',17,col.coral)+text(530,250,'等右侧完成',18,col.teal);
      v+=line([[200,65],[390,65],[580,65]],col.mute,1,'stroke-dasharray="4 5"');
    }else if(kind==='stroke'){
      const ps=[[55,220],[175,65],[295,195],[420,45],[555,170],[750,75]];
      v+=line(partial(ps.slice(0,5),q),col.teal,4);v+=line(ps.slice(4),col.teal,3,'stroke-dasharray="8 7"');
      ps.forEach((p,i)=>{v+=dot(...p,i===5?col.mute:col.coral);v+=text(p[0]-12,p[1]+(i%2? -15:28),i%2?'顶':'底',15,i===5?col.mute:col.text);});
      v+=text(530,265,'虚线：末笔还在延伸',16,col.mute);
    }else if(kind==='segment'){
      v+=rect(100,120,570,60,col.teal,'opacity=".10"');v+=line(partial(wave,q),col.teal,3);
      v+=line([[50,210],[475,45]],col.gold,5);v+=line([[475,45],[750,100]],col.gold,3,'stroke-dasharray="7 6"');
      v+=text(70,275,'细线是笔',17,col.teal)+text(290,275,'粗线是线段示意',17,col.gold)+text(570,275,'破坏 ≠ 终结',17,col.coral);
    }else if(kind==='center'||kind==='third'){
      const ps=kind==='center'?[[65,80],[180,230],[310,100],[440,210],[590,75],[735,180]]:[[55,110],[140,235],[255,130],[365,210],[520,45],[650,105],[760,30]];
      const top=kind==='center'?100:130, bottom=210;
      v+=rect(130,top,560,bottom-top,col.teal,'opacity=".13"');v+=`<line x1="80" x2="770" y1="${top}" y2="${top}" stroke="${col.teal}" stroke-dasharray="6 5"/><line x1="80" x2="770" y1="${bottom}" y2="${bottom}" stroke="${col.teal}" stroke-dasharray="6 5"/>`;
      v+=line(partial(ps,q),col.text,4)+text(700,top-10,'ZG = 7',15,col.teal)+text(700,bottom+25,'ZD = 3',15,col.teal);
      if(kind==='center')v+=text(220,160,'共同重叠区 [3, 7]',24,col.teal);
      else v+=dot(650,105,col.coral,7)+text(592,78,'回拉到 8',17,col.coral)+text(465,28,'离开到 12',16,col.mute)+text(510,269,'触到 7 → 按本片口径重入',15,col.mute);
    }else if(kind==='trend'){
      [[85,150],[355,100],[620,45]].forEach(([x,y],i)=>{v+=rect(x,y,135,75,col.teal,'opacity=".13"');v+=text(x+20,y+46,`中枢 ${i+1}`,18,col.teal);});
      v+=line(partial([[35,230],[90,140],[180,190],[265,120],[355,160],[435,75],[525,130],[625,40],[705,90],[780,25]],q),col.text,3);
      v+=text(75,275,'同级别 + 位置分离；重叠时检查更大整理',17,col.mute);
    }else if(kind==='divergence'){
      v+=line(partial([[55,175],[230,70],[360,150],[565,35],[735,90]],q),col.text,4);
      v+=text(175,43,'前段',17,col.mute)+text(550,22,'价格新高',17,col.coral);
      for(let i=0;i<18;i++){const x=90+i*36;const amp=i<7?50*Math.sin(i/7*Math.PI):i>10?25*Math.sin((i-10)/8*Math.PI):5;v+=rect(x,240-amp,15,Math.max(3,amp),col.teal,'opacity=".8"');}
      v+=text(535,274,'柱面积减弱：只是线索',16,col.teal);
    }else if(kind==='first-second'){
      const ps=[[45,40],[180,210],[300,145],[420,245],[560,85],[650,185],[775,50]];
      v+=line(partial(ps,q),col.text,4)+dot(420,245,col.coral,7)+text(355,276,'10：一买候选',17,col.coral)+dot(650,185,col.teal,7)+text(605,223,'11：首次回抽',16,col.teal)+text(537,65,'反弹到16',16,col.mute);
    }else if(kind==='levels'){
      ['大级别：背景','操作级：结构','次级别：确认','更小级：时机'].forEach((s,i)=>{let x=45+i*185,y=48+i*42;v+=rect(x,y,175,65,i===Math.floor(q*3)?col.grid:col.ink,'stroke="'+col.teal+'" stroke-width="1"');v+=text(x+15,y+38,s,16,col.text);if(i<3)v+=text(x+167,y+78,'↘',25,col.teal);});
      v+=text(50,283,'时间倍数 ≠ 结构嵌套证明',18,col.coral);
    }else if(kind==='time'){
      v+=line(partial([[40,70],[225,220],[385,135],[560,55],[755,105]],q),col.teal,4);
      v+=dot(225,220,col.coral,7)+text(175,258,'第100根：低点发生',17,col.coral)+dot(560,55,col.gold,7)+text(490,32,'第108根：才确认',17,col.gold);
      v+=`<path d="M240 230 Q410 295 555 235" stroke="${col.mute}" stroke-width="2" fill="none" stroke-dasharray="6 6"/>`;
    }
    return `<svg class="lesson-diagram" viewBox="0 0 820 300" role="img" aria-label="${esc(lessons[chapter]?.summary)}">${v}</svg>`;
  }
  function chapterMedia(i){return media.chapters.find(c=>c.id===lessons[i]?.id)||media.chapters[i];}
  function renderChapters(){
    $('chapter-list').innerHTML=lessons.map((l,i)=>`<button class="chapter-item ${i===chapter?'active':''}" data-chapter="${i}" aria-current="${i===chapter?'step':'false'}"><span class="chapter-num">${String(i+1).padStart(2,'0')}</span><span class="chapter-name">${esc(l.title.split('：')[0])}</span><span class="chapter-clock">${chapterMedia(i)?mmss(chapterMedia(i).duration):''}</span></button>`).join('');
  }
  function renderLesson(progress=0){
    const l=lessons[chapter];if(!l)return;
    $('lesson-stage').innerHTML=`<div class="stage-kicker">${esc(l.kicker)}</div><h2>${esc(l.title)}</h2><p class="stage-summary">${esc(l.summary)}</p>${lessonDiagram(l.kind,progress)}<span class="stage-example">教学示意 · 非真实行情</span>`;
    $('narration').textContent=l.narration;
    $('lesson-position').textContent=`${String(chapter+1).padStart(2,'0')} / ${lessons.length}`;
    $('lesson-progress').style.width=`${progress*100}%`;
    $('lesson-prev').disabled=chapter===0;
    $('lesson-next').disabled=chapter===lessons.length-1;
    $('lesson-play').textContent=lessonPlaying?'暂停讲解':lessonElapsed>0?'继续这一章':'开始连续讲解';
    const m=chapterMedia(chapter);$('lesson-duration').textContent=m?`${mmss(lessonElapsed)} / ${mmss(m.duration)}`:'';
  }
  function setChapter(i, continuePlaying=false){
    if(i<0||i>=lessons.length)return;
    audio.pause();chapter=i;lessonElapsed=0;lessonProgress=0;lessonPlaying=false;
    const m=chapterMedia(i);if(m)audio.src=m.audio;
    renderLesson();renderChapters();if(continuePlaying)playLesson();
  }
  async function playLesson(){
    if(lessonPlaying){lessonPlaying=false;audio.pause();renderLesson(lessonProgress);return;}
    lessonPlaying=true;
    if($('voice').checked&&chapterMedia(chapter)){
      try{audio.muted=false;await audio.play();}catch(error){lessonPlaying=false;$('narration').textContent='音频未能播放，请打开完整 MP4；也可以取消中文配音，按字幕继续。'+lessons[chapter].narration;}
    }
    renderLesson(lessonProgress);
  }
  function nextLesson(){if(chapter<lessons.length-1)setChapter(chapter+1,true);else{lessonPlaying=false;lessonElapsed=chapterMedia(chapter)?.duration||lessonElapsed;lessonProgress=1;audio.pause();renderLesson(1);$('lesson-play').textContent='讲解完成，进入算法回放 →';}}
  function switchView(view){
    activeView=view;$('lesson-view').hidden=view!=='lesson';$('chart-view').hidden=view!=='chart';$('full-view').hidden=view!=='full';$('period-view').hidden=view!=='period';
    for(const name of ['lesson','chart','period','full']){$('tab-'+name).classList.toggle('active',name===view);$('tab-'+name).setAttribute('aria-selected',String(name===view));}
    if(view==='full'&&!$('full-frame').src)$('full-frame').src=$('full-frame').dataset.src;
    if(view==='period'&&!$('period-frame').src)$('period-frame').src=$('period-frame').dataset.src;
    window.ChanChartNarrator?.stopAll();
    for(const id of ['full-frame','period-frame'])$(id).contentWindow?.postMessage({type:'chan-stop-narration'},'*');
    if(view!=='lesson'){lessonPlaying=false;audio.pause();}
    if(view==='chart'){lessonPlaying=false;audio.pause();renderChart();renderLesson(lessonProgress);}else{chartPlaying=false;renderLesson(lessonProgress);}
    history.replaceState(null,'','#'+view);
  }
  function pick(kind,item){const i=visiblePicks.length;visiblePicks.push({kind,item});return `class="pick" data-pick="${i}" data-node-id="${esc(item.id??item.signal_id??'')}" tabindex="0" role="button" aria-label="查看${kind}证据"`;}
  function snapshot(){return data.snapshots[count-1];}
  function narrationContext(){return {period:data.meta.period||data.meta.trade_level||data.meta.level||'5m',rank:+$('rank-select').value||null,as_of:count-1,bars:data.bars.slice(0,count),report:snapshot(),synthetic:data.meta.synthetic,source_group:'本页独立5分钟教学样例'};}
  function highlightNarration(id){for(const el of $('chart-host').querySelectorAll('[data-node-id]'))el.classList.toggle('cn-highlight',!!id&&el.dataset.nodeId===String(id));}
  function setCount(n){count=Math.max(5,Math.min(data.bars.length,Number(n)));$('time-slider').value=count;selected=null;renderChart();}
  function renderChart(){
    if(!data)return;
    const s=snapshot(), W=window.innerWidth<780?700:1100,H=500,left=46,right=60,top=32,priceH=302,macdY=392,macdH=75;
    const windowSize=+$('window-size').value,start=windowSize?Math.max(0,count-windowSize):0;
    const rank=+$('rank-select').value,centers=s.centers.filter(c=>!rank||c.rank===rank),types=(s.types||[]).filter(t=>!rank||t.rank===rank);
    const bs=data.bars.slice(start,count),hi=Math.max(...bs.map(b=>b.high)),lo=Math.min(...bs.map(b=>b.low)),pad=(hi-lo||1)*.1;
    const ymax=hi+pad,ymin=lo-pad;const x=i=>left+(i-start+.5)/(count-start)*(W-left-right),y=p=>top+(ymax-p)/(ymax-ymin)*priceH;
    visiblePicks=[];let v=rect(0,0,W,H,col.ink);
    for(let i=0;i<=4;i++){let price=ymin+(ymax-ymin)*i/4,yy=y(price);v+=`<line x1="${left}" x2="${W-right}" y1="${yy}" y2="${yy}" stroke="${col.grid}"/>`+text(W-right+10,yy+4,fmt(price),11,col.mute);}
    v+=text(left,18,`${data.meta.synthetic?'合成教学数据':'用户导入数据'} · ${data.meta.trade_level||data.meta.level||'示例级别'} · 截至第 ${count} 根`,12,col.mute);
    if(layers.centers)for(const [ci,c] of centers.entries()){if(c.end<start)continue;const xx=x(Math.max(start,c.start)),ww=Math.max(3,x(c.end)-xx),color=c.rank>1?col.gold:col.teal;const a=pick('递归中枢',c);v+=`<g ${a}>${rect(xx,y(c.zg),ww,y(c.zd)-y(c.zg),color,'opacity=".10"')}${rect(xx,y(c.zg),ww,y(c.zd)-y(c.zg),'none','stroke="'+color+'" stroke-width="1.5"')}${text(xx+6,y(c.zg)-8,`L${c.rank} 中枢 ${ci+1} · ${fmt(c.zd)} / ${fmt(c.zg)}`,11,color)}</g>`;}
    if(layers.candles){const cw=Math.max(1,Math.min(8,(W-left-right)/(count-start)*.56));for(const b of bs){const color=b.close>=b.open?col.rise:col.fall;v+=`<line x1="${x(b.index)}" x2="${x(b.index)}" y1="${y(b.high)}" y2="${y(b.low)}" stroke="${color}" stroke-width="1"/>`+rect(x(b.index)-cw/2,Math.min(y(b.open),y(b.close)),cw,Math.max(1.3,Math.abs(y(b.open)-y(b.close))),color);}}
    if(layers.strokes)for(const b of s.strokes){if(b.end<start)continue;const attrs=pick('笔',b);v+=`<g ${attrs}>${line([[x(b.start),y(b.start_price)],[x(b.end),y(b.end_price)]],col.teal,1.8,b.finalized?'':'stroke-dasharray="5 5"')}${line([[x(b.start),y(b.start_price)],[x(b.end),y(b.end_price)]],'transparent',12)}</g>`;}
    if(layers.segments)for(const b of s.segments){if(b.end<start)continue;v+=`<g ${pick('特征序列线段',b)}>${line([[x(b.start),y(b.start_price)],[x(b.end),y(b.end_price)]],col.gold,3.5,b.state==='confirmed'?'':'stroke-dasharray="8 6"')}${line([[x(b.start),y(b.start_price)],[x(b.end),y(b.end_price)]],'transparent',13)}</g>`;}
    if(layers.types)for(const t of types){if(t.end<start)continue;v+=`<g ${pick('完成分解单元',t)}>${line([[x(t.start),y(t.start_price)],[x(t.end),y(t.end_price)]],col.coral,4,'opacity=".65" stroke-dasharray="3 5"')}${text(x(Math.max(start,t.start))+5,y(t.start_price)-19,`L${t.rank} 完成分解 ≠ 反转`,10,col.coral)}</g>`;}
    if(layers.fractals)for(const f of s.raw_fractals||s.fractals){if(f.source_index<start)continue;const xx=x(f.source_index),yy=y(f.price),d=f.kind==='top'?-1:1;v+=`<g ${pick(f.kind==='top'?'顶分型':'底分型',f)}><path d="M ${xx-4} ${yy+d*10} L ${xx+4} ${yy+d*10} L ${xx} ${yy+d*4} Z" fill="${col.coral}"/><circle cx="${xx}" cy="${yy+d*8}" r="9" fill="transparent"/></g>`;}
    const firstRecords=new Map(),latestRecords=new Map();for(const e of data.events||[]){if(e.available_at>=count)continue;if(e.event==='first_seen')firstRecords.set(e.signal_id,e);if(e.anchor!=null)latestRecords.set(e.signal_id,e);}
    const allSignals=[...firstRecords].map(([id,first])=>({...first,...latestRecords.get(id),first_observed_at:first.available_at})).filter(sig=>!rank||sig.rank===rank);
    if(layers.signals)for(const sig of allSignals){if(sig.anchor<start)continue;const st=s.signal_states?.[sig.signal_id]||sig.status||'candidate',failed=['invalidated','stale_on_confirmation','withdrawn'].includes(st),xx=x(sig.anchor),yy=y(sig.price),dir=sig.side==='buy'?1:-1,c=failed?col.mute:col.coral;
      v+=`<g ${pick('买卖点候选',{...sig,current_status:st})}>${dot(xx,yy,c,5)}<line x1="${xx}" x2="${xx}" y1="${yy}" y2="${yy+dir*29}" stroke="${c}"/><rect x="${xx-42}" y="${yy+dir*29-(dir===1?0:19)}" width="134" height="22" rx="3" fill="${col.ink}" stroke="${c}"/>${text(xx-36,yy+dir*29+(dir===1?15:-4),`L${sig.rank} ${signalNames[sig.signal_class]||'候选'}${st==='withdrawn'?'·撤回':failed?'·失效':''}`,11,c)}</g>`;
      if(!failed)v+=`<line x1="${x(sig.anchor)}" x2="${W-right}" y1="${y(sig.invalidation)}" y2="${y(sig.invalidation)}" stroke="${col.coral}" opacity=".65" stroke-dasharray="5 6"/>`;
    }
    v+=`<line x1="${left}" x2="${W-right}" y1="${macdY}" y2="${macdY}" stroke="${col.grid}"/>`+text(left,macdY-13,'MACD 柱体 · 指标力度线索',11,col.mute);
    const hist=data.macd.slice(start,count),maxHist=Math.max(.01,...hist.map(v=>Math.abs(v))),bw=Math.max(1,Math.min(6,(W-left-right)/(count-start)*.65));
    hist.forEach((h,i)=>{let hh=Math.abs(h)/maxHist*macdH*.48;v+=rect(x(i+start)-bw/2,h>=0?macdY-hh:macdY,bw,Math.max(.5,hh),h>=0?col.rise:col.fall);});
    for(let j=0;j<5;j++){let i=start+Math.floor((count-start-1)*j/4);v+=text(x(i),H-12,`第${i+1}根`,11,col.mute,'text-anchor="middle"');}
    $('chart-host').innerHTML=`<svg id="chart-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="截至第${count}根的缠论结构代理图">${v}</svg>`;
    $('asof-label').textContent=`截至第 ${count} 根 / ${data.bars[count-1].time.replace('T',' ').slice(0,19)}`;
    $('bar-count').textContent=`${count} / ${data.bars.length}`;$('snapshot-count').textContent=`${count} 个历史快照`;
    $('chart-play').textContent=chartPlaying?'暂停回放':'播放形成过程';$('state-label').textContent=stateNames[s.current_state]||s.current_state||'递归结构计算中';
    $('structure-counts').innerHTML=[[s.raw_fractals?.length??s.fractals.length,'已知分型'],[s.strokes.length,'严格笔 / 含末笔'],[s.segments.length,'特征序列线段'],[centers.length,rank?`L${rank} 中枢`:'各秩中枢']].map(([n,label])=>`<div><b>${n}</b>${label}</div>`).join('');
    const audit=s.certificate_audit,ls=s.hierarchy?.levels||[];$('hierarchy-audit').innerHTML=`<b>递归凭据：${audit?.state==='passed'?'重算通过':'尚在形成'}</b>${ls.map(l=>`<div class="audit-line"><span>L${l.rank} · 中枢 ${l.centers.length}</span><span>完成分解 ${l.completed_types.length}</span></div>`).join('')}<div>通过凭据检查，不等于已经反转。</div>`;
    $('signal-evidence').innerHTML='<div class="signal-list">'+(allSignals.map(sig=>{const st=s.signal_states?.[sig.signal_id]||sig.status,failed=['invalidated','stale_on_confirmation','withdrawn'].includes(st);return `<div class="signal-note ${failed?'invalidated':''}"><strong>L${sig.rank} ${signalNames[sig.signal_class]||sig.signal_class} ${st==='withdrawn'?'· 已撤回':failed?'· 已失效':'· 结构候选'}</strong>极值：${timeName(sig.anchor)}<br>首次观测：${timeName(sig.first_observed_at)}<br>失效边界：${fmt(sig.invalidation)}<br>${failed?'保留旧版本，依据以当前时点为准。':'下级结构确认请在多周期全层图查看。'}</div>`;}).join('')||'<div class="signal-note invalidated">此时点没有本秩候选。<br>不补造尚未发生的信号。</div>')+'</div>';
    if(!selected)$('selected-evidence').innerHTML='<span class="empty-label">先点一个结构，看看它凭什么成立。</span>';
    chartNarrator?.update(narrationContext());
  }
  function showEvidence(choice){
    if(!choice)return;selected=choice;const {kind,item}=choice;
    const first=item.source_index??item.start??item.anchor,last=item.end??item.source_index??item.anchor;
    const confirmed=('confirmed_at' in item)?item.confirmed_at:item.available_at;
    const rows=[['原始范围',`${timeName(first)}${last!==first?' → '+timeName(last):''}`],[kind==='买卖点候选'?'候选首次可知':'确认时间',timeName(confirmed)],['最早可用',timeName(item.available_at??item.confirmed_at)],['定义口径',item.definition_mode||'structure_proxy']];
    if(item.finalized!=null)rows.push(['完成状态',item.finalized?'已封闭的笔':'未完成尾笔']);
    if(item.current_status)rows.push(['当前状态',item.current_status==='invalidated'?'已失效':item.current_status]);
    if(item.zd!=null)rows.push(['核心边界',`${fmt(item.zd)} — ${fmt(item.zg)}`],['外沿范围',`${fmt(item.dd)} — ${fmt(item.gg)}`]);
    if(item.rank!=null)rows.push(['结构秩',`L${item.rank}${item.child_rank!=null?' ← L'+item.child_rank:''}`]);
    if(item.components)rows.push(['组成单元',item.components.map(x=>typeof x==='number'?x+1:x).join(', ')]);
    if(item.confirmation?.path)rows.push(['线段确认路径',({feature_no_gap:'无缺口特征分型',feature_gap:'缺口后的第二序列',first_pen_break:'笔破坏后的结构确认'})[item.confirmation.path]||item.confirmation.path]);
    if(item.certificate)rows.push(['中枢凭据',item.certificate.passed?'组件/区间检查通过':'未通过']);
    if(item.completion?.is_turn_confirmation===false)rows.push(['完成的含义','同级分解单元完成，非反转确认']);
    $('selected-evidence').innerHTML=`<div class="evidence-title">${esc(kind)} <span>#${item.id??item.source_index??item.anchor??''}</span></div>${rows.map(([k,v])=>`<div class="evidence-row"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('')}<details><summary style="margin-top:12px;font-size:11px;cursor:pointer">查看原始算法记录</summary><pre class="raw-evidence">${esc(JSON.stringify(item,null,2))}</pre></details>`;
    chartNarrator?.selectObject(kind,item);
  }
  function download(filename,content,type){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function currentExport(){
    const s=snapshot(),counts=Object.fromEntries(['raw_fractals','fractals','strokes','segments','centers','types','signal_candidates'].map(key=>[key,(s[key]||[]).length]));
    return {meta:{...data.meta,counts,as_of:count-1,execution_allowed:false},bars:data.bars.slice(0,count),snapshot:s,events:data.events.filter(e=>e.available_at<count)};
  }
  function animate(now){
    const dt=lastFrame?Math.min(.1,(now-lastFrame)/1000):0;lastFrame=now;
    if(lessonPlaying&&activeView==='lesson'){
      const m=chapterMedia(chapter), duration=m?.duration||Math.max(12,lessons[chapter].narration.length/4);
      if($('voice').checked&&m)lessonElapsed=audio.currentTime;else lessonElapsed+=dt;
      const p=Math.min(1,lessonElapsed/duration);if(Math.abs(p-lessonProgress)>.009){lessonProgress=p;renderLesson(p);}
      if((!$('voice').checked||!m)&&p>=1)nextLesson();
    }
    if(chartPlaying&&activeView==='chart'&&now-chartLast>+$('chart-speed').value){chartLast=now;if(count<data.bars.length)setCount(count+1);else{chartPlaying=false;renderChart();}}
    requestAnimationFrame(animate);
  }
  if(!lessons.length||!data){$('fatal-error').hidden=false;$('fatal-error').textContent='数据未载入，请把 index.html、lessons.js、data.js 和 app.js 放在同一目录。';return;}
  $('tab-lesson').onclick=()=>switchView('lesson');$('tab-chart').onclick=()=>switchView('chart');$('tab-full').onclick=()=>switchView('full');$('tab-period').onclick=()=>switchView('period');$('go-chart').onclick=()=>switchView('chart');$('back-lesson').onclick=()=>switchView('lesson');document.querySelector('.brand').onclick=e=>{e.preventDefault();switchView('lesson');};
  $('lesson-prev').onclick=()=>setChapter(chapter-1,lessonPlaying);$('lesson-next').onclick=()=>setChapter(chapter+1,lessonPlaying);$('lesson-play').onclick=()=>{if(chapter===lessons.length-1&&lessonElapsed>=(chapterMedia(chapter)?.duration||999))switchView('chart');else playLesson();};
  $('chapter-list').onclick=e=>{const b=e.target.closest('[data-chapter]');if(b)setChapter(+b.dataset.chapter,lessonPlaying);};
  $('voice').onchange=()=>{if(lessonPlaying){if($('voice').checked&&chapterMedia(chapter)){audio.currentTime=lessonElapsed;audio.play().catch(()=>{lessonPlaying=false;renderLesson(lessonProgress);});}else audio.pause();}};
  audio.onended=()=>{if(lessonPlaying)nextLesson();};
  $('chart-play').onclick=()=>{if(count===data.bars.length)setCount(5);chartPlaying=!chartPlaying;renderChart();};$('chart-step').onclick=()=>{chartPlaying=false;setCount(count+1);};$('chart-reset').onclick=()=>{chartPlaying=false;setCount(5);};
  $('time-slider').max=data.bars.length;$('time-slider').oninput=e=>{chartPlaying=false;setCount(+e.target.value);};
  $('window-size').onchange=()=>{selected=null;renderChart();};$('rank-select').onchange=()=>{selected=null;renderChart();};
  for(const input of document.querySelectorAll('[data-layer]'))input.onchange=()=>{layers[input.dataset.layer]=input.checked;selected=null;renderChart();};
  for(const b of document.querySelectorAll('[data-jump]'))b.onclick=()=>{chartPlaying=false;setCount(+b.dataset.jump);};
  $('chart-host').onclick=e=>{const el=e.target.closest('[data-pick]');if(el)showEvidence(visiblePicks[+el.dataset.pick]);};$('chart-host').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){const el=e.target.closest('[data-pick]');if(el){e.preventDefault();e.stopPropagation();showEvidence(visiblePicks[+el.dataset.pick]);}}};
  $('export-json').onclick=()=>download(`chanlun-asof-${count}.json`,JSON.stringify(currentExport(),null,2),'application/json');
  $('export-svg').onclick=()=>{const copy=$('chart-svg').cloneNode(true),meta=document.createElementNS('http://www.w3.org/2000/svg','metadata');meta.textContent=JSON.stringify(currentExport().meta);copy.insertBefore(meta,copy.firstChild);download(`chanlun-asof-${count}.svg`,copy.outerHTML,'image/svg+xml');};
  document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;if(e.key===' '){e.preventDefault();activeView==='lesson'?playLesson():$('chart-play').click();}if(activeView==='lesson'&&e.key==='ArrowRight')setChapter(chapter+1,lessonPlaying);if(activeView==='lesson'&&e.key==='ArrowLeft')setChapter(chapter-1,lessonPlaying);});
  window.addEventListener('resize',()=>{selected=null;renderChart();});
  $('total-duration').textContent=media.video_seconds?mmss(media.video_seconds):'';
  count=Math.min(130,data.bars.length);$('time-slider').value=count;
  document.querySelector('.jump-cases').hidden=!data.meta.synthetic;
  $('data-description').innerHTML=`${data.meta.synthetic?'合成教学示例':'用户导入数据'} · ${data.bars.length} 根K线<br>特征序列 + 声明口径递归`;
  for(let rank=4;rank<=8;rank++){const option=document.createElement('option');option.value=String(rank);option.textContent=`L${rank} · 未形成时解释原因`;$('rank-select').appendChild(option);}
  chartNarrator=window.ChanChartNarrator?.mount($('chart-narration'),narrationContext,{highlight:highlightNarration});
  setChapter(0);renderChart();if(location.hash==='#chart')switchView('chart');else if(location.hash==='#full')switchView('full');else if(location.hash==='#period')switchView('period');requestAnimationFrame(animate);
  window.CHAN_APP={setCount,setChapter,switchView,currentExport,getState:()=>({chapter,count,lessonPlaying,chartPlaying,activeView}),renderChart,getNarrator:()=>chartNarrator};
})();
