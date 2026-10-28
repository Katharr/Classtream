/* Teacher commands against stream_fixture.py, isolated from the real classroom. */
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {chromium}=require(process.env.CLASSTREAM_PLAYWRIGHT || 'playwright');
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const base='http://127.0.0.1:18765', errors=[];
  const context=await browser.newContext({viewport:{width:1440,height:960}});
  let headers;
  try {
    const token=(await (await context.request.post(base+'/api/admin/login',{
      data:{username:'fixture',password:'fixture-password'}})).json()).token;
    headers={'X-Admin-Token':token};
    await context.request.post(base+'/api/screen/private',{headers,data:{enabled:false}});
    await context.request.post(base+'/api/screen/permissions',{headers,data:{monitor_id:1,access:'all'}});
    await context.addInitScript(t=>localStorage.setItem('pystream_admin_token',t),token);
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/?host=fixture');
    await page.waitForFunction(()=>document.getElementById('screen-img').width===640);
    await assertEventually(async()=>(await (await context.request.get(base+'/api/teacher-shortcuts',{headers})).json()).enabled);
    const defaults=(await (await context.request.get(base+'/api/teacher-shortcuts',{headers})).json()).bindings;
    assert.equal(defaults.hide,'Ctrl+Alt+Shift+Y');
    assert.equal(defaults.restore,'Ctrl+Alt+Shift+Z');
    assert.ok(!(await (await context.request.get(base+'/?host=fixture')).text()).includes('id="btn-pause"'));
    assert.equal(await page.locator('#btn-pause').count(),0);
    assert.equal(await page.locator('#monitor-list').isVisible(),false);
    assert.equal(await page.locator('#screen-access-panel').isVisible(),false);
    assert.equal(await page.locator('#teacher-restore-btn').count(),0);
    await page.locator('#teacher-hide-btn').hover();
    await page.locator('#teacher-shortcut-tooltip').waitFor({state:'visible'});
    assert.ok((await page.locator('#teacher-shortcut-tooltip').innerText()).includes('网页：h'));
    assert.ok((await page.locator('#teacher-shortcut-tooltip').innerText()).includes(defaults.hide));
    const bodyKey=async key=>{await page.locator('h1').click();await page.keyboard.press(key);};
    const privacy=async()=>(await (await context.request.get(base+'/api/screen/permissions',{headers})).json()).private_mode;
    const waitPrivacy=async expected=>{await assertEventually(async()=>await privacy()===expected);};
    await bodyKey('Space');
    assert.equal(await page.evaluate(async()=>(await import('/static/js/state.js')).state.paused),false);
    await page.evaluate(async()=>(await import('/static/js/controls.js')).togglePause());
    assert.equal(await page.evaluate(async()=>(await import('/static/js/state.js')).state.paused),false);
    await page.locator('#session-name-input').fill('hHnsc');
    await page.locator('#session-name-input').press('h');assert.equal(await privacy(),false);
    await page.locator('h1').click();
    await page.evaluate(()=>{
      document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'h',isComposing:true,bubbles:true}));
      document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'h',repeat:true,bubbles:true}));
      document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'h',ctrlKey:true,bubbles:true}));
    });
    assert.equal(await privacy(),false);
    await page.keyboard.press('/');await page.locator('#teacher-command-dialog').waitFor({state:'visible'});
    await page.locator('#teacher-command-search').fill('隐藏');
    assert.equal(await page.locator('[data-command="hide"]').count(),1);
    await page.locator('#teacher-command-search').press('Escape');
    await page.locator('#teacher-command-dialog').waitFor({state:'hidden'});
    await bodyKey('n');await page.locator('#teacher-new-dialog').waitFor({state:'visible'});
    const before=(await (await context.request.get(base+'/api/status')).json()).session_token;
    await page.locator('#teacher-new-name').press('h');assert.equal(await privacy(),false);
    await page.locator('#teacher-new-name').press('Escape');
    assert.equal((await (await context.request.get(base+'/api/status')).json()).session_token,before);
    const studentContext=await browser.newContext();
    await studentContext.addInitScript(()=>localStorage.setItem('pystream_name','Shortcut student'));
    const student=await studentContext.newPage();student.on('pageerror',e=>errors.push(e.message));
    await student.goto(base+'/class');await student.waitForFunction(()=>document.getElementById('screen-img').width===640);
    assert.equal(await student.locator('#teacher-actions').count(),0);
    assert.equal(await student.locator('#btn-pause').isVisible(),true);
    await page.bringToFront();await bodyKey('h');await waitPrivacy(true);
    await student.locator('#single-private-overlay').waitFor({state:'visible'});
    await page.locator('#teacher-privacy-banner').waitFor({state:'visible'});
    const output=path.resolve(__dirname,'../../docs/快捷键-2026-10-28');fs.mkdirSync(output,{recursive:true});
    await page.screenshot({path:path.join(output,'01-教师隐藏共享.png')});
    assert.equal(await page.locator('#teacher-hide-btn').innerText(),'恢复共享');
    await page.locator('#teacher-hide-btn').hover();
    assert.ok((await page.locator('#teacher-shortcut-tooltip').innerText()).includes('Shift+h'));
    await page.locator('#teacher-hide-btn').click();await waitPrivacy(false);
    await page.locator('#teacher-hide-btn').click();await waitPrivacy(true);
    await bodyKey('h');assert.equal(await privacy(),true); // idempotent hide
    await bodyKey('Shift+h');await waitPrivacy(false);
    await student.locator('#single-private-overlay').waitFor({state:'hidden',timeout:8000});
    await page.locator('#teacher-privacy-banner').waitFor({state:'hidden'});
    await bodyKey('t');assert.equal(await page.locator('#chat-input').evaluate(el=>el===document.activeElement),true);
    await page.locator('#chat-input').fill('');await bodyKey('?');
    await page.locator('#teacher-settings-dialog').waitFor({state:'visible'});
    await page.screenshot({path:path.join(output,'02-快捷键设置.png')});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:path.join(output,'03-手机快捷键设置.png')});
    await page.setViewportSize({width:1440,height:960});
    await page.locator('[data-bind="hide"]').click();await page.keyboard.press('j');
    assert.equal(await page.locator('[data-bind="hide"]').innerText(),'j');
    await page.locator('[data-bind="restore"]').click();await page.keyboard.press('=');
    assert.ok((await page.locator('#teacher-toast').innerText()).includes('占用'));
    await page.keyboard.press('j');
    assert.ok((await page.locator('#teacher-toast').innerText()).includes('占用'));
    await page.keyboard.press('Escape'); // cancel recording
    await page.keyboard.press('Escape'); // close settings
    await page.reload();await page.waitForFunction(()=>document.getElementById('screen-img').width===640);
    await bodyKey('h');assert.equal(await privacy(),false);
    await page.locator('#teacher-hide-btn').hover();
    assert.ok((await page.locator('#teacher-shortcut-tooltip').innerText()).includes('网页：j'));
    await bodyKey('j');await waitPrivacy(true);await bodyKey('Shift+h');await waitPrivacy(false);
    await bodyKey('?');await page.locator('#teacher-bindings-reset').click();
    await page.locator('#teacher-web-enabled').uncheck();await page.keyboard.press('Escape');
    await bodyKey('h');assert.equal(await privacy(),false);
    await page.locator('#teacher-help-btn').click();await page.locator('#teacher-web-enabled').check();
    await page.locator('#teacher-global-hide').fill('Ctrl+Alt+Shift+Y');
    await page.locator('#teacher-global-restore').fill('Ctrl+Alt+Shift+Z');
    await page.locator('#teacher-global-enabled').check();await page.locator('#teacher-global-save').click();
    await assertEventually(async()=>(await (await context.request.get(base+'/api/teacher-shortcuts',{headers})).json()).enabled);
    await page.locator('#teacher-global-enabled').uncheck();await page.locator('#teacher-global-save').click();
    await assertEventually(async()=>!(await (await context.request.get(base+'/api/teacher-shortcuts',{headers})).json()).enabled);
    await page.keyboard.press('Escape');
    // Student keys must not issue teacher commands, while student pause remains usable.
    await student.reload();await student.waitForFunction(()=>document.getElementById('screen-img').width===640);
    await student.bringToFront();await student.locator('h1').click();await student.keyboard.press('h');
    assert.equal(await privacy(),false);await student.keyboard.press('Space');
    assert.equal(await student.evaluate(async()=>(await import('/static/js/state.js')).state.paused),true);
    assert.deepEqual(errors,[]);
    console.log('PASS: no teacher pause, composition/repeat/input/modal guards, command search, create cancellation, student privacy/automatic restore, rebinding persistence/conflict, page disable, native enable/disable, student role separation and pause.');
  } finally {
    if(headers)await context.request.post(base+'/api/teacher-shortcuts',{headers,data:{enabled:false}}).catch(()=>{});
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
async function assertEventually(predicate){
  for(let i=0;i<80;i++){if(await predicate())return;await new Promise(resolve=>setTimeout(resolve,100));}
  throw new Error('Expected shortcut state was not reached');
}
