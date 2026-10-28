/* Discussion controls in actual teacher/student browsers; synthetic screen only. */
const assert = require('node:assert/strict');
const path = require('node:path');
require('node:fs').mkdirSync(path.resolve(__dirname, '../.artifacts/browser'), { recursive: true });
const { chromium } = require(process.env.CLASSTREAM_PLAYWRIGHT || 'playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const base = process.env.CLASSTREAM_TEST_URL || 'http://127.0.0.1:18765';
  const errors = [];
  try {
    const hostContext = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    const host = await hostContext.newPage();
    host.on('pageerror', error => errors.push(error.message));
    await host.goto(base + '/?host=fixture');
    await host.locator('#admin-password').fill('fixture-password');
    await host.locator('#admin-submit-btn').click();
    await host.locator('#admin-modal').waitFor({ state: 'hidden' });
    await host.locator('#discussion-mute-all').waitFor();
    const headers = { 'x-admin-token': await host.evaluate(() => localStorage.getItem('pystream_admin_token')) };
    await hostContext.request.post(base + '/api/session/new', { headers, data: { name: 'Discussion test' } });
    const students = [];
    for (let i = 0; i < 2; i++) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base + '/class');
      await page.waitForFunction(() => document.getElementById('identity-btn').textContent.startsWith('小'));
      assert.equal(await page.locator('#chat-panel').isVisible(), true);
      assert.equal(await page.locator('#discussion-mute-all').isVisible(), false);
      students.push(page);
    }
    const [first, second] = students;
    const name = await first.locator('#identity-btn').innerText();
    assert.equal(await host.locator('#discussion-member-settings').isVisible(), false);
    assert.equal(await host.locator('#discussion-mute-all').getAttribute('aria-checked'), 'false');
    assert.equal(await host.locator('#discussion-status').innerText(), '学员可自由发言');
    await host.locator('#discussion-member-open').click();
    await host.locator('#discussion-member-search').fill('不存在的学员');
    assert.equal(await host.locator('#discussion-member-list').innerText(), '没有匹配的学员');
    await host.locator('#discussion-member-search').fill(name);
    await host.getByRole('button', { name: '禁言：' + name, exact: true }).click();
    await first.waitForFunction(() => document.getElementById('chat-input').disabled);
    assert.equal(await second.locator('#chat-input').isDisabled(), false);
    assert.equal(await host.locator('#chat-input').isDisabled(), false);
    for (const id of ['chat-send-btn', 'chat-file-btn', 'chat-code-btn', 'chat-code-input', 'chat-code-send', 'chat-emoji-btn'])
      assert.equal(await first.locator('#' + id).isDisabled(), true, id);
    await first.reload();
    await first.waitForFunction(() => document.getElementById('chat-input').disabled);
    assert.equal(await first.locator('#identity-btn').innerText(), name);
    await host.locator('#discussion-member-close').click();
    await host.locator('#discussion-mute-all').click();
    await second.waitForFunction(() => document.getElementById('chat-input').disabled);
    assert.match(await second.locator('#discussion-status').innerText(), /全员禁言/);
    await host.locator('#chat-input').fill('教师在全体禁言期间仍可发言');
    await host.locator('#chat-input').press('Enter');
    await second.locator('.msg-content').filter({ hasText: '教师在全体禁言期间仍可发言' }).last().waitFor();
    await host.locator('#discussion-mute-all').click();
    await second.waitForFunction(() => !document.getElementById('chat-input').disabled);
    assert.equal(await first.locator('#chat-input').isDisabled(), true);
    await host.locator('#discussion-member-open').click();
    await host.locator('[data-filter="muted"]').click();
    assert.equal(await host.locator('.discussion-muted-badge').innerText(), '已禁言');
    await host.getByRole('button', { name: '解除禁言：' + name, exact: true }).click();
    await first.waitForFunction(() => !document.getElementById('chat-input').disabled);
    await first.locator('#chat-input').fill('解除后恢复发言');
    await first.locator('#chat-input').press('Enter');
    await host.locator('.msg-content').filter({ hasText: '解除后恢复发言' }).last().waitFor();
    await host.locator('#discussion-member-close').click();
    await host.route('**/api/discussion', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false}' }));
    await host.locator('#discussion-mute-all').click();
    await host.waitForFunction(() => document.getElementById('discussion-error').textContent.includes('设置失败'));
    assert.equal(await host.locator('#discussion-mute-all').getAttribute('aria-checked'), 'false');
    await host.unroute('**/api/discussion');
    await first.setViewportSize({ width: 390, height: 844 });
    assert.equal(await first.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await host.setViewportSize({ width: 390, height: 844 });
    assert.equal(await host.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await host.locator('#discussion-member-open').click();
    await host.locator('[data-filter="all"]').click();
    await host.getByRole('button', { name: '禁言：' + name, exact: true }).click();
    await first.waitForFunction(() => document.getElementById('chat-input').disabled);
    await first.screenshot({ path: path.resolve(__dirname, '../.artifacts/browser/discussion-student-muted.png') });
    assert.equal(await host.locator('#discussion-member-settings').evaluate(el => el.scrollWidth <= el.clientWidth), true);
    await host.screenshot({ path: path.resolve(__dirname, '../.artifacts/browser/discussion-teacher-members.png') });
    await host.keyboard.press('Escape');
    assert.equal(await host.locator('#discussion-member-settings').isVisible(), false);
    await host.screenshot({ path: path.resolve(__dirname, '../.artifacts/browser/discussion-teacher-controls.png') });
    await hostContext.request.post(base + '/api/session/new', { headers, data: { name: 'Next discussion test' } });
    await host.waitForFunction(() => document.querySelectorAll('#discussion-member-list button[aria-pressed=true]').length === 0);
    assert.deepEqual(errors, []);
    console.log('PASS: default open; teacher-only controls; individual/all mute and release; disabled inputs; refresh stability; teacher messages; failure recovery; new classroom reset; 390px layout; no JS errors.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
