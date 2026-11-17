/* Period-aware, as-of explanation player. Data and spoken facts share one frame. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id), catalog=window.CHAN_PERIOD_CATALOG, explain=window.ChanExplain;
 const E=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const F=value=>Number.isFinite(+value)?(+value).toFixed(2):'—';
 const C={bg:'#102c2b',text:'#eaf5ef',muted:'#91aea3',grid:'#284540',mint:'#65d2ba',gold:'#e1c07c',coral:'#ed9c77',up:'#d56860',down:'#439b80'};
 const names={first_buy:'一买候选',second_buy:'二买候选',third_buy:'三买候选',first_sell:'一卖候选',second_sell:'二卖候选',third_sell:'三卖候选'};
 let period='5m',rank='all',frameIndex=0,stepIndex=0,selected=null,model=null;
 let picks=[],objectIndex=new Map(),replayTimer=null,speechToken=0,speechMode=null,speechPaused=false,voices=[];
 const layers={bars:true,fractals:true,strokes:true,segments:true,centers:true,types:false,signals:true};
 const synth=('speechSynthesis' in window)?window.speechSynthesis:null;
 function pitem(){return catalog.periods[period];}
 function frame(){return pitem().snapshots[frameIndex];}
 function visibleBars(){return pitem().bars.slice(0,frame().input_count);}
 function timeLabel(index){return index==null?'尚未确认':`第 ${index+1} 根`;}
 const finite=Number.isFinite;
 const rawIndex=obj=>obj.source_index??obj.source??obj.start??obj.anchor??obj.index;
 const available=obj=>obj.available_at??obj.completed_at??obj.formed_at??obj.basis_at??obj.confirmed_at;
 function rect(x,y,w,h,color,extra=''){return `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${color}" ${extra}/>`;}
 function txt(x,y,label,size=12,color=C.text,extra=''){return `<text x="${x}" y="${y}" font-size="${size}" fill="${color}" ${extra}>${E(label)}</text>`;}
 function ln(points,color,width=2,extra=''){return `<polyline points="${points.map(p=>p.join(',')).join(' ')}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" ${extra}/>`;}
 function gather(report){
   const base=report.base||{},hier=report.hierarchy||{},levels=hier.levels||[];
   const centers=report.centers||levels.flatMap(l=>l.centers||[]);
   const types=report.types||levels.flatMap(l=>l.completed_types||[]);
   const result={fractals:base.fractals||report.fractals||[],strokes:base.strokes||report.strokes||[],segments:base.segments||report.segments||[],centers,types,signals:report.signals||report.signal_candidates||[],merged:base.merged||report.merged||[]};
   const cutoff=frame().as_of;
   for(const key of Object.keys(result))result[key]=result[key].filter(o=>available(o)==null||available(o)<=cutoff);
   return result;
 }
 function rankMatches(obj){return rank==='all'||(rank==='0'?false:Number(obj.rank)===Number(rank));}
 function allObjects(){const o=gather(frame().report);objectIndex=new Map();for(const[k,items]of Object.entries(o))for(const item of items){if(item.id)objectIndex.set(item.id,{kind:k,item});}return o;}
 function stopReplay(){if(replayTimer!==null)clearInterval(replayTimer);replayTimer=null;$('replay').textContent='播放观测过程';}
 function stopSpeech(message){speechToken++;speechMode=null;speechPaused=false;if(synth)synth.cancel();$('speech-pause').textContent='暂停';if(message)$('speech-status').textContent=message;}
 function refreshVoices(){if(synth)voices=synth.getVoices();}
 if(synth){refreshVoices();synth.addEventListener?.('voiceschanged',refreshVoices);}
 function chooseVoice(){return voices.find(v=>/^zh[-_]CN/i.test(v.lang))||voices.find(v=>/^zh/i.test(v.lang))||null;}
 function say(text,mode,onend){
   stopSpeech();if(!synth){$('speech-status').textContent='当前浏览器没有语音朗读功能，下面保留完整文字讲解。';return;}
   const voice=chooseVoice();
   if(!voice&&voices.length){$('speech-status').textContent='未找到中文语音，可继续阅读文字；安装系统中文语音后刷新页面再试。';return;}
   const u=new SpeechSynthesisUtterance(String(text||''));u.lang='zh-CN';u.rate=Number($('speech-rate').value);if(voice)u.voice=voice;
   const token=++speechToken;speechMode=mode;$('speech-status').textContent=mode==='guided'?'正在带读当前一条，结束后进入下一条。':'正在朗读当前图；切换周期、层级或时点后停止。';
   u.onend=()=>{if(token!==speechToken)return;speechMode=null;speechPaused=false;$('speech-pause').textContent='暂停';$('speech-status').textContent='本段朗读完成。';if(onend)onend();};
   u.onerror=e=>{if(token!==speechToken||e.error==='canceled'||e.error==='interrupted')return;speechMode=null;$('speech-status').textContent='语音未能继续播放，可使用下方完整文字讲解。';};
   synth.speak(u);
 }
 function currentStep(){return model?.steps?.[stepIndex];}
 function selectedSpeech(){return selected?explain.describeObject(selected.kind,selected.item,visibleBars()).speech:model?.speech;}
 function guided(){const s=currentStep();if(!s)return;say(`${s.title}。${s.text}`,'guided',()=>{if(stepIndex+1<(model.steps||[]).length){stepIndex++;selected=null;renderStep();draw();guided();}});}
 function resetKnowledge(message='图已切换，讲解按当前时点重新整理。'){stopReplay();stopSpeech(message);stepIndex=0;selected=null;}
 function setPeriod(value){if(!catalog.periods[value])throw Error(`未提供周期：${value}`);resetKnowledge();period=value;frameIndex=pitem().snapshots.length-1;render();}
 function setRank(value){if(value!==null&&value!=='all'&&!(Number(value)>=0&&Number(value)<=8))throw Error('层级应为L0至L8或all');resetKnowledge();rank=value==null?'all':String(value);$('rank-select').value=rank;render();}
 function setSnapshot(value){resetKnowledge();frameIndex=Math.max(0,Math.min(pitem().snapshots.length-1,Math.round(Number(value))));render();}
 function buildModel(){const p=pitem(),f=frame();return explain.explainFrame({period,rank:rank==='all'?null:Number(rank),as_of:f.as_of,bars:visibleBars(),report:f.report,source_group:p.source_group,synthetic:p.synthetic,availablePeriods:catalog.meta.period_order});}
 function pickAttrs(kind,item){const n=picks.length;picks.push({kind,item});return `class="pick" data-pick="${n}" role="button" tabindex="0" aria-label="查看${E(kind)} ${E(item.id||'')}"`;}
 function highlightId(){return selected?.item?.id||currentStep()?.objectId;}
 function draw(){
   const all=allObjects(),bs=visibleBars(),windowSize=Number($('chart-window').value),begin=windowSize?Math.max(0,bs.length-windowSize):0,shown=bs.slice(begin);
   const W=innerWidth<800?700:1000,H=480,L=44,R=58,T=35,PH=318,MY=402,MH=45;
   if(!shown.length){$('plot-host').innerHTML='<p style="color:white;padding:30px">当前时点没有可用K线。</p>';return;}
   const high=Math.max(...shown.map(b=>b.high)),low=Math.min(...shown.map(b=>b.low)),pad=(high-low||1)*.10;
   const x=i=>L+(i-begin+.5)/(bs.length-begin)*(W-L-R),y=p=>T+(high+pad-p)/(high-low+2*pad)*PH;
   const highlight=highlightId();picks=[];let v=rect(0,0,W,H,C.bg);
   v+=`<defs><clipPath id="price-clip"><rect x="${L-8}" y="${T-15}" width="${W-L-R+16}" height="${PH+38}"/></clipPath></defs>`;
   for(let i=0;i<=4;i++){const price=low-pad+(high-low+2*pad)*i/4,yy=y(price);v+=`<line x1="${L}" x2="${W-R}" y1="${yy}" y2="${yy}" stroke="${C.grid}"/>`+txt(W-R+9,yy+4,F(price),10,C.muted);}
   v+=txt(L,18,`${pitem().label} · 截至第 ${bs.length} 根 · ${pitem().synthetic?'合成教学数据':'用户输入'}`,11,C.muted);
   let geom='';
   if(layers.centers)for(const c of all.centers.filter(rankMatches)){if(c.end<begin)continue;const color=c.rank>1?C.gold:C.mint,xx=x(Math.max(begin,c.start)),ww=Math.max(3,x(c.end)-xx),sel=c.id===highlight;
     geom+=`<g ${pickAttrs('center',c)}>${rect(xx,y(c.zg),ww,Math.max(1,y(c.zd)-y(c.zg)),color,`opacity="${sel?.24:.11}"`)}${rect(xx,y(c.zg),ww,Math.max(1,y(c.zd)-y(c.zg)),'none',`stroke="${color}" stroke-width="${sel?3:1.4}"`)}${txt(xx+5,y(c.zg)-7,`L${c.rank} 中枢 · ${F(c.zd)} / ${F(c.zg)}`,10,color)}</g>`;
   }
   if(layers.bars){const width=Math.max(1,Math.min(8,(W-L-R)/(bs.length-begin)*.55));for(const b of shown){const i=b.index??bs.indexOf(b),color=b.close>=b.open?C.up:C.down;geom+=`<line x1="${x(i)}" x2="${x(i)}" y1="${y(b.high)}" y2="${y(b.low)}" stroke="${color}" stroke-width="1"/>${rect(x(i)-width/2,Math.min(y(b.open),y(b.close)),width,Math.max(1.2,Math.abs(y(b.open)-y(b.close))),color)}`;}}
   for(const [key,color,width]of [['strokes',C.mint,1.7],['segments',C.gold,3.1]])if(layers[key])for(const m of all[key]){if(m.end<begin)continue;const sel=m.id===highlight,confirmed=m.state==='confirmed'||m.finalized===true;geom+=`<g ${pickAttrs(key==='strokes'?'stroke':'segment',m)}>${ln([[x(m.start),y(m.start_price)],[x(m.end),y(m.end_price)]],sel?C.coral:color,sel?width+2:width,confirmed?'':'stroke-dasharray="7 6"')}${ln([[x(m.start),y(m.start_price)],[x(m.end),y(m.end_price)]],'transparent',15)}</g>`;}
   if(layers.types)for(const t of all.types.filter(rankMatches)){if(t.end<begin)continue;const sel=t.id===highlight;geom+=`<g ${pickAttrs('type',t)}>${ln([[x(t.start),y(t.start_price)],[x(t.end),y(t.end_price)]],C.coral,sel?5:3,'stroke-dasharray="3 5"')}${txt(x(Math.max(begin,t.start))+5,y(t.start_price)-13,`L${t.rank} 完成分解`,10,C.coral)}</g>`;}
   if(layers.fractals)for(const f of all.fractals){const i=f.source_index??f.source??f.index;if(i<begin)continue;const dir=f.kind==='top'?-1:1,xx=x(i),yy=y(f.price),sel=f.id===highlight;geom+=`<g ${pickAttrs('fractal',f)}><path d="M ${xx-4} ${yy+dir*11} L ${xx+4} ${yy+dir*11} L ${xx} ${yy+dir*4} Z" fill="${sel?C.gold:C.coral}"/><circle cx="${xx}" cy="${yy+dir*9}" r="10" fill="transparent"/></g>`;}
   if(layers.signals)for(const s of all.signals.filter(rankMatches)){if(s.anchor<begin)continue;const st=s.state||s.status,failed=['invalidated','withdrawn','stale_on_confirmation'].includes(st),color=failed?C.muted:C.coral,xx=x(s.anchor),yy=y(s.price),dir=s.side==='buy'?1:-1,label=names[s.class]||names[String(s.signal_class||'').replace('_candidate','')]||'结构候选';geom+=`<g ${pickAttrs('signal',s)}><circle cx="${xx}" cy="${yy}" r="${s.id===highlight?8:5}" fill="${color}"/><line x1="${xx}" x2="${xx}" y1="${yy}" y2="${yy+dir*24}" stroke="${color}"/>${txt(xx+7,yy+dir*24,`L${s.rank} ${label}${failed?'·失效':''}`,10,color)}</g>`;}
   const target=highlight?objectIndex.get(highlight):null;
   if(target){const obj=target.item,a=rawIndex(obj),b=obj.end??a;if(finite(a)&&finite(b)&&b>=begin){const xx=x(Math.max(a,begin)),end=x(Math.min(b,bs.length-1));geom=rect(xx-5,T,Math.max(10,end-xx+10),PH,C.coral,'opacity=".055"')+geom;}}
   v+=`<g clip-path="url(#price-clip)">${geom}</g>`;
   v+=`<line x1="${L}" x2="${W-R}" y1="${MY}" y2="${MY}" stroke="${C.grid}"/>`+txt(L,MY-13,'MACD · 辅助力度，不定义买卖点',10,C.muted);
   const rawHist=frame().report.macd||[],hist=rawHist.slice(begin,bs.length).map(h=>typeof h==='number'?h:(h.histogram??h.hist??0)),max=Math.max(.01,...hist.map(Math.abs)),bw=Math.max(1,Math.min(6,(W-L-R)/(bs.length-begin)*.55));hist.forEach((h,i)=>{const hh=Math.abs(h)/max*MH*.6;v+=rect(x(begin+i)-bw/2,h>=0?MY-hh:MY,bw,Math.max(.6,hh),h>=0?C.up:C.down);});
   for(let j=0;j<5;j++){const i=begin+Math.floor((bs.length-begin-1)*j/4);v+=txt(x(i),H-12,`第${i+1}根`,10,C.muted,'text-anchor="middle"');}
   $('plot-host').innerHTML=`<svg id="period-chart" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${pitem().label}当前截止图">${v}</svg>`;
   const centerCount=all.centers.filter(rankMatches).length,typeCount=all.types.filter(rankMatches).length;
   $('plot-status').textContent=`当前已知：${all.fractals.length} 个分型 / ${all.strokes.length} 笔 / ${all.segments.length} 线段 / ${centerCount} 个所选层级中枢 / ${typeCount} 个完成分解。虚线待确认，灰色候选已失效。点图可查看这条线的形成依据。`;
 }
 function renderStep(){
   const steps=model?.steps||[];stepIndex=Math.max(0,Math.min(steps.length-1,stepIndex));const s=steps[stepIndex];
   $('step-position').textContent=steps.length?`${String(stepIndex+1).padStart(2,'0')} / ${steps.length}`:'0 / 0';
   $('step-prev').disabled=stepIndex===0;$('step-next').disabled=stepIndex>=steps.length-1;
   $('active-step').innerHTML=s?`<span>STEP ${String(stepIndex+1).padStart(2,'0')}</span><h3>${E(s.title)}</h3><p>${E(s.text)}</p>`:'<p>当前没有可解释结构。</p>';
   $('step-list').innerHTML=steps.map((item,i)=>`<button data-step="${i}" class="${i===stepIndex?'active':''}" aria-current="${i===stepIndex?'step':'false'}"><span>${String(i+1).padStart(2,'0')}</span>${E(item.title)}</button>`).join('');
 }
 function renderExplanation(){
   model=buildModel();$('explanation-title').textContent=model.title;$('explanation-overview').textContent=model.overview;$('period-role').textContent=typeof model.periodRole==='string'?model.periodRole:JSON.stringify(model.periodRole);$('rank-role').textContent=typeof model.rankRole==='string'?model.rankRole:JSON.stringify(model.rankRole);
   const a=model.availability||{},reasons=a.reasons||[];$('availability').classList.toggle('warn',!['available','complete','ready'].includes(a.status));
   $('availability').textContent=reasons.length?reasons.join('；'):(a.status==='available'?'所选层级已有结构证据。':'以当前时点已有结构解释；未确认项保留等待。');
   $('object-panel').hidden=true;renderStep();
 }
 function render(){
   const p=pitem(),f=frame(),g=catalog.meta.source_groups?.[p.source_group],last=visibleBars().at(-1);
   $('period-buttons').innerHTML=catalog.meta.period_order.map(key=>`<button data-period="${key}" class="${key===period?'active':''}" aria-pressed="${key===period}">${E(catalog.periods[key].label)}</button>`).join('');
   $('current-period').textContent=p.label;$('current-asof').textContent=(f.as_of_time||last?.time||'').replace('T',' ').slice(0,19);$('source-note').textContent=`${g?.label||p.source_group} · ${p.synthetic?'程序合成，非真实行情。':''} ${g?.note||''} 分钟源与长期独立日线源不能拼成已验证的跨级别证据。`;
   $('frame-slider').max=Math.max(0,p.snapshots.length-1);$('frame-slider').value=frameIndex;$('frame-position').textContent=`${frameIndex+1} / ${p.snapshots.length} 次观测`;$('bars-count').textContent=`${f.input_count} / ${p.bars.length} 根K线`;
   $('schedule-note').textContent='回放选定的前缀观测时点，每一帧都重新计算；不是每一根的完整回放。';
   $('first-frame').disabled=frameIndex===0;$('previous-frame').disabled=frameIndex===0;$('last-frame').disabled=frameIndex===p.snapshots.length-1;$('next-frame').disabled=frameIndex===p.snapshots.length-1;
   $('period-role-title').textContent=`${p.label}，解决什么问题`;
   renderExplanation();draw();
 }
 function setStep(index){stopSpeech('讲解位置已改变，可朗读这一条。');selected=null;$('object-panel').hidden=true;stepIndex=Math.max(0,Math.min(model.steps.length-1,index));renderStep();draw();}
 function selectObject(choice){if(!choice)return;stopReplay();stopSpeech('已选中结构，点击朗读可听这一个对象的依据。');selected=choice;const d=explain.describeObject(choice.kind,choice.item,visibleBars());$('object-panel').hidden=false;$('object-title').textContent=d.title;$('object-text').textContent=d.text;$('object-rows').innerHTML=(d.rows||[]).map(row=>`<div><span>${E(row.label)}</span><b>${E(row.value)}</b></div>`).join('');draw();}
 function currentExport(){return {meta:{period,label:pitem().label,rank:rank==='all'?null:Number(rank),as_of:frame().as_of,as_of_time:frame().as_of_time,synthetic:pitem().synthetic,source_group:pitem().source_group,input_sha256:pitem().input_sha256,profile:catalog.meta.profile,execution_allowed:false,strict_original_equivalence_proven:false,cross_group_link_allowed:false},bars:visibleBars(),report:frame().report,explanation:model};}
 function save(filename,text,type){const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 if(!catalog?.periods||!explain?.explainFrame){$('load-error').hidden=false;$('load-error').textContent='周期数据或讲解模块没有载入。请把本页、period_catalog.js、chart_explainer.js、period-explained.js放在同一目录。';$('main-grid').hidden=true;return;}
 $('period-buttons').onclick=e=>{const b=e.target.closest('[data-period]');if(b)setPeriod(b.dataset.period);};$('rank-select').onchange=e=>setRank(e.target.value);$('chart-window').onchange=()=>{stopSpeech('视野已调整，讲解仍依据当前时点。');draw();};
 $('frame-slider').oninput=e=>setSnapshot(+e.target.value);$('first-frame').onclick=()=>setSnapshot(0);$('last-frame').onclick=()=>setSnapshot(pitem().snapshots.length-1);$('previous-frame').onclick=()=>setSnapshot(frameIndex-1);$('next-frame').onclick=()=>setSnapshot(frameIndex+1);
 $('replay').onclick=()=>{stopSpeech('正在回放形成过程，讲解按每个时点更新。');if(replayTimer!==null){stopReplay();return;}if(frameIndex===pitem().snapshots.length-1)frameIndex=0;selected=null;stepIndex=0;render();$('replay').textContent='暂停观测';replayTimer=setInterval(()=>{if(frameIndex>=pitem().snapshots.length-1){stopReplay();return;}frameIndex++;selected=null;stepIndex=0;render();},1200);};
 $('step-prev').onclick=()=>setStep(stepIndex-1);$('step-next').onclick=()=>setStep(stepIndex+1);$('step-list').onclick=e=>{const b=e.target.closest('[data-step]');if(b)setStep(+b.dataset.step);};
 $('read-chart').onclick=()=>{stopReplay();say(selectedSpeech(),'chart');};$('read-step').onclick=()=>{stopReplay();const s=currentStep();if(s)say(`${s.title}。${s.text}`,'step');};$('guided-read').onclick=()=>{stopReplay();guided();};
 $('speech-pause').onclick=()=>{if(!synth||!speechMode)return;if(speechPaused){synth.resume();speechPaused=false;$('speech-pause').textContent='暂停';$('speech-status').textContent='继续朗读。';}else{synth.pause();speechPaused=true;$('speech-pause').textContent='继续';$('speech-status').textContent='朗读已暂停。';}};$('speech-stop').onclick=()=>stopSpeech('朗读已停止。');$('speech-rate').onchange=()=>stopSpeech('语速已调整，点击朗读重新开始。');
 $('clear-object').onclick=()=>{stopSpeech('已返回整图讲解。');selected=null;$('object-panel').hidden=true;draw();};
 $('plot-host').onclick=e=>{const node=e.target.closest('[data-pick]');if(node)selectObject(picks[+node.dataset.pick]);};$('plot-host').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){const node=e.target.closest('[data-pick]');if(node){e.preventDefault();selectObject(picks[+node.dataset.pick]);}}};
 $('export-json').onclick=()=>save(`chanlun-${period}-asof-${frame().as_of+1}.json`,JSON.stringify(currentExport(),null,2),'application/json');$('export-svg').onclick=()=>{const s=$('period-chart').cloneNode(true),m=document.createElementNS('http://www.w3.org/2000/svg','metadata');m.textContent=JSON.stringify(currentExport().meta);s.insertBefore(m,s.firstChild);save(`chanlun-${period}-asof-${frame().as_of+1}.svg`,s.outerHTML,'image/svg+xml');};
 window.addEventListener('resize',draw);window.addEventListener('pagehide',()=>{stopReplay();stopSpeech();});
 if(!synth){$('speech-status').textContent='当前浏览器没有语音朗读功能；完整文字和逐条带看仍可使用。';$('read-chart').disabled=$('read-step').disabled=$('guided-read').disabled=true;}
 frameIndex=pitem().snapshots.length-1;render();
 window.CHAN_PERIOD_APP={setPeriod,setRank,setSnapshot,setStep,selectObject,stopSpeech,render,currentExport,getExplanation:()=>model,getState:()=>({period,rank,snapshot:frameIndex,as_of:frame().as_of,step:stepIndex,selectedId:selected?.item?.id||null,replayPlaying:replayTimer!==null,speechMode,speechPaused})};
})();
