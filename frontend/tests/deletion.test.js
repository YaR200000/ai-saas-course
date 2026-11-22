import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { deleteTransaction, getSummary, getTransactions, validTransactionId } from '../src/api.js';
import { pageAfterDeletion, submissionGate } from '../src/transactionForm.js';

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

test('DELETE keeps BIGINT exact, uses only per-request Bearer, no body, no redirects and never parses 204', async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    if (options.method === 'DELETE') return { status: 204, json() { throw new Error('must not parse'); } };
    return Response.json(url === '/api/summary' ? { total_income: '0.00', total_expense: '0.00', balance: '0.00' } : []);
  };
  await deleteTransaction('9223372036854775807', 'synthetic-secret');
  await getSummary(); await getTransactions();
  assert.equal(calls[0][0], '/api/transactions/9223372036854775807');
  const options = calls[0][1];
  assert.equal(options.method, 'DELETE');
  assert.equal(options.headers.Authorization, 'Bearer synthetic-secret');
  assert.equal(options.credentials, 'omit');
  assert.equal(options.redirect, 'error');
  assert.equal('body' in options, false);
  for (const [, getOptions] of calls.slice(1)) assert.equal(getOptions.headers, undefined);
});

test('invalid IDs never reach fetch; all bounds checked as text', async () => {
  globalThis.fetch = () => { throw new Error('must not send'); };
  for (const id of [0, 1, null, undefined, '', '0', '-1', '+1', '1.0', '1e2', '../1', '9223372036854775808', '9'.repeat(100)]) {
    assert.equal(validTransactionId(id), false);
    await assert.rejects(deleteTransaction(id, 'secret'), (error) => error.status === 422 && !error.outcomeUnknown);
  }
  for (const id of ['1', '9007199254740993', '9223372036854775807']) assert.equal(validTransactionId(id), true);
});

for (const status of [401, 403, 404, 422, 503, 500]) test(`DELETE ${status}: safe error, no automatic retries`, async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({ detail: 'private SQL password' }, { status }); };
  await assert.rejects(deleteTransaction('1', 'private-secret'), (error) => {
    assert.equal(error.status, status);
    assert.equal(error.outcomeUnknown, [503, 500].includes(status));
    assert.doesNotMatch(error.message, /private|SQL|password/);
    if (status === 404) assert.match(error.message, /недоступна/);
    if (status === 422) assert.match(error.message, /ідентифікатор/);
    return true;
  });
  assert.equal(calls, 1);
});

test('disabled writes and uncertain outcomes are distinguished', async () => {
  globalThis.fetch = async () => Response.json({ detail: 'Writing is disabled.' }, { status: 503 });
  await assert.rejects(deleteTransaction('1', 'secret'), (error) => !error.outcomeUnknown && /вимкнений/.test(error.message));
  for (const response of [null, Response.json({}), Response.json({}, { status: 202 })]) {
    let calls = 0;
    globalThis.fetch = async () => { calls++; if (!response) throw new Error('private-secret'); return response; };
    await assert.rejects(deleteTransaction('1', 'secret'), (error) => error.outcomeUnknown && !error.message.includes('private-secret'));
    assert.equal(calls, 1);
  }
});

test('shared latch excludes simultaneous POST/DELETE and repeated confirmation', async () => {
  const gate = submissionGate();
  let release; let deletes = 0;
  globalThis.fetch = async () => { deletes++; return new Response(null, { status: 204 }); };
  const postInFlight = gate(() => new Promise((resolve) => { release = resolve; }));
  assert.equal(await gate(() => deleteTransaction('1', 'secret')), false);
  assert.equal(deletes, 0);
  release(); await postInFlight;
  const first = gate(() => deleteTransaction('1', 'secret'));
  assert.equal(await gate(() => deleteTransaction('1', 'secret')), false);
  await first;
  assert.equal(deletes, 1);
});

test('deletion selects the needed page before fetching; first page stays zero', () => {
  assert.equal(pageAfterDeletion(3, 1), 2);
  assert.equal(pageAfterDeletion(3, 2), 3);
  assert.equal(pageAfterDeletion(0, 1), 0);
});

test('15-second timeout aborts DELETE, classifies AbortError as unknown, releases gate and never retries', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const gate = submissionGate();
  let signal; let calls = 0; let transportError;
  globalThis.fetch = (_, options) => {
    calls++; signal = options.signal;
    return new Promise((_, reject) => signal.addEventListener('abort', () => {
      transportError = new DOMException('synthetic abort', 'AbortError');
      reject(transportError);
    }, { once: true }));
  };
  const pending = gate(() => deleteTransaction('1', 'secret'));
  const rejected = assert.rejects(pending, (error) => error.outcomeUnknown === true && error.status === 0 && /15 секунд/.test(error.message));
  assert.equal(await gate(() => { throw new Error('must stay locked'); }), false);
  t.mock.timers.tick(14999);
  assert.equal(signal.aborted, false);
  t.mock.timers.tick(1);
  await rejected;
  assert.equal(transportError.name, 'AbortError');
  assert.equal(signal.aborted, true);
  assert.equal(await gate(async () => {}), true);
  t.mock.timers.tick(15000);
  assert.equal(calls, 1);
});

test('timeout covers error-body reading on the same deadline, even if the reader ignores abort', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let signal; let finishBody; let calls = 0; let reading = false;
  globalThis.fetch = async (_, options) => {
    calls++; signal = options.signal;
    return { status: 401, ok: false, json: () => { reading = true; return new Promise((resolve) => { finishBody = resolve; }); } };
  };
  const pending = deleteTransaction('1', 'secret');
  const rejected = assert.rejects(pending, (error) => error.outcomeUnknown === true && error.status === 0);
  await Promise.resolve();
  assert.equal(reading, true);
  t.mock.timers.tick(15000);
  await rejected;
  assert.equal(signal.aborted, true);
  finishBody({ detail: 'private-secret' }); // Late status/body must not override timeout.
  await Promise.resolve();
  assert.equal(calls, 1);
});

test('AbortError during error-body reading cannot become an ordinary 401', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  globalThis.fetch = async (_, { signal }) => ({ status: 401, ok: false,
    json: () => new Promise((_, reject) => signal.addEventListener('abort', () => {
      reject(new DOMException('synthetic body abort', 'AbortError'));
    }, { once: true })) });
  const pending = deleteTransaction('1', 'secret');
  const rejected = assert.rejects(pending, (error) => error.outcomeUnknown === true && error.status === 0);
  await Promise.resolve();
  t.mock.timers.tick(15000);
  await rejected;
});

for (const status of [204, 401, 503]) test(`DELETE ${status} clears its timer after completion`, async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const clear = t.mock.method(globalThis, 'clearTimeout');
  let signal;
  globalThis.fetch = async (_, options) => {
    signal = options.signal;
    return status === 204 ? new Response(null, { status }) : Response.json({ detail: 'synthetic' }, { status });
  };
  if (status === 204) await deleteTransaction('1', 'secret');
  else await assert.rejects(deleteTransaction('1', 'secret'), (error) => error.status === status);
  assert.equal(clear.mock.callCount(), 1);
  t.mock.timers.tick(15000);
  assert.equal(signal.aborted, false);
});
