import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { analyzeTransactions, validAiAnalysis } from '../src/api.js';
import { createAnalysisRequest } from '../src/aiAnalysisRequest.js';
import { submissionGate } from '../src/transactionForm.js';

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const result = { period_start: '2026-10-25', period_end: '2026-11-23', currency: 'UAH', transaction_count: 3,
  total_income: '1000.00', total_expense: '250.00', balance: '750.00', summary: 'Підсумок записів.',
  top_expense_categories: [{ category: 'Їжа', amount: '250.00', share_percent: '100.00' }],
  risks: ['Ризик неповного обліку.'], advice: ['Перевірте записи.'] };

test('AI POST has only per-request Bearer, no body/key/cookies, and accepts the actual contract', async () => {
  let calls = 0;
  globalThis.fetch = async (url, options) => {
    calls++;
    assert.equal(url, '/api/ai/analyze-transactions');
    assert.equal(options.method, 'POST');
    assert.deepEqual(options.headers, { Authorization: 'Bearer synthetic-admin' });
    assert.equal(options.body, undefined);
    assert.equal(options.credentials, 'omit');
    assert.equal(options.redirect, 'error');
    assert.equal(options.cache, 'no-store');
    return Response.json(result);
  };
  assert.deepEqual(await analyzeTransactions('synthetic-admin'), result);
  assert.equal(calls, 1);
});

for (const status of [401, 403, 429, 502, 503, 504, 500]) test(`safe AI error ${status}, no automatic retries`, async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({ detail: 'private-secret' }, { status, headers: { 'Retry-After': '90' } }); };
  await assert.rejects(analyzeTransactions('synthetic-admin'), (error) => {
    assert.equal(error.status, status);
    assert.ok(!error.message.includes('private-secret'));
    if (status === 429) assert.match(error.message, /90 с/);
    return true;
  });
  assert.equal(calls, 1);
});

test('AI validates dates, currency, text bounds, amounts, count, shares and list shape', async () => {
  assert.equal(validAiAnalysis(result), true);
  const invalid = [{ currency: 'USD' }, { period_end: '2026-02-30' }, { period_start: '2027-01-01' },
    { total_income: 1000 }, { total_expense: '-1.00' }, { balance: '1e3' }, { summary: '' },
    { transaction_count: -1 }, { risks: ['x'.repeat(501)] }, { advice: ['x', 'x', 'x', 'x', 'x', 'x'] },
    { top_expense_categories: [{ category: 'X', amount: '1.00', share_percent: '100.01' }] }];
  for (const change of invalid) {
    assert.equal(Boolean(validAiAnalysis({ ...result, ...change })), false);
    globalThis.fetch = async () => Response.json({ ...result, ...change });
    await assert.rejects(analyzeTransactions('secret'), /контракту/);
  }
  globalThis.fetch = async () => new Response('private-bad-json');
  await assert.rejects(analyzeTransactions('secret'), /некоректну/);
  globalThis.fetch = async () => { throw new Error('private-network'); };
  await assert.rejects(analyzeTransactions('secret'), (error) => !error.message.includes('private-network'));
});

test('manual controller starts no requests until click; prevents double click and shares admin gate', async () => {
  const request = createAnalysisRequest();
  let resolve; let calls = 0; const states = [];
  globalThis.fetch = async () => { calls++; return new Promise((done) => { resolve = () => done(Response.json(result)); }); };
  const gate = submissionGate();
  const options = { password: 'secret', revision: 3, runAdmin: gate, onState: (state) => states.push(state), onUnauthorized() {} };
  assert.equal(calls, 0);
  assert.equal(await request.start({ ...options, password: '' }), false);
  assert.equal(await request.start({ ...options, pending: true }), false);
  const first = request.start(options);
  assert.equal(states[0].status, 'loading');
  assert.equal(await request.start(options), false);
  assert.equal(await gate(async () => assert.fail('must exclude concurrent writes')), false);
  resolve(); await first;
  assert.equal(calls, 1);
  assert.equal(states[1].status, 'ready');
  assert.equal(states[1].revision, 3); // App compares this with its current financial revision.
});

test('401 clears admin access; logout/unmount cancellation suppresses late results', async () => {
  const request = createAnalysisRequest(); let exits = 0; const states = [];
  const options = { password: 'secret', revision: 0, runAdmin: submissionGate(), onState: (state) => states.push(state), onUnauthorized() { exits++; } };
  globalThis.fetch = async () => Response.json({}, { status: 401 });
  await request.start(options);
  assert.equal(exits, 1);
  assert.equal(states.at(-1).errorStatus, 401);
  let resolve;
  globalThis.fetch = async () => new Promise((done) => { resolve = done; });
  const pending = request.start(options);
  request.cancel();
  await pending;
  resolve(Response.json(result));
  await Promise.resolve();
  assert.equal(states.at(-1).status, 'loading'); // No ready/error notification after cancellation.
});

test('client deadline covers stalled JSON and cleans up timer without retries', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let calls = 0; let signal;
  globalThis.fetch = async (_, options) => {
    calls++; signal = options.signal;
    return { ok: true, status: 200, json: () => new Promise(() => {}) };
  };
  const pending = analyzeTransactions('secret');
  const rejected = assert.rejects(pending, /Час очікування/);
  await Promise.resolve();
  t.mock.timers.tick(140000);
  await rejected;
  assert.equal(signal.aborted, true);
  assert.equal(calls, 1);
});

test('panel/result render accessible initial, four blocks, empty, stale and escaped text', async () => {
  const vite = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true, include: [] } });
  try {
    const { default: Panel, AiAnalysisResult } = await vite.ssrLoadModule('/src/AiAnalysisPanel.jsx');
    let calls = 0;
    globalThis.fetch = async () => { calls++; throw new Error('must not fetch during render'); };
    const initial = renderToStaticMarkup(React.createElement(Panel, {}));
    assert.match(initial, /лише вручну/);
    assert.match(initial, /disabled/);
    assert.match(initial, /Проаналізувати фінанси за допомогою AI/);
    assert.equal(calls, 0);
    const html = renderToStaticMarkup(React.createElement(AiAnalysisResult, { data: { ...result,
      summary: '<script>test</script>', total_income: '9007199254740993.01' }, stale: true }));
    for (const text of ['Фінансовий підсумок', 'Найбільші категорії витрат', 'Потенційні ризики', 'Практичні рекомендації', 'Аналіз застарів', '25.10.2026', '23.11.2026', '100,00 %']) assert.ok(html.includes(text));
    assert.match(html, /&lt;script&gt;/);
    assert.doesNotMatch(html, /<script>/);
    assert.ok(html.includes('9\u00a0007\u00a0199\u00a0254\u00a0740\u00a0993,01'));
    const empty = renderToStaticMarkup(React.createElement(AiAnalysisResult, { data: { ...result, transaction_count: 0,
      top_expense_categories: [], risks: [], advice: [] } }));
    assert.match(empty, /AI не викликався/);
    assert.match(empty, /Категорій витрат.*немає/);
  } finally { await vite.close(); }
});
