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

    await teacher.getByRole('link', { name: '新建题目' }).click();
    await teacher.getByLabel('标题').fill('输出整数');
    await teacher.getByLabel('题面').fill('读入并输出一个整数。');
    await teacher.getByRole('button', { name: '创建题目' }).click();
    await teacher.getByRole('link', { name: /^输出整数/ }).waitFor();

    async function createSheet(name, problemNames) {
      await teacher.getByRole('link', { name: '题单', exact: true }).click();
      await teacher.getByRole('link', { name: '新建题单' }).click();
      await teacher.getByLabel('标题').fill(name);
      for (const problemName of problemNames) {
        await teacher.getByLabel('选择题目').selectOption({ label: problemName });
        await teacher.getByRole('button', { name: '加入题目' }).click();
      }
      await teacher.getByLabel('创建时开放').check();
      await teacher.getByRole('button', { name: '创建题单' }).click();
      await teacher.getByRole('link', { name: name + ' 开放' }).waitFor();
    }
    await createSheet('第一课', ['两数求和']);
    await createSheet('第二课', ['两数求和', '输出整数']);
    await teacher.getByRole('link', { name: '第一课 历史' }).waitFor();
    await teacher.screenshot({ path: path.join(artifacts, 'oj-teacher.png') });

    const student = await browser.newPage({ viewport: { width: 360, height: 780 } });
    const sourceEditor = student.getByRole('textbox', { name: 'C++17 源码', exact: true });
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
    const openTile = student.getByRole('link', { name: '第二课 开放' });
    const historyTile = student.getByRole('link', { name: '第一课 历史' });
    await historyTile.waitFor();
    const [openBox, historyBox] = await Promise.all([openTile.boundingBox(), historyTile.boundingBox()]);
    assert.equal(openBox.y, historyBox.y);
    assert.ok(openBox.x < historyBox.x);
    await student.getByRole('link', { name: '第一课 历史' }).click();
    await student.getByRole('link', { name: /两数求和/ }).click();
    await student.getByRole('heading', { name: '样例输入' }).waitFor();
    assert.equal(await sourceEditor.count(), 0);
    assert.equal(await student.getByRole('button', { name: '进入在线调试' }).count(), 0);
    await student.getByRole('link', { name: '题单', exact: true }).click();
    await student.getByRole('link', { name: '第二课 开放' }).click();
    await student.getByRole('link', { name: /两数求和/ }).click();
    const sheetContext = student.getByRole('complementary', { name: '题单信息' });
    const problemPaper = student.locator('.problem-paper');
    const submissionPanel = student.getByRole('region', { name: '代码提交区域' });
    await submissionPanel.waitFor();
    const [paperBox, panelBox, contextBox] = await Promise.all([
      problemPaper.boundingBox(), submissionPanel.boundingBox(), sheetContext.boundingBox()
    ]);
    assert.equal(paperBox.x, panelBox.x);
    assert.equal(paperBox.width, panelBox.width);
    assert.ok(panelBox.y >= paperBox.y + paperBox.height);
    assert.ok(contextBox.x >= paperBox.x + paperBox.width);
    assert.equal(contextBox.y, paperBox.y);
    const sumProblem = sheetContext.getByRole('link', { name: /两数求和/ });
    assert.equal(await sumProblem.getAttribute('aria-current'), 'page');
    await sourceEditor.fill('int main() { return 0; }');
    await sheetContext.getByRole('link', { name: /输出整数/ }).click();
    await student.getByRole('heading', { name: '输出整数', exact: true }).waitFor();
    await sumProblem.click();
    await student.getByRole('heading', { name: '两数求和', exact: true }).waitFor();
    assert.equal(await sourceEditor.inputValue(), 'int main() { return 0; }');
    await teacher.getByRole('link', { name: '题库', exact: true }).click();
    await teacher.getByRole('link', { name: /^两数求和/ }).click();
    await teacher.getByLabel('样例输出').fill('3\n');
    await teacher.getByRole('button', { name: '保存新版本' }).click();
    await teacher.getByText('v2 · 100 分', { exact: true }).waitFor();
    await student.getByRole('button', { name: '提交评测' }).click();
    await student.getByRole('button', { name: '刷新题面' }).click();
    await student.getByRole('button', { name: '刷新题面' }).waitFor({ state: 'hidden' });
    assert.equal(await sourceEditor.inputValue(), 'int main() { return 0; }');
    await student.getByRole('button', { name: '提交评测' }).click();
    await student.getByText('100 / 100 分', { exact: true }).waitFor();
    await student.getByRole('button', { name: '提交评测' }).click();
    await student.getByText(/请在 \d+ 秒后重试/).waitFor();
    await student.getByRole('button', { name: '测试样例' }).click();
    await student.getByRole('heading', { name: '程序输出' }).waitFor();
    await student.getByRole('button', { name: '进入在线调试' }).click();
    const debug = student.getByRole('dialog', { name: '在线调试' });
    const debugEditor = debug.getByRole('textbox', { name: 'C++17 源码' });
    const debugViewport = student.viewportSize();
    assert.deepEqual(await debug.boundingBox(), { x: 0, y: 0, ...debugViewport });
    const [reader, editor, resultRow, toolbar] = await Promise.all([
      debug.locator('.debug-statement').boundingBox(), debug.locator('.debug-source').boundingBox(),
      debug.locator('.debug-data').boundingBox(), debug.locator('.debug-toolbar').boundingBox()
    ]);
    assert.ok(reader.width > debugViewport.width * .24 && reader.width < debugViewport.width * .29);
    assert.ok(reader.x + reader.width <= editor.x && reader.y === editor.y);
    assert.ok(Math.abs(editor.y + editor.height - resultRow.y) <= 1);
    assert.ok(Math.abs(resultRow.y + resultRow.height - toolbar.y) <= 1);
    const paneBoxes = await Promise.all((await debug.locator('.debug-pane').all()).map(pane => pane.boundingBox()));
    assert.equal(paneBoxes.length, 3);
    assert.ok(paneBoxes.every(pane => pane.y === resultRow.y && Math.abs(pane.width * 3 - resultRow.width) <= 1));
    await debug.locator('.debug-statement').getByText('输入两个整数，输出它们的和。', { exact: true }).waitFor();
    assert.equal(await debugEditor.inputValue(), 'int main() { return 0; }');
    const sampleInput = debug.getByRole('textbox', { name: '样例输入' });
    assert.equal(await sampleInput.inputValue(), '1 2');
    assert.equal(await sampleInput.isEditable(), false);
    await debug.locator('.debug-pane').nth(1).getByText('3', { exact: true }).waitFor();
    const exampleCode = [
      '#include <iostream>', '', 'int main() {', '    // 读取两个整数', '    int left = 0, right = 0;',
      '    std::cin >> left >> right;', '    std::cout << "<b>sum</b>: " << left + right << \'\\n\';',
      '    return 0;', '}'
    ].join('\n');
    await debugEditor.fill(exampleCode);
    const debugSyntax = debug.locator('.editor-syntax');
    assert.equal(await debugSyntax.textContent(), exampleCode);
    for (const [kind, token] of Object.entries({
      directive: '#include <iostream>', type: 'int', comment: '// 读取两个整数', number: '0', string: '"<b>sum</b>: "', keyword: 'return'
    })) {
      const span = debugSyntax.locator(`.syntax-${kind}`).getByText(token, { exact: true }).first();
      await span.waitFor();
      assert.notEqual(await span.evaluate(node => getComputedStyle(node).color), await debugSyntax.evaluate(node => getComputedStyle(node).color));
    }
    assert.equal(await debugSyntax.locator('b').count(), 0);
    await student.screenshot({ path: path.join(artifacts, 'oj-debug.png') });
    const longCode = '/* block\ncomment */\n' + 'auto text = R"tag(raw\ntext)tag";\n' + `// ${'x'.repeat(400)}\n`.repeat(85);
    await debugEditor.fill(longCode);
    assert.equal(await debugSyntax.locator('.syntax-comment').first().textContent(), '/* block\ncomment */');
    assert.equal(await debugSyntax.locator('.syntax-string').textContent(), 'R"tag(raw\ntext)tag"');
    await debugEditor.evaluate(input => { input.scrollTop = input.scrollHeight; input.scrollLeft = input.scrollWidth; });
    await student.waitForFunction(() => {
      const input = document.getElementById('debug-source');
      const syntax = input.previousElementSibling;
      return input.scrollTop > 0 && input.scrollLeft > 0 && Math.abs(input.scrollTop - syntax.scrollTop) <= 1
        && Math.abs(input.scrollLeft - syntax.scrollLeft) <= 1;
    });
    await debugEditor.fill('int main() { return 0; }');
    await debug.getByRole('button', { name: '在线运行' }).click();
    await debug.locator('.debug-result').getByText('通过', { exact: true }).waitFor();
    const customInput = debug.getByRole('textbox', { name: '自定义输入' });
    await debug.getByRole('button', { name: '自定义输入' }).click();
    await customInput.fill('7 9');
    await debug.getByRole('button', { name: '题目样例' }).click();
    assert.equal(await sampleInput.inputValue(), '1 2');
    await debug.getByRole('button', { name: '自定义输入' }).click();
    assert.equal(await customInput.inputValue(), '7 9');
    await debugEditor.fill('int main() {\n  return 1;\n}');
    assert.equal(await debug.locator('.debug-line-numbers').textContent(), '1\n2\n3');
    await debug.getByRole('button', { name: '在线运行' }).click();
    await debug.getByText('运行完成', { exact: true }).waitFor();
    await debug.getByText('7 9', { exact: true }).waitFor();
    await debug.getByRole('button', { name: '提交评测' }).click();
    await debug.getByText(/请在 \d+ 秒后重试/).waitFor();
    await debug.getByRole('button', { name: '返回题目详情' }).click();
    assert.equal(await sourceEditor.inputValue(), 'int main() {\n  return 1;\n}');
    const mainSyntax = submissionPanel.locator('.code-panel .editor-syntax');
    assert.equal(await mainSyntax.locator('.syntax-keyword').textContent(), 'return');
    assert.equal(await mainSyntax.locator('.syntax-number').textContent(), '1');
    await student.evaluate(() => window.scrollTo(0, 0));
    await student.screenshot({ path: path.join(artifacts, 'oj-student.png'), fullPage: true });
    await student.setViewportSize({ width: 360, height: 780 });
    assert.equal(await student.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const [mobilePanel, mobileContext] = await Promise.all([submissionPanel.boundingBox(), sheetContext.boundingBox()]);
    assert.equal(mobilePanel.x, mobileContext.x);
    assert.ok(mobileContext.y >= mobilePanel.y + mobilePanel.height);
    await sourceEditor.fill(longCode);
    await sourceEditor.evaluate(input => { input.scrollTop = input.scrollHeight; });
    await student.waitForFunction(() => {
      const input = document.getElementById('source');
      const syntax = input.previousElementSibling;
      return input.scrollTop > 0 && input.scrollWidth === input.clientWidth && Math.abs(input.scrollTop - syntax.scrollTop) <= 1;
    });
    await sourceEditor.fill('int main() {\n  return 1;\n}');
    await student.screenshot({ path: path.join(artifacts, 'oj-mobile.png'), fullPage: true });
    await student.getByRole('button', { name: '进入在线调试' }).click();
    assert.deepEqual(await debug.boundingBox(), { x: 0, y: 0, width: 360, height: 780 });
    const [mobileReader, mobileEditor] = await Promise.all([
      debug.locator('.debug-statement').boundingBox(), debug.locator('.debug-source').boundingBox()
    ]);
    assert.equal(mobileReader.x, mobileEditor.x);
    assert.ok(Math.abs(mobileReader.y + mobileReader.height - mobileEditor.y) <= 1);
    await student.keyboard.press('Escape');
    await student.getByRole('link', { name: '我的提交' }).click();
    await student.getByRole('link', { name: /两数求和.*评测/ }).click();
    await student.getByText('int main() { return 0; }', { exact: true }).waitFor();

    await teacher.getByRole('link', { name: '提交记录' }).click();
    await teacher.getByRole('link', { name: /两数求和.*Ada.*评测/ }).click();
    await teacher.getByRole('link', { name: '题目版本 v2' }).click();
    await teacher.getByText('1100', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: browser OJ management, login, history, editor, submission and version');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
