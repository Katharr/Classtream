/* Synthetic fixture only; no live classroom or desktop capture. */
const assert = require('node:assert/strict');
const { chromium } = require(process.env.CLASSTREAM_PLAYWRIGHT || 'playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    const base = (process.env.CLASSTREAM_TEST_URL || 'http://127.0.0.1:18765');
    for (const teacher of [true, false]) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      if (teacher) {
        const login = await context.request.post(base + '/api/admin/login', {
          data: { username: 'fixture', password: 'fixture-password' },
        });
        const { token } = await login.json();
        assert.ok(token);
        await context.addInitScript(t => localStorage.setItem('pystream_admin_token', t), token);
      }
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base + (teacher ? '/?host=admin' : '/class'));
      await page.waitForFunction(() => document.getElementById('screen-img').width === 640);
      const translation = () => page.locator('#screen-img').evaluate(el => {
        const values = (el.style.translate || '0px').split(' ').map(parseFloat);
        return [values[0], values[1] || 0];
      });
      const drag = async (dx, dy, button = 'left') => {
        const box = await page.locator('#screen-area').boundingBox();
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await page.mouse.down({ button });
        await page.mouse.move(box.x + box.width / 2 + dx, box.y + box.height / 2 + dy, { steps: 5 });
        await page.mouse.up({ button });
      };
      const zoomClick = async id => {
        await page.locator(id).click();
      };
      await drag(30, 30);
      assert.deepEqual(await translation(), [0, 0], 'normal size stays centered');
      for (let i = 0; i < 8; i++) await zoomClick('#btn-zoom-in');
      await page.waitForTimeout(150);
      await drag(60, 45);
      const moved = await translation();
      assert.ok(moved[0] > 0 && moved[1] > 0, 'left drag pans both axes');
      await drag(-30, -20, 'right');
      assert.deepEqual(await translation(), moved, 'right click does not pan');
      await page.keyboard.press('Escape'); // Dismiss a possible native context menu.
      await drag(-35, -25);
      assert.ok((await translation())[0] < moved[0], 'reverse drag moves back');
      await drag(5000, 5000);
      const bounded = await translation();
      assert.ok(bounded.every(value => value >= 0 && value < 1500), 'large drag clamps at edges');
      assert.equal(await page.locator('#screen-area').evaluate(el => el.classList.contains('panning')), false);
      await page.setViewportSize({ width: 1600, height: 1000 });
      await page.waitForTimeout(150);
      assert.ok((await translation()).every(Number.isFinite));
      await zoomClick('#btn-zoom-reset');
      await page.waitForFunction(() => !document.getElementById('screen-area').classList.contains('zoomed'));
      assert.deepEqual(await translation(), [0, 0]);
      await zoomClick('#btn-zoom-in');
      await page.locator('#screen-area').click();
      await page.evaluate(() => document.activeElement.blur());
      await page.keyboard.press('0');
      await page.waitForFunction(() => !document.getElementById('screen-area').classList.contains('zoomed'));
      assert.deepEqual(await translation(), [0, 0], 'keyboard reset also centers');
      // Keep the teacher connected while the student receives the fixture stream.
    }
    assert.deepEqual(errors, []);
    console.log('PASS: teacher/student zoom panning, bounds, resize, mouse buttons and reset');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
