// Run: sed 's/TASK_SPACE_ID/12/g' scripts/diagnostics/browser-performance.mjs | ego-browser nodejs
// Uses an existing, authenticated local test TaskSpace on a project with tasks; no writes.
const spaceId = Number('TASK_SPACE_ID');
if (!Number.isInteger(spaceId)) throw new Error('Substitute the active TaskSpace ID first');
const task = await taskSpace(spaceId);
const p = task.page('p1');
await p.cdp('Emulation.setDeviceMetricsOverride',{width:1900,height:872,deviceScaleFactor:1,mobile:false});
await p.cdp('Emulation.setCPUThrottlingRate',{rate:4});
const samples=[];
for(let i=0;i<3;i++){
  await p.click('loc=role:button[name="项目首页"]');
  await p.waitForSelector('.project-overview',{state:'visible'});
  await p.evaluate(()=>{window.__perf=[];window.__po?.disconnect();window.__po=new PerformanceObserver(l=>window.__perf.push(...l.getEntries().map(e=>e.duration)));window.__po.observe({type:'longtask'});performance.clearResourceTimings()});
  await p.click('loc=role:button[name="项目任务"]');
  await p.waitForSelector('button[aria-label="刷新任务计划"]',{state:'visible'});
  await p.waitForFunction(()=>document.querySelectorAll('.ant-table-row, .task-plan-row').length>0 && !document.querySelector('.ant-spin-spinning'));
  await p.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  samples.push(await p.evaluate(()=>({longTasks:window.__perf,dom:document.querySelectorAll('*').length,api:performance.getEntriesByType('resource').filter(r=>new URL(r.name).pathname.startsWith('/api/')).map(r=>({path:new URL(r.name).pathname,ms:Math.round(r.duration)}))})));
}
const peaks=samples.map(s=>Math.max(0,...s.longTasks));
const median=peaks.sort((a,b)=>a-b)[1];
console.log(JSON.stringify({scenario:'warm project overview → task plan',samples,medianLongestTaskMs:median,cpuSlowdown:4,budgetMs:200,pass:median<=200},null,2));
await p.evaluate(()=>window.__po?.disconnect());
await p.cdp('Emulation.setCPUThrottlingRate',{rate:1});
if(median>200) process.exitCode=1;
