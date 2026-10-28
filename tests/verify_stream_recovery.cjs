/* Real Edge + loopback WebSockets. Drop application messages, never touch LAN. */
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require(process.env.CLASSTREAM_PLAYWRIGHT || 'playwright');

(async () => {
  const base = (process.env.CLASSTREAM_TEST_URL || 'http://127.0.0.1:18765');
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const contexts = [], errors = [], results = {};
  const phase = page => page.locator('#conn-state').getAttribute('data-phase');
  const waitPhase = (page, value, timeout = 10000) => page.waitForFunction(
    value => document.getElementById('conn-state').dataset.phase === value, value, { timeout });
  try {
    const hostContext = await browser.newContext(); contexts.push(hostContext);
    const { token } = await (await hostContext.request.post(base + '/api/admin/login', {
      data: { username: 'fixture', password: 'fixture-password' },
    })).json();
    const headers = { 'x-admin-token': token };
    await hostContext.request.post(base + '/api/screen/private', { headers, data: { enabled: false } });
    await hostContext.request.post(base + '/api/screen/freeze', { headers, data: { enabled: false } });
    await hostContext.request.post(base + '/api/screen/permissions', { headers, data: { monitor_id: 1, access: 'all' } });
    await hostContext.request.post(base + '/test/mode/0');
    await hostContext.request.post(base + '/test/health/capture/1');
    await hostContext.request.post(base + '/test/health/heartbeat/1');
    await hostContext.addInitScript(t => localStorage.setItem('pystream_admin_token', t), token);
    const host = await hostContext.newPage();
    host.on('pageerror', e => errors.push(e.message));
    await host.goto(base + '/?host=fixture'); await waitPhase(host, 'live');

    const students = [];
    let blackhole = false, attempts = 0;
    for (let i = 0; i < 4; i++) {
      const context = await browser.newContext(); contexts.push(context);
      await context.addInitScript(name => localStorage.setItem('pystream_name', name), 'Repair viewer ' + i);
      if (i === 0) await context.routeWebSocket(/\/ws\/\d+\?/, route => {
        attempts++;
        const upstream = route.connectToServer();
        upstream.onMessage(message => { if (!blackhole) route.send(message); });
      });
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(base + '/class'); await waitPhase(page, 'live'); students.push(page);
    }
    // Static desktop: heartbeat remains, no binary update is required for health.
    await host.waitForTimeout(3500);
    assert.deepEqual(await Promise.all(students.map(phase)), ['live', 'live', 'live', 'live']);

    const beforeAttempts = attempts, started = performance.now();
    blackhole = true;
    await waitPhase(students[0], 'interrupted', 4000);
    results.blackholeNoticeMs = Math.round(performance.now() - started);
    assert.ok(results.blackholeNoticeMs <= 3600);
    assert.deepEqual(await Promise.all(students.slice(1).map(phase)), ['live', 'live', 'live']);
    await waitPhase(students[0], 'reconnecting', 3500);
    results.blackholeReconnectMs = Math.round(performance.now() - started);
    const unblocked = performance.now();
    blackhole = false;
    await waitPhase(students[0], 'live');
    results.recoveredAfterUnblockMs = Math.round(performance.now() - unblocked);
    assert.ok(attempts > beforeAttempts);

    // An unavailable capture source still sends metadata; avoid pointless retries.
    const afterRecoveryAttempts = attempts;
    await hostContext.request.post(base + '/test/health/capture/0');
    await Promise.all(students.map(page => waitPhase(page, 'source', 5000)));
    await host.waitForTimeout(2500);
    assert.equal(attempts, afterRecoveryAttempts);
    await hostContext.request.post(base + '/test/health/capture/1');
    await Promise.all(students.map(page => waitPhase(page, 'live')));

    await hostContext.request.post(base + '/api/screen/freeze', { headers, data: { enabled: true } });
    await Promise.all(students.map(page => waitPhase(page, 'frozen')));
    assert.equal(await phase(host), 'live', 'teacher preview stays live while students freeze');
    await host.waitForTimeout(3500);
    assert.equal(attempts, afterRecoveryAttempts);
    await hostContext.request.post(base + '/api/screen/freeze', { headers, data: { enabled: false } });
    await Promise.all(students.map(page => waitPhase(page, 'live')));

    await students[1].evaluate(async () => (await import('/static/js/controls.js')).togglePause());
    await waitPhase(students[1], 'paused');
    await host.waitForTimeout(3500); assert.equal(await phase(students[1]), 'paused');
    await students[1].evaluate(async () => (await import('/static/js/controls.js')).togglePause());
    await waitPhase(students[1], 'live');

    // Every recovered framebuffer must converge to the new content.
    await hostContext.request.post(base + '/test/color/200');
    await Promise.all(students.map(page => page.waitForFunction(() => {
      const p = document.getElementById('screen-img').getContext('2d').getImageData(290, 290, 1, 1).data;
      return p[0] > 170 && p[1] < 30;
    })));
    const output = path.resolve(__dirname, '../.artifacts/browser/stream-recovery');
    fs.mkdirSync(output, { recursive: true });
    await students[0].screenshot({ path: path.join(output, '恢复后的学生画面.png') });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ result: 'PASS', students: 4, ...results,
      checks: ['static health', 'one-way application blackhole', 'other three stay live',
        'automatic reconnect', 'source failure without reconnect loop', 'freeze status',
        'teacher preview', 'pause/resume', 'all four framebuffers converge', 'no JS errors'] }));
  } finally {
    for (const context of contexts) await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
