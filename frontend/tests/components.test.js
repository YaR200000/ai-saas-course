import { test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('components render loading, error, empty, negative balance, and partial data', async () => {
  const vite = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true, include: [] } });
  try {
    const { SummaryCards, TransactionsTable } = await vite.ssrLoadModule('/src/components.jsx');
    const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));
    const common = { onRetry() {}, onPage() {}, page: 0 };
    const loading = { status: 'loading', data: null };
    assert.match(render(SummaryCards, { ...common, resource: loading }), /Завантаження суми/);
    assert.match(render(TransactionsTable, { ...common, resource: loading }), /Завантажуємо операції/);
    const failed = { status: 'error', data: null, error: 'API недоступний' };
    assert.match(render(SummaryCards, { ...common, resource: failed }), /Спробувати ще раз/);
    assert.match(render(TransactionsTable, { ...common, resource: failed }), /role="alert"/);
    assert.match(render(TransactionsTable, { ...common, resource: { status: 'ready', data: [] } }), /Історія починається тут/);
    assert.match(render(TransactionsTable, { ...common, page: 1, resource: { status: 'ready', data: [] } }), /На цій сторінці немає/);
    const summary = render(SummaryCards, { ...common, resource: { status: 'ready', data: {
      total_income: '0.00', total_expense: '245.50', balance: '-245.50' } } });
    assert.match(summary, /−245,50/);
    const table = render(TransactionsTable, { ...common, resource: { status: 'ready', data: [{
      id: '1', created_at: '2026-11-17T09:00:00Z', type: 'expense', amount: '125.50',
      category: 'Інше', description: '<script>alert(1)</script>' }] } });
    assert.match(table, /&lt;script&gt;/);
    assert.doesNotMatch(table, /<script>/);
    // Independent resources can render available data alongside another error.
    assert.match(summary + render(TransactionsTable, { ...common, resource: failed }), /−245,50/);
    assert.match(table + render(SummaryCards, { ...common, resource: failed }), /125,50/);
  } finally { await vite.close(); }
});
