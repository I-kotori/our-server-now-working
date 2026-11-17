const {chromium}=require('playwright-core');
const fs=require('fs');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{}),headless:true,args:['--no-sandbox']});
 const results=[];
 for(const width of [390,1280]){
  const page=await browser.newPage({viewport:{width,height:900}});
  await page.addInitScript(()=>{
   window.shifts=[];
   new PerformanceObserver(list=>{for(const e of list.getEntries())if(!e.hadRecentInput)window.shifts.push({value:e.value,sources:e.sources.map(s=>s.node?.className||s.node?.id||s.node?.nodeName)});}).observe({type:'layout-shift',buffered:true});
  });
  await page.clock.install();
  let calls=0,mode='up';
  const payload=()=>({generated:Math.floor(Date.now()/1000),services:['포트 101','포트 102','이클래스'].map((name,i)=>({id:['ssh101','ssh102','eclass'][i],name,state:mode,last:Math.floor(Date.now()/1000),ms:4,views:Object.fromEntries([[1,60],[24,24],[168,42]].map(([h,n])=>[h,{bars:Array.from({length:n},(_,i)=>h===168&&i===0?[240,239,false]:[1,1,false]),issues:Array.from({length:n},(_,i)=>({ranges:h===168&&i===0?[[Math.floor(Date.now()/1000)-300,Math.floor(Date.now()/1000)-180,'recovered']]:[],more:0})),success:100}]))})),incidents:[]});
  await page.route('https://status.test/**',async route=>{
   if(new URL(route.request().url()).pathname==='/api/status'){calls++;await new Promise(r=>setTimeout(r,1000));await route.fulfill({json:payload()});}
   else await route.fulfill({contentType:'text/html',body:fs.readFileSync(process.argv[2]||require('node:path').join(__dirname,'../index.html'),'utf8')});
  });
  await page.route('https://static.cloudflareinsights.com/**',r=>r.abort());
  await page.goto('https://status.test/');
  await page.waitForTimeout(1500);
  const initial=await page.evaluate(()=>({cls:window.shifts.reduce((s,e)=>s+e.value,0),shifts:window.shifts,cards:document.querySelectorAll('.card').length,overflow:document.documentElement.scrollWidth>innerWidth}));
  const exact=await page.evaluate(()=>{
   const epoch=t=>Date.parse(t)/1000;
   return {text:barDescription({issues:[{ranges:[[epoch('2026-11-17T04:26:00+09:00'),epoch('2026-11-17T04:28:00+09:00'),'recovered']],more:0}]},0,epoch('2026-11-17T01:50:00+09:00'),14400,240,238,false),midnight:issueTimeRange(epoch('2026-11-17T23:59:00+09:00'),epoch('2026-11-18T00:01:00+09:00'))};
  });
  assert.equal(exact.text,'11. 17. 01:50 ~ 11. 17. 05:50\n99.17% 성공\n11. 17. 04:26 ~ 04:28 동안 접속 이상 확인');
  assert.equal(exact.midnight,'11. 17. 23:59 ~ 11. 18. 00:01');
  for(const index of [0,59]){
   const bar=page.locator('.card').first().locator('.bar').nth(index);
   await bar.hover();
   if(!await page.locator('#graph-tooltip').isVisible())throw Error('tooltip not immediate');
   if(await bar.getAttribute('title'))throw Error('native delayed tooltip remains');
   const box=await page.locator('#graph-tooltip').boundingBox();
   if(box.x<0||box.x+box.width>width)throw Error('tooltip outside viewport');
  }
  await page.keyboard.press('Escape');if(await page.locator('#graph-tooltip').isVisible())throw Error('tooltip dismissal failed');
  await page.locator('.card').first().locator('.bar').first().focus();await page.keyboard.press('ArrowRight');
  if(await page.locator('.card').first().locator('.bar').nth(1).evaluate(el=>el!==document.activeElement))throw Error('tooltip keyboard navigation failed');
  await page.locator('.card').first().locator('.bar').nth(1).blur();
  mode='unknown';await page.clock.fastForward(30000);await page.waitForTimeout(1200);
  if(calls!==2)throw Error(`expected polling twice, got ${calls}`);
  const updated=await page.locator('.state').first().textContent();if(!updated.includes('상태 확인 불가'))throw Error('refresh state did not update');
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
  await page.clock.fastForward(60000);await page.waitForTimeout(100);if(calls!==2)throw Error('hidden tab polled');
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));});
  await page.waitForTimeout(1200);if(calls!==3)throw Error('visible tab did not refresh');
  await page.getByRole('button',{name:'24시간',exact:true}).click();
  const day=await page.locator('.card').first().locator('.bar').count();
  await page.getByRole('button',{name:'7일',exact:true}).click();
  const week=await page.locator('.card').first().locator('.bar').count();
  await page.locator('.card').first().locator('.bar').first().hover();
  const issueText=await page.locator('#graph-tooltip').textContent();
  assert.ok(issueText.includes('99.58% 성공'));assert.ok(issueText.includes('동안 접속 이상 확인'));assert.ok(!/회 검사|회 실패|오전|오후/.test(issueText));
  assert.equal(initial.cards,3);assert.equal(day,24);assert.equal(week,42);assert.equal(await page.locator('.card').first().locator('.bar').count(),42);
  await page.getByRole('button',{name:'1시간',exact:true}).click();assert.equal(await page.locator('.card').first().locator('.bar').count(),60);
  results.push({width,initial,day,week,calls,after:await page.evaluate(()=>({cls:window.shifts.reduce((s,e)=>s+e.value,0),state:document.querySelector('.state')?.textContent}))});
  await page.screenshot({path:require('node:path').join(require('node:os').tmpdir(),`status-${width}.png`),fullPage:true});await page.close();
 }
 if(results.some(r=>r.initial.cls!==0||r.after.cls!==0||r.initial.overflow)){console.log(JSON.stringify(results,null,2));throw Error('layout regression')};
 console.log(JSON.stringify(results,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
