import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { getSummary, getTransactions, formatMoney, formatDate, PAGE_SIZE } from '../src/api.js';

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const summary = { total_income: '0.00', total_expense: '245.50', balance: '-245.50' };
const transaction = { id: '9007199254740993', created_at: '2026-11-17T09:00:00Z', date: '2026-11-17',
  type: 'expense', amount: '125.50', category: 'Інше', description: 'кава', currency: 'UAH' };

test('summary uses the exact backend contract and relative URL', async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/summary');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.credentials, 'omit');
    return Response.json(summary);
  };
  assert.deepEqual(await getSummary(), summary);
});

test('transactions accepts an array, preserves order, IDs, and pagination', async () => {
  globalThis.fetch = async (url) => {
    assert.equal(url, `/api/transactions?limit=${PAGE_SIZE}&offset=40`);
    return Response.json([transaction, { ...transaction, id: '2' }]);
  };
  const rows = await getTransactions(2);
  assert.equal(rows[0].id, '9007199254740993');
  assert.equal(rows[1].id, '2');
});

test('empty transactions remain an empty array', async () => {
  globalThis.fetch = async () => Response.json([]);
  assert.deepEqual(await getTransactions(), []);
});

test('rejects an items envelope and invalid summary/money contracts', async () => {
  globalThis.fetch = async () => Response.json({ items: [transaction] });
  await assert.rejects(getTransactions(), /Формат/);
  globalThis.fetch = async () => Response.json({ ...summary, balance: -245.5 });
  await assert.rejects(getSummary(), /Формат/);
  globalThis.fetch = async () => Response.json([{ ...transaction, amount: 125.5 }]);
  await assert.rejects(getTransactions(), /Формат/);
});

test('HTTP errors never expose response bodies', async () => {
  globalThis.fetch = async () => new Response('private-sql-password', { status: 503 });
  await assert.rejects(getSummary(), (error) => !error.message.includes('private') && /API/.test(error.message));
});

test('malformed JSON and network errors have readable messages', async () => {
  globalThis.fetch = async () => new Response('<html>error</html>');
  await assert.rejects(getSummary(), /некоректну/);
  globalThis.fetch = async () => { throw new TypeError('Network error'); };
  await assert.rejects(getTransactions(), /з’єднатися/);
});

test('abort signal is passed through', async () => {
  const controller = new AbortController();
  globalThis.fetch = async (_, options) => {
    assert.equal(options.signal, controller.signal);
    return Response.json(summary);
  };
  await getSummary(controller.signal);
});

test('formats negative, zero, and very large decimal amounts without float', () => {
  assert.equal(formatMoney('-245.50'), '−245,50\u00a0₴');
  assert.equal(formatMoney('0.00'), '0,00\u00a0₴');
  assert.equal(formatMoney('9007199254740993.01'), '9\u00a0007\u00a0199\u00a0254\u00a0740\u00a0993,01\u00a0₴');
  assert.equal(formatMoney(undefined), '—');
  assert.match(formatDate('2026-11-17T23:30:00Z'), /18/);
  assert.throws(() => getTransactions(-1), /сторінка/);
});
