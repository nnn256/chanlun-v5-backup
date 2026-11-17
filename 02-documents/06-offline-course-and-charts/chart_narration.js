/* Context-bound text and optional local Chinese speech for a calculated chart. */
(function(root){
 'use strict';
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const active=new Set();
 function mount(host,getContext,options={}){
  if(!host||!root.ChanExplain)return null;
  let lesson=null,context=null,step=0,selected=null,playing=false,paused=false,utterance=null,generation=0,lastKey='';
  const speech=root.speechSynthesis;
  host.classList.add('cn-lesson');
  host.innerHTML='<div class="cn-heading"><div><p class="cn-eyebrow">图形讲解 · 跟随当前周期、层级与时点</p><h3 class="cn-title"></h3><p class="cn-subtitle"></p></div><div class="cn-source"></div></div><p class="cn-overview"></p><div class="cn-body"><nav class="cn-menu" aria-label="图形讲解步骤"></nav><div class="cn-content"><h4 class="cn-step-title"></h4><p class="cn-text" aria-live="polite"></p><div class="cn-controls"><button class="cn-prev" aria-label="上一段讲解">← 上一段</button><button class="cn-speak cn-primary">朗读这一段</button><button class="cn-walk">逐段讲解</button><button class="cn-pause">暂停朗读</button><button class="cn-stop">停止</button><button class="cn-next" aria-label="下一段讲解">下一段 →</button><label>语速 <select class="cn-rate"><option value="0.9">慢一点</option><option value="1" selected>正常</option><option value="1.2">稍快</option></select></label></div><div class="cn-status" role="status"></div><div class="cn-guide-note">切换周期、层级或回放时点会停止旧讲解，并更新为当前这张图。点选结构，还能单独听它的依据。</div></div></div><div class="cn-object" hidden><h4></h4><p></p><button>朗读这个结构的说明</button></div>';
  const $=selector=>host.querySelector(selector);
  function setStatus(value){$('.cn-status').textContent=value;}
  function stop(){generation++;if(speech&&playing)speech.cancel();playing=false;paused=false;utterance=null;$('.cn-pause').textContent='暂停朗读';}
  function highlight(current){if(options.highlight)options.highlight(current?.objectId||null,current?.kind||null);}
  function showStep(index){
   if(!lesson)return;step=Math.max(0,Math.min(lesson.steps.length-1,index));const current=lesson.steps[step];
   $('.cn-step-title').textContent=`${String(step+1).padStart(2,'0')} / ${current.title}`;
   $('.cn-text').textContent=current.text;
   $('.cn-prev').disabled=step===0;$('.cn-next').disabled=step===lesson.steps.length-1;
   for(const b of $('.cn-menu').children)b.setAttribute('aria-current',+b.dataset.step===step?'step':'false');
   highlight(current);
  }
  function voice(){const voices=speech?.getVoices?.()||[];return voices.find(v=>/^zh[-_]CN$/i.test(v.lang)&&/Huihui|Xiaoxiao|中文|Chinese/i.test(v.name))||voices.find(v=>/^zh/i.test(v.lang));}
  function speakText(value,onend){
   stop();if(!speech||!root.SpeechSynthesisUtterance){setStatus('本浏览器没有中文朗读能力，文字讲解已完整显示。');return;}
   const chosen=voice();if(!chosen){setStatus('没有可用中文语音。请在系统安装中文语音；文字与逐段图解可继续使用。');return;}
   for(const controller of active)if(controller!==api)controller.stop();
   const token=++generation;utterance=new SpeechSynthesisUtterance(value);utterance.lang=chosen.lang||'zh-CN';utterance.voice=chosen;utterance.rate=+$('.cn-rate').value;
   utterance.onstart=()=>{if(token===generation){playing=true;setStatus(`正在朗读 · ${chosen.name}`);}};
   utterance.onend=()=>{if(token!==generation)return;playing=false;paused=false;utterance=null;setStatus('这一段已讲完。');if(onend)onend();};
   utterance.onerror=e=>{if(token!==generation)return;playing=false;paused=false;setStatus(e.error==='interrupted'||e.error==='canceled'?'朗读已停止。':`语音未完成（${e.error}），可直接阅读文字。`);};
   playing=true;speech.cancel();speech.speak(utterance);
  }
  function walkthrough(){if(!lesson)return;const run=()=>{speakText(lesson.steps[step].text,()=>{if(step<lesson.steps.length-1){showStep(step+1);run();}else setStatus('当前这张图已讲完；可切换周期或层级继续。');});};run();}
  function update(next){
   context=next||getContext();if(!context)return;
   const key=JSON.stringify([context.period,context.rank,context.as_of,context.bars?.length,context.report?.as_of,context.report?.input_count]);
   if(key===lastKey)return;
   lastKey=key;stop();selected=null;$('.cn-object').hidden=true;lesson=root.ChanExplain.explainFrame(context);
   $('.cn-title').textContent=lesson.title;$('.cn-subtitle').textContent=lesson.subtitle;
   $('.cn-overview').textContent=lesson.overview;$('.cn-source').textContent=`${context.synthetic===false?'导入行情':'合成教学示例'} · ${context.source_group||lesson.sourceGroup||'本周期输入'}`;
   $('.cn-menu').innerHTML=lesson.steps.map((s,i)=>`<button data-step="${i}" aria-current="${i===0?'step':'false'}"><span class="cn-stepnum">${String(i+1).padStart(2,'0')}</span><span>${esc(s.title)}</span></button>`).join('');
   showStep(0);setStatus('文字说明已按当前图更新。点击按钮后才会朗读。');
  }
  function selectObject(kind,obj){
   stop();selected=root.ChanExplain.describeObject(kind,obj,context?.bars||[]);
   $('.cn-object').hidden=false;$('.cn-object h4').textContent=selected.title;$('.cn-object p').textContent=selected.text;
   setStatus('已选结构，说明对应它的实际组件与时间。');
  }
  $('.cn-menu').onclick=e=>{const b=e.target.closest('[data-step]');if(b){stop();showStep(+b.dataset.step);setStatus('可朗读当前这一段。');}};
  $('.cn-prev').onclick=()=>{stop();showStep(step-1);};$('.cn-next').onclick=()=>{stop();showStep(step+1);};
  $('.cn-speak').onclick=()=>{if(lesson)speakText(lesson.steps[step].text);};$('.cn-walk').onclick=walkthrough;
  $('.cn-pause').onclick=()=>{if(!playing)return;if(paused){speech.resume();paused=false;$('.cn-pause').textContent='暂停朗读';setStatus('继续朗读。');}else{speech.pause();paused=true;$('.cn-pause').textContent='继续朗读';setStatus('已暂停。');}};
  $('.cn-stop').onclick=()=>{stop();setStatus('已停止朗读。');};$('.cn-rate').onchange=()=>{stop();setStatus('语速已调整，重新点击朗读即可。');};
  $('.cn-object button').onclick=()=>{if(selected)speakText(selected.speech||selected.text);};
  const api={update,selectObject,stop,getState:()=>({step,playing,paused,title:lesson?.title,availability:lesson?.availability,stepCount:lesson?.steps?.length||0}),speakText};active.add(api);update();return api;
 }
 root.ChanChartNarrator={mount,stopAll:()=>{for(const item of active)item.stop();}};
 root.addEventListener?.('pagehide',()=>root.ChanChartNarrator.stopAll());
 root.addEventListener?.('message',event=>{if(event.source===root.parent&&event.data?.type==='chan-stop-narration')root.ChanChartNarrator.stopAll();});
})(typeof window!=='undefined'?window:globalThis);
