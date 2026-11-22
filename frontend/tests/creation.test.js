import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createTransaction, getSummary, getTransactions, validCalendarDate, formatCalendarDate, todayKyiv } from '../src/api.js';
import { emptyTransaction, validateTransaction, submissionGate } from '../src/transactionForm.js';

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const payload = { type: 'income', amount: '300.00', category: 'Зарплата', description: 'Виплата', date: '2026-11-21' };
const row = { ...payload, id: '9007199254740993', created_at: '2026-11-21T10:00:00Z', currency: 'UAH' };

test('POST uses private per-request credentials, fixed relative URL, no redirects; GET has no password', async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    if (options.method === 'POST') return Response.json(row, { status: 201 });
    return Response.json(url === '/api/summary' ? { total_income: '300.00', total_expense: '0.00', balance: '300.00' } : [row]);
  };
  assert.deepEqual(await createTransaction(payload, 'synthetic-secret'), row);
  await getSummary(); await getTransactions();
  const [url, options] = calls[0];
  assert.equal(url, '/api/transactions');
  assert.equal(options.headers.Authorization, 'Bearer synthetic-secret');
  assert.equal(options.redirect, 'error');
  assert.equal(options.credentials, 'omit');
  assert.deepEqual(JSON.parse(options.body), payload);
  for (const [, getOptions] of calls.slice(1)) assert.equal(getOptions.headers, undefined);
});

test('calendar dates reject invalid leap days and never shift a date', () => {
  assert.equal(validCalendarDate('2024-02-29'), true);
  for (const date of ['2026-02-29', '2026-04-31', '2026-2-01', '0000-01-01', '2026-01-01T00:00:00Z']) assert.equal(validCalendarDate(date), false);
  assert.equal(formatCalendarDate('2026-01-01'), '01.01.2026');
  assert.equal(todayKyiv(new Date('2026-01-01T22:30:00Z')), '2026-01-02');
  assert.equal(todayKyiv(new Date('2026-07-01T21:30:00Z')), '2026-07-02');
});

test('form normalizes comma and whitespace without losing precision', () => {
  const result = validateTransaction({ ...payload, amount: '9999999999,99', category: ' Їжа ', description: ' тест ' });
  assert.deepEqual(result.errors, {});
  assert.equal(result.payload.amount, '9999999999.99');
  assert.equal(result.payload.category, 'Їжа');
  assert.equal(emptyTransaction().type, 'expense');
});

test('form rejects invalid fields and excessive precision without rounding', () => {
  for (const amount of ['0', '0.00', '-1', 'NaN', 'Infinity', '1e2', '10000000000', '1.001', '1,2.3']) {
    assert.ok(validateTransaction({ ...payload, amount }).errors.amount);
  }
  for (const [name, value] of [['type', 'other'], ['date', '2026-02-30'], ['category', ' '], ['category', 'a'.repeat(101)], ['description', 'a'.repeat(2001)]]) {
    assert.ok(validateTransaction({ ...payload, [name]: value }).errors[name]);
  }
});

for (const status of [401, 403, 422, 503, 500]) test(`POST ${status} is safe and never retried`, async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({ detail: [{ field: 'amount', message: 'private-secret' }] }, { status }); };
  await assert.rejects(createTransaction(payload, 'private-secret'), (error) => {
    assert.equal(error.status, status);
    assert.ok(!error.message.includes('private-secret'));
    assert.equal(error.outcomeUnknown, [503, 500].includes(status));
    if (status === 422) assert.ok(error.fieldErrors.amount);
    return true;
  });
  assert.equal(calls, 1);
});

test('disabled writes are distinct from uncertain commit', async () => {
  globalThis.fetch = async () => Response.json({ detail: 'Writing is disabled.' }, { status: 503 });
  await assert.rejects(createTransaction(payload, 'secret'), (error) => !error.outcomeUnknown && /вимкнений/.test(error.message));
});

test('network loss, invalid success JSON, wrong status and invalid response contracts are uncertain', async () => {
  for (const response of [null, new Response('private-secret', { status: 201 }), Response.json(row), Response.json({ ...row, date: '2026-02-30' }, { status: 201 })]) {
    let calls = 0;
    globalThis.fetch = async () => { calls++; if (!response) throw new Error('private-secret'); return response; };
    await assert.rejects(createTransaction(payload, 'private-secret'), (error) => error.outcomeUnknown && !error.message.includes('private-secret'));
    assert.equal(calls, 1);
  }
});

test('synchronous submission latch prevents double POST and releases after failure', async () => {
  const gate = submissionGate();
  let release; let calls = 0;
  const first = gate(async () => { calls++; await new Promise((resolve) => { release = resolve; }); });
  assert.equal(await gate(async () => { calls++; }), false);
  release(); await first;
  await assert.rejects(gate(async () => { throw new Error('failure'); }));
  assert.equal(await gate(async () => { calls++; }), true);
  assert.equal(calls, 2);
});
