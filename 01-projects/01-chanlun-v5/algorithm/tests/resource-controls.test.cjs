const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../workbench/web/app.js'),'utf8');

function functionSource(name){
  const start=source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start>=0,`missing function ${name}`);
  const after=source.slice(start+10).search(/\n(?:async )?function /);
  return source.slice(start,after<0?undefined:start+10+after);
}

function setup(){
  const elements=new Map();
  const el=selector=>{
    if(!elements.has(selector))elements.set(selector,{value:'',textContent:'',disabled:false,close(){this.closed=true;}});
    return elements.get(selector);
  };
  const resources=[{textContent:''},{textContent:''}];
  const requests=[];
  const context={S:{},$:el,$$:()=>resources,Number,String,Date,setInterval(){return 0;},
    integer:value=>Number(value).toLocaleString('zh-CN'),
    api:async(url,body)=>{requests.push({url,body});return {id:'test-job',total:1};},
    text:(selector,value)=>el(selector).textContent=value,
    sessionStorage:{setItem(){}},view(){},refreshOverview:async()=>{},toast(){},
    refreshBacktests(){context.refreshed=true;}};
  vm.createContext(context);
  for(const name of ['parseWorkerSelection','workerSelectionLabel','resourceSummaryText','refreshResourceStatus','submitJob','startBacktest']){
    vm.runInContext(functionSource(name),context);
  }
  return {context,el,resources,requests};
}

test('auto remains a string in job and backtest launch payloads',async()=>{
  const x=setup();
  x.el('#job-workers').value='auto';x.el('#job-symbols').value='sh600000';
  x.el('#job-mode').value='day';x.el('#job-scope').value='selected';
  x.el('#job-tolerance').value='1';
  await x.context.submitJob({preventDefault(){}});
  assert.equal(x.requests[0].url,'/api/jobs');
  assert.equal(x.requests[0].body.workers,'auto');
  x.el('#backtest-workers').value='auto';
  await x.context.startBacktest();
  assert.equal(x.requests[1].url,'/api/backtests/start');
  assert.equal(x.requests[1].body.workers,'auto');
  assert.equal(x.el('#backtest-start').disabled,false);
});

test('explicit workers stay numeric and invalid inputs never reach the API',async()=>{
  const x=setup();x.el('#backtest-workers').value='16';
  await x.context.startBacktest();
  assert.equal(x.requests[0].body.workers,16);
  for(const value of ['', '0', '17', '1.5', 'many']){
    assert.throws(()=>x.context.parseWorkerSelection(value),/并发数/);
  }
  assert.throws(()=>x.context.parseWorkerSelection('16',12),/1到12/);
});

test('resource status reports measured memory and CPU without claiming GPU execution',()=>{
  const x=setup();const text=x.context.resourceSummaryText({
    cpu:{logical_processors:20},memory:{available_bytes:1024**3,total_bytes:16*1024**3},
    plan:{target_workers:0,ceiling:16,reason:'memory_pressure'},
    gpu:{name:'RTX 3050 Ti',supported:false,execution:'cpu'},execution_backend:'cpu_multiprocess',
  });
  assert.match(text,/CPU 20线程/);assert.match(text,/1\.0 GB \/ 16\.0 GB/);
  assert.match(text,/自动并发 0 \/ 上限 16/);assert.match(text,/内存紧张，暂停派发/);
  assert.match(text,/显卡 RTX 3050 Ti/);assert.match(text,/当前算法使用CPU多进程/);
  assert.doesNotMatch(text,/GPU加速|显卡加速/);
});

test('resource refreshes are rate limited and unavailable state never invents measurements',async()=>{
  const x=setup();x.context.api=async url=>{x.requests.push({url});return {};};
  await x.context.refreshResourceStatus();await x.context.refreshResourceStatus();
  assert.equal(x.requests.length,1);
  assert.match(x.resources[0].textContent,/线程数未知/);
  x.context.api=async()=>{throw Error('offline');};
  await x.context.refreshResourceStatus(true);
  assert.equal(x.resources[0].textContent,'资源状态暂不可用：offline');
  assert.equal(x.context.S.resourcesPending,false);
});

test('both resource-aware forms default to automatic workers',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../workbench/web/index.html'),'utf8');
  assert.match(html,/<select id="backtest-workers"><option value="auto" selected>/);
  assert.match(html,/<select id="job-workers"><option value="auto" selected>/);
  assert.match(html,/id="backtest-resources" data-resource-summary/);
  assert.match(html,/classic=20261117&build=445/);
});
