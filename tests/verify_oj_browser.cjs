/* Teacher and learner flows through the standalone OJ in Edge. */
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require(process.env.CLASSTREAM_PLAYWRIGHT || 'playwright');
const artifacts = path.resolve(__dirname, '../.artifacts/browser');

(async () => {
  fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const base = process.env.CLASSTREAM_TEST_URL || 'http://127.0.0.1:18765';
  const errors = [];
  try {
    const teacher = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    teacher.on('pageerror', error => errors.push(error.message));
    await teacher.goto(base + '/teacher');
    await teacher.getByRole('heading', { name: '教师首页' }).waitFor();
    await teacher.screenshot({ path: path.join(artifacts, 'teacher-home.png') });
    await teacher.getByRole('link', { name: '课堂直播', exact: true }).click();
    assert.equal(teacher.url(), base + '/?host=admin');
    assert.equal(await teacher.locator('#screen-img').count(), 1);
    await teacher.goBack();
    await teacher.getByRole('link', { name: '编程 OJ', exact: true }).click();
    await teacher.getByLabel('用户名').fill('fixture');
    await teacher.getByLabel('密码', { exact: true }).fill('fixture-password');
    await teacher.getByRole('button', { name: '登录' }).click();
    await teacher.getByRole('link', { name: '学员' }).click();
    await teacher.getByLabel('用户名').fill('Ada');
    await teacher.getByRole('button', { name: '添加学员' }).click();
    await teacher.getByRole('button', { name: '重置密码' }).waitFor();
    const password = await teacher.locator('.roster-password code').innerText();

    await teacher.getByRole('link', { name: '题库', exact: true }).click();
    await teacher.getByRole('link', { name: '新建题目' }).click();
    await teacher.getByLabel('标题').fill('两数求和');
    await teacher.getByLabel('题面').fill('输入两个整数，输出它们的和。');
    await teacher.getByLabel('样例输入').fill('1 2');
    await teacher.getByLabel('样例输出').fill('3');
    await teacher.getByRole('button', { name: '添加数据组' }).click();
    await teacher.getByRole('group', { name: '数据组 1' }).getByLabel('分数').fill('10');
    await teacher.getByRole('group', { name: '数据组 2' }).getByLabel('标准输出').fill('1100');
    await teacher.getByRole('button', { name: '创建题目' }).click();
    await teacher.getByRole('link', { name: /^两数求和/ }).waitFor();

    async function createSheet(name) {
      await teacher.getByRole('link', { name: '题单', exact: true }).click();
      await teacher.getByRole('link', { name: '新建题单' }).click();
      await teacher.getByLabel('标题').fill(name);
      await teacher.getByLabel('选择题目').selectOption({ label: '两数求和' });
      await teacher.getByRole('button', { name: '加入题目' }).click();
      await teacher.getByLabel('创建时开放').check();
      await teacher.getByRole('button', { name: '创建题单' }).click();
      await teacher.getByRole('link', { name: name + ' 开放' }).waitFor();
    }
    await createSheet('第一课');
    await createSheet('第二课');
    await teacher.getByRole('link', { name: '第一课 历史' }).waitFor();
    await teacher.screenshot({ path: path.join(artifacts, 'oj-teacher.png') });

    const student = await browser.newPage({ viewport: { width: 360, height: 780 } });
    student.on('pageerror', error => errors.push(error.message));
    await student.goto(base + '/');
    await student.getByRole('heading', { name: '学生首页' }).waitFor();
    assert.equal(await student.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await student.screenshot({ path: path.join(artifacts, 'student-home-mobile.png') });
    await student.setViewportSize({ width: 1280, height: 900 });
    await student.getByRole('link', { name: '编程 OJ', exact: true }).click();
    await student.getByLabel('用户名').fill('Ada');
    await student.getByLabel('密码', { exact: true }).fill(password);
    await student.getByRole('button', { name: '登录' }).click();
    await student.getByRole('link', { name: '第一课 历史' }).click();
    await student.getByRole('link', { name: /两数求和/ }).click();
    await student.getByRole('heading', { name: '样例输入' }).waitFor();
    assert.equal(await student.getByLabel('C++17 源码').count(), 0);
    await student.getByRole('link', { name: '题单', exact: true }).click();
    await student.getByRole('link', { name: '第二课 开放' }).click();
    await student.getByRole('link', { name: /两数求和/ }).click();
    await student.getByLabel('C++17 源码').fill('int main() { return 0; }');
    await teacher.getByRole('link', { name: '题库', exact: true }).click();
    await teacher.getByRole('link', { name: /^两数求和/ }).click();
    await teacher.getByLabel('样例输出').fill('3\n');
    await teacher.getByRole('button', { name: '保存新版本' }).click();
    await teacher.getByText('v2 · 100 分', { exact: true }).waitFor();
    await student.getByRole('button', { name: '提交评测' }).click();
    await student.getByRole('button', { name: '刷新题面' }).click();
    await student.getByRole('button', { name: '刷新题面' }).waitFor({ state: 'hidden' });
    assert.equal(await student.getByLabel('C++17 源码').inputValue(), 'int main() { return 0; }');
    await student.getByRole('button', { name: '提交评测' }).click();
    await student.getByText('100 / 100 分', { exact: true }).waitFor();
    await student.getByRole('button', { name: '测试样例' }).click();
    await student.getByText(/请在 \d+ 秒后重试/).waitFor();
    await student.screenshot({ path: path.join(artifacts, 'oj-student.png') });
    await student.setViewportSize({ width: 360, height: 780 });
    assert.equal(await student.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await student.screenshot({ path: path.join(artifacts, 'oj-mobile.png'), fullPage: true });
    await student.getByRole('link', { name: '我的提交' }).click();
    await student.getByRole('link', { name: /两数求和/ }).click();
    await student.getByText('int main() { return 0; }', { exact: true }).waitFor();

    await teacher.getByRole('link', { name: '提交记录' }).click();
    await teacher.getByRole('link', { name: /两数求和.*Ada/ }).click();
    await teacher.getByRole('link', { name: '题目版本 v2' }).click();
    await teacher.getByText('1100', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: browser OJ management, login, history, editor, submission and version');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
