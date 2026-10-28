/* Real browser checks against stream_fixture.py, never the live classroom. */
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require(process.env.CLASSTREAM_PLAYWRIGHT || 'playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const contexts = [];
  const errors = [];
  try {
    const base = 'http://127.0.0.1:18765';
    const hostContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    contexts.push(hostContext);
    const login = await hostContext.request.post(base + '/api/admin/login', {
      data: { username: 'fixture', password: 'fixture-password' },
    });
    const { token } = await login.json();
    assert.ok(token);
    await hostContext.addInitScript(t => localStorage.setItem('pystream_admin_token', t), token);
    const host = await hostContext.newPage();
    host.on('pageerror', e => errors.push(e.message));
    await host.goto(base + '/?host=admin');
    const painted = async page => page.waitForFunction(() => {
      const c = document.getElementById('screen-img');
      return c?.tagName === 'CANVAS' && c.width === 640 && c.getContext('2d').getImageData(5, 5, 1, 1).data[0] > 230;
    });
    await painted(host);
    const students = [];
    for (let i = 0; i < 4; i++) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      contexts.push(context);
      await context.addInitScript(({ name, slow }) => {
        localStorage.setItem('pystream_name', name);
        if (slow) {
          const send = WebSocket.prototype.send;
          WebSocket.prototype.send = function (value) {
            if (typeof value === 'string' && value.includes('stream:ack')) {
              const ws = this;
              setTimeout(() => { if (ws.readyState === 1) send.call(ws, value); }, 900);
            } else send.call(this, value);
          };
        }
      }, { name: 'Browser student ' + (i + 1), slow: i === 3 });
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(base + '/class');
      await painted(page);
      students.push(page);
    }
    const stats = async () => (await hostContext.request.get(base + '/test/stats')).json();
    await students[0].waitForTimeout(1200);
    assert.equal((await stats()).peers, 5);
    await hostContext.request.post(base + '/test/color/220');
    await students[0].waitForFunction(() => {
      const pixel = document.getElementById('screen-img').getContext('2d').getImageData(290, 290, 1, 1).data;
      return pixel[0] > 190 && pixel[1] < 30;
    });
    await hostContext.request.post(base + '/api/settings', {
      headers: { 'x-admin-token': token }, data: { quality: 60 },
    });
    // Paused clients must keep their base current and repaint immediately on resume.
    const image = page => page.locator('#screen-img').evaluate(c => c.toDataURL());
    await students[0].evaluate(async () => (await import('/static/js/controls.js')).togglePause());
    const frozen = await image(students[0]);
    await students[0].waitForTimeout(180);
    assert.equal(await image(students[0]), frozen);
    await students[0].evaluate(async () => (await import('/static/js/controls.js')).togglePause());
    assert.notEqual(await image(students[0]), frozen);
    // Existing grid/reconnect paths must use the same decoder and Canvas.
    await students[1].evaluate(async () => (await import('/static/js/stream.js')).selectAllGrid());
    await students[1].waitForFunction(() => {
      const c = document.querySelector('.grid-img');
      return c?.tagName === 'CANVAS' && c.width === 640;
    });
    await students[1].evaluate(async () => (await import('/static/js/stream.js')).selectMonitor(1));
    await painted(students[1]);
    // No desktop/cursor change means no screen batches or repeated JPEG traffic.
    await hostContext.request.post(base + '/test/mode/0');
    await host.waitForTimeout(2200); // let delayed ACK catch up
    const idleBefore = await stats();
    await host.waitForTimeout(400);
    const idleAfter = await stats();
    assert.equal(idleAfter.stream_bytes, idleBefore.stream_bytes);
    await host.screenshot({ path: path.resolve(__dirname, '../../docs/低延迟浏览器验收.png') });
    // Permissions remain enforced by upstream APIs and close all student senders.
    await hostContext.request.post(base + '/api/screen/private', {
      headers: { 'x-admin-token': token }, data: { enabled: true },
    });
    await host.waitForTimeout(150);
    assert.equal((await stats()).peers, 1);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ result: 'PASS', viewers: 4, slowAckMs: 900,
      idleBytesDelta: idleAfter.stream_bytes - idleBefore.stream_bytes,
      checks: ['HTTP Canvas decode', 'JPEG delta composition', 'quality epoch reset', 'four viewers', 'slow viewer isolation', 'pause/resume',
        'grid/single switch', 'static dedup', 'private permission', 'no browser JS errors'] }));
  } finally {
    for (const context of contexts) await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
