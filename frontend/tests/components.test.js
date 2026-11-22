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
      id: '1', created_at: '2026-11-17T09:00:00Z', date: '2026-11-16', type: 'expense', amount: '125.50',
      category: 'Інше', description: '<script>alert(1)</script>' }] } });
    assert.match(table, /&lt;script&gt;/);
    assert.doesNotMatch(table, /<script>/);
    assert.match(table, /16\.11\.2026/);
    assert.match(table, /−125,50/);
    const incomeRow = { id: '2', created_at: '2026-11-17T09:00:00Z', date: '2026-11-15',
      type: 'income', amount: '300.00', category: 'Зарплата', description: 'Виплата' };
    const income = render(TransactionsTable, { ...common, resource: { status: 'ready', data: [incomeRow] } });
    assert.match(income, /Дохід/);
    assert.match(income, /\+300,00/);
    assert.match(income, /15\.11\.2026/);
    const full = render(TransactionsTable, { ...common, page: 1,
      resource: { status: 'ready', data: Array.from({ length: 20 }, (_, n) => ({ ...incomeRow, id: String(n) })) } });
    assert.match(full, /Сторінка 2/);
    assert.doesNotMatch(full, /disabled/);
    assert.equal((income.match(/disabled/g) || []).length, 2);
    const { default: Form } = await vite.ssrLoadModule('/src/TransactionForm.jsx');
    const { default: Access } = await vite.ssrLoadModule('/src/AdminAccess.jsx');
    const { default: Composer } = await vite.ssrLoadModule('/src/TransactionComposer.jsx');
    const form = render(Form, { values: { ...incomeRow, amount: '300,00' }, errors: { amount: 'Перевірте суму' },
      pending: true, onChange() {}, onSubmit() {} });
    assert.match(form, /fieldset disabled/);
    assert.match(form, /aria-invalid="true"/);
    assert.match(form, /aria-describedby="amount-error"/);
    assert.match(form, /Зберігаємо/);
    const access = render(Access, { enabled: false, onPassword() {}, onExit() {} });
    assert.match(access, /type="password"/);
    assert.match(access, /Сервер перевірить пароль/);
    const enabled = render(Access, { enabled: true, busy: true, onExit() {} });
    assert.match(enabled, /Завершити адміністративний режим/);
    assert.match(enabled, /disabled/);
    assert.match(render(Composer, { onCreated() {}, onRefresh() {}, refreshFailed: false }), /Створити операцію/);
    const adminTable = render(TransactionsTable, { ...common, admin: true, pending: true,
      resource: { status: 'ready', data: [incomeRow] }, onDelete() {} });
    assert.match(adminTable, /<th>Дії<\/th>/);
    assert.match(adminTable, /aria-label="Видалити дохід/);
    assert.match(adminTable, /disabled=""[^>]*aria-label="Видалити/);
    assert.doesNotMatch(income, />Видалити</);
    const { default: Dialog } = await vite.ssrLoadModule('/src/DeleteTransactionDialog.jsx');
    const dialog = render(Dialog, { transaction: { ...incomeRow, description: '<script>private</script>' }, pending: true,
      onCancel() {}, onConfirm() {}, restoreFocus() {} });
    assert.match(dialog, /<dialog/);
    assert.match(dialog, /aria-labelledby="delete-title"/);
    assert.match(dialog, /aria-describedby="delete-warning"/);
    assert.match(dialog, /не можна скасувати/);
    assert.match(dialog, /&lt;script&gt;/);
    assert.doesNotMatch(dialog, /<script>/);
    assert.match(dialog, /Видаляємо…/);
    assert.equal((dialog.match(/disabled=""/g) || []).length, 2);
    const formWithSharedAdmin = render(Composer, { password: 'synthetic-not-for-html', pending: true,
      onCreated() {}, onRefresh() {}, onUnauthorized() {}, runAdmin() {}, refreshFailed: false });
    assert.match(formWithSharedAdmin, /fieldset disabled/);
    assert.doesNotMatch(formWithSharedAdmin, /synthetic-not-for-html/);
    // Independent resources can render available data alongside another error.
    assert.match(summary + render(TransactionsTable, { ...common, resource: failed }), /−245,50/);
    assert.match(table + render(SummaryCards, { ...common, resource: failed }), /125,50/);
  } finally { await vite.close(); }
});
