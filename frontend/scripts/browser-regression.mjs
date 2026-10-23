// Real Chromium + production Next UI; synthetic API responses, no provider/SMTP/device claim.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');
const base = process.env.UI_TEST_URL || 'http://127.0.0.1:3100';
assert.equal(new URL(base).hostname, '127.0.0.1', 'Only a disposable loopback server is permitted');
const output = process.env.UI_TEST_OUTPUT || '/tmp/learning-ui-regression';
fs.mkdirSync(output, { recursive: true });
const user = { id: 'synthetic-browser-user', email: 'synthetic@example.invalid', display_name: 'Synthetic Learner' };
const quiz = [1, 2].map((n) => ({ question_id: `original-${n}`, question: `Original synthetic question ${n}: 1 + ${n}?`,
  question_type: 'single_choice', options: ['A', 'B', 'C', 'D'].map((key, i) => ({ key, text: `Original option ${i + 1}` })),
  correct_option: 'B', explanation: 'Original synthetic arithmetic fixture.', knowledge_point: 'Synthetic arithmetic', notebook_id: 'data-structure' }));
const signature = (items) => items.map((q) => `${q.question_id}:${q.question}:${q.correct_option}`).join('|');
const errors = [];
const results = [];

async function setup(browser, name, viewport, authenticated = true) {
  const context = await browser.newContext({ viewport, recordVideo: { dir: path.join(output, 'videos') } });
  const setSyntheticCookie = () => context.addCookies([{ name: 'la_access_token', value: 'synthetic-ui-only-not-a-jwt', url: base, httpOnly: true, sameSite: 'Lax' }]);
  if (authenticated) await setSyntheticCookie();
  let signedIn = authenticated;
  let dashboardCalls = 0;
  let latestCalls = 0;
  await context.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    let body;
    let status = 200;
    if (pathname.endsWith('/auth/me')) { status = signedIn ? 200 : 401; body = signedIn ? { user } : { detail: 'Synthetic signed-out fixture' }; }
    else if (pathname.endsWith('/auth/login')) { signedIn = true; await setSyntheticCookie(); body = { user }; }
    else if (pathname.endsWith('/auth/logout')) { signedIn = false; await context.clearCookies(); body = {}; }
    else if (pathname.endsWith('/auth/refresh')) { status = 401; body = {}; }
    else if (pathname.endsWith('/subjects')) body = [];
    else if (pathname.endsWith('/profile')) body = { ...user, display_name: 'Synthetic Profile' };
    else if (pathname.endsWith('/quiz/latest')) { latestCalls++; body = { quiz_items: [] }; }
    else if (pathname.endsWith('/practice/recommendations')) body = { items: [] };
    else if (pathname.endsWith('/learning-center')) {
      dashboardCalls++;
      status = dashboardCalls === 1 ? 503 : 200;
      body = status === 503 ? { detail: 'Synthetic retry fixture' } : { subjects: [], next_move: null };
    }
    else if (pathname.endsWith('/memory')) body = { weak_points: [], error_count: {}, recent_topics: [], last_session: '' };
    else if (pathname.endsWith('/sessions')) body = [];
    else if (pathname.endsWith('/chat')) {
      return route.fulfill({ contentType: 'text/event-stream', body:
        'event: reasoning_delta\ndata: {"delta":"Synthetic test trace; not a real model response."}\n\n' +
        'event: answer_delta\ndata: {"delta":"Synthetic answer for UI regression."}\n\n' +
        'event: done\ndata: {}\n\n' });
    } else body = {};
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(`${name}: ${e.message}`));
  page.on('console', (m) => { if (/hydration|didn't match|did not match/i.test(m.text())) errors.push(`${name}: ${m.text()}`); });
  return { context, page, latestCalls: () => latestCalls };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const [size, viewport] of Object.entries({ mobile: { width: 390, height: 844 }, desktop: { width: 1280, height: 900 } })) {
      let test = await setup(browser, `${size}-auth`, viewport, false);
      await test.page.goto(`${base}/login?next=${encodeURIComponent('/\\evil.invalid')}`);
      await test.page.getByPlaceholder('you@example.com').fill(user.email);
      await test.page.getByPlaceholder('至少 8 位').fill('Synthetic-Only-123!');
      await test.page.getByRole('button', { name: '立即登录' }).click();
      await test.page.waitForURL(`${base}/chat`);
      await test.page.getByPlaceholder('输入你的问题...').fill('Synthetic test request');
      await test.page.getByRole('button', { name: '发送', exact: true }).click();
      const panel = test.page.getByRole('button', { name: '收起处理过程' });
      await panel.waitFor();
      await panel.click();
      await test.page.getByPlaceholder('输入你的问题...').fill('Manual collapse must survive rerenders');
      await test.page.getByRole('button', { name: '展开处理过程' }).waitFor();
      await test.page.screenshot({ path: path.join(output, `${size}-chat.png`), fullPage: true });
      const stored = await test.page.evaluate(() => JSON.stringify(localStorage));
      assert.ok(!stored.includes('Synthetic test trace'), 'Ephemeral trace must not persist');
      await test.context.close();
      results.push(`${size}: safe redirect, streamed trace disclosure, manual collapse, ephemeral cache`);

      test = await setup(browser, `${size}-practice`, viewport);
      await test.context.addInitScript(({ quiz, signature, userId }) => {
        if (localStorage.getItem('synthetic_fixture_seeded')) return;
        localStorage.setItem('synthetic_fixture_seeded', 'true');
        localStorage.setItem('learning_active_user_id', 'another-synthetic-user');
        localStorage.setItem(`learning_quiz:${userId}`, JSON.stringify(quiz));
        localStorage.setItem(`learning_practice_state:${userId}`, JSON.stringify({ quizSignature: signature,
          quizItemCount: 1, currentIndex: 0, selectedOption: 'B', showHint: false, feedback: null,
          sessionId: '', notebookId: 'data-structure', isCompleted: true, updatedAt: 1 }));
      }, { quiz, signature: signature(quiz.slice(0, 1)), userId: user.id });
      await test.page.goto(`${base}/practice`);
      await test.page.getByRole('heading', { name: '第 2 题 / 共 2 题' }).waitFor();
      assert.equal(test.latestCalls(), 0, 'Cached own-user practice must restore without remote replacement');
      await test.page.getByRole('button', { name: 'B Original option 2', exact: true }).click();
      await test.page.screenshot({ path: path.join(output, `${size}-practice.png`), fullPage: true });
      await test.page.waitForFunction((userId) => JSON.parse(localStorage.getItem(`learning_practice_state:${userId}`) || '{}').selectedOption === 'B', user.id);
      await test.page.reload();
      await test.page.getByRole('heading', { name: '第 2 题 / 共 2 题' }).waitFor();
      await test.context.close();
      results.push(`${size}: account-scoped cached practice, appended-question resume, reload`);

      test = await setup(browser, `${size}-profile-dashboard`, viewport);
      await test.page.goto(`${base}/profile`);
      await test.page.getByRole('heading', { name: 'Synthetic Profile' }).waitFor();
      await test.page.goto(`${base}/dashboard`);
      await test.page.getByRole('button', { name: '重试', exact: true }).click();
      await test.page.getByRole('button', { name: '重试', exact: true }).waitFor({ state: 'hidden' });
      await test.page.screenshot({ path: path.join(output, `${size}-dashboard.png`), fullPage: true });
      await test.context.close();
      results.push(`${size}: profile fetch, failed dashboard load and retry`);
    }
    assert.deepEqual(errors, [], 'No browser runtime or hydration errors');
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ scope: 'Real Chromium/Next UI, synthetic API; no physical device or external provider', results }, null, 2));
    console.log(JSON.stringify({ passed: results.length, results }));
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
