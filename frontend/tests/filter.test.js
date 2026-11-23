import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { getTransactionPage } from '../src/api.js';
import { transactionListReducer } from '../src/transactionList.js';
import { pageAfterDeletion } from '../src/transactionForm.js';

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const income = { id: '1', created_at: '2026-11-17T09:00:00Z', date: '2026-11-17',
  type: 'income', amount: '300.00', category: 'Salary', description: 'Test', currency: 'UAH' };

for (const type of ['all', 'income', 'expense']) test(`page request sends ${type} and parses filtered total`, async () => {
  const controller = new AbortController();
  globalThis.fetch = async (url, options) => {
    assert.equal(url, `/api/transactions?limit=20&offset=40&type=${type}`);
    assert.equal(options.signal, controller.signal);
    assert.equal(options.headers, undefined);
    assert.equal(options.credentials, 'omit');
    return Response.json([income], { headers: { 'X-Total-Count': '41' } });
  };
  assert.deepEqual(await getTransactionPage(2, controller.signal, type), { items: [income], total: 41 });
});

test('filter changes reset the React list reducer page; create/delete navigation preserves filter', () => {
  let state = { page: 3, type: 'all' };
  for (const value of ['income', 'expense', 'all']) {
    state = transactionListReducer(state, { type: 'filter', value });
    assert.deepEqual(state, { page: 0, type: value });
    state = transactionListReducer(state, { type: 'page', value: 4 });
    assert.deepEqual(state, { page: 4, type: value });
    state = transactionListReducer(state, { type: 'page', value: pageAfterDeletion(4, 1) });
    assert.deepEqual(state, { page: 3, type: value });
    state = transactionListReducer(state, { type: 'page', value: 0 });
    assert.deepEqual(state, { page: 0, type: value });
    state = transactionListReducer(state, { type: 'page', value: (page) => page + 2 });
  }
});

test('empty filtered pages retain total and invalid totals fail safely', async () => {
  globalThis.fetch = async () => Response.json([], { headers: { 'X-Total-Count': '4' } });
  assert.deepEqual(await getTransactionPage(2, undefined, 'income'), { items: [], total: 4 });
  for (const raw of [undefined, '-1', '1.5', '9007199254740992', 'private']) {
    globalThis.fetch = async () => Response.json([], { headers: raw === undefined ? {} : { 'X-Total-Count': raw } });
    await assert.rejects(getTransactionPage(), /кількість/);
  }
  assert.throws(() => getTransactionPage(0, undefined, 'invalid'), /тип/);
  assert.throws(() => getTransactionPage(-1), /сторінка/);
});

test('filtered API failures and malformed payloads have safe errors', async () => {
  globalThis.fetch = async () => Response.json({ detail: 'private' }, { status: 422 });
  await assert.rejects(getTransactionPage(), (error) => error.status === 422 && !error.message.includes('private'));
  globalThis.fetch = async () => { throw new Error('private'); };
  await assert.rejects(getTransactionPage(), /з’єднатися/);
  globalThis.fetch = async () => Response.json({ items: [] }, { headers: { 'X-Total-Count': '0' } });
  await assert.rejects(getTransactionPage(), /Формат/);
});

test('filter control is labelled, emits selection, and count disables Next on a full last page', async () => {
  const vite = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true, include: [] } });
  try {
    const { TransactionsTable } = await vite.ssrLoadModule('/src/components.jsx');
    let selected;
    const props = { page: 0, type: 'income', onType(value) { selected = value; }, onPage() {}, onRetry() {},
      resource: { status: 'ready', total: 20, data: Array.from({ length: 20 }, (_, i) => ({ ...income, id: String(i + 1) })) } };
    const element = TransactionsTable(props);
    const filter = element.props.children.find((child) => child?.props?.className === 'transaction-filter');
    const select = filter.props.children.find((child) => child.type === 'select');
    select.props.onChange({ target: { value: 'expense' } });
    assert.equal(selected, 'expense');
    const render = (extra = {}) => renderToStaticMarkup(React.createElement(TransactionsTable, { ...props, ...extra }));
    const html = render();
    assert.match(html, /label for="transaction-type"/);
    assert.match(html, /value="income" selected/);
    assert.match(html, /Усього: 20/);
    assert.match(html, /disabled="">Далі/);
    assert.match(render({ pending: true }), /select[^>]*disabled/);
    assert.match(render({ resource: { status: 'ready', data: [], total: 0 } }), /За цим фільтром немає/);
    assert.match(render({ resource: { status: 'loading', data: null } }), /Завантажуємо/);
    assert.match(render({ resource: { status: 'error', data: null, error: 'API unavailable' } }), /role="alert"/);
  } finally { await vite.close(); }
});
