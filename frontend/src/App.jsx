import React, { useEffect, useRef, useState } from 'react';
import { deleteTransaction, getSummary, getTransactions } from './api.js';
import { useResource } from './useResource.js';
import { SummaryCards, TransactionsTable } from './components.jsx';
import TransactionComposer from './TransactionComposer.jsx';
import AdminAccess from './AdminAccess.jsx';
import DeleteTransactionDialog from './DeleteTransactionDialog.jsx';
import { pageAfterDeletion, submissionGate } from './transactionForm.js';

const loadSummary = (_, signal) => getSummary(signal);

export default function App() {
  const [page, setPage] = useState(0);
  const [summaryVersion, setSummaryVersion] = useState(0);
  const [transactionsVersion, setTransactionsVersion] = useState(0);
  const [password, setPassword] = useState('');
  const [adminPending, setAdminPending] = useState(false);
  const [selected, setSelected] = useState(null);
  const [deleteNotice, setDeleteNotice] = useState(null);
  const gate = useRef(null);
  const focusReturn = useRef(null);
  const reconcile = useRef(false);
  const verifyAfter = useRef(null);
  if (!gate.current) gate.current = submissionGate();
  const runAdmin = (operation) => gate.current(async () => {
    setAdminPending(true);
    try { await operation(); } finally { setAdminPending(false); }
  });
  const summary = useResource(loadSummary, 0, summaryVersion);
  const transactions = useResource(getTransactions, page, transactionsVersion);
  const refresh = (targetPage = page) => { setPage(targetPage); setSummaryVersion((n) => n + 1); setTransactionsVersion((n) => n + 1); };
  const busy = summary.status === 'loading' || transactions.status === 'loading';
  useEffect(() => {
    if (verifyAfter.current !== null && transactions.status === 'ready' && transactions.version >= verifyAfter.current) {
      verifyAfter.current = null;
      setDeleteNotice({ message: 'Список оновлено. Перевірте операції; повторна дія потребує нового підтвердження.' });
    }
    if (reconcile.current && transactions.status === 'ready') {
      if (page > 0 && transactions.data.length === 0) setPage((previous) => previous - 1);
      else reconcile.current = false;
    }
  }, [page, transactions]);
  const restoreFocus = () => {
    const target = focusReturn.current;
    if (target?.isConnected && !target.disabled) target.focus();
    else document.getElementById('transactions-heading')?.focus();
  };
  const confirmDelete = () => {
    if (!selected || !password) return;
    void runAdmin(async () => {
      try { await deleteTransaction(selected.transaction.id, password); }
      catch (error) {
        setSelected(null);
        if (error.status === 401) setPassword('');
        setDeleteNotice({ message: error.message, error: true, unknown: error.outcomeUnknown });
        if (error.outcomeUnknown) verifyAfter.current = transactionsVersion + 1;
        if (error.status === 404) { reconcile.current = true; refresh(pageAfterDeletion(selected.page, selected.count)); }
        return;
      }
      focusReturn.current = null;
      setSelected(null);
      setDeleteNotice({ message: 'Операцію видалено.', success: true });
      reconcile.current = true;
      refresh(pageAfterDeletion(selected.page, selected.count));
    });
  };

  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#overview"><span className="brand-mark">f<span>↗</span></span>finspace<span className="brand-dot">.</span></a>
      <div className="workspace"><span className="workspace-avatar">М</span><div><strong>Мої фінанси</strong><small>Особистий простір</small></div></div>
      <p className="nav-label">РОБОЧИЙ ПРОСТІР</p>
      <nav aria-label="Основна навігація"><a className="nav-link active" href="#overview"><span aria-hidden="true">▦</span>Огляд фінансів</a>
        <a className="nav-link" href="#transactions-heading"><span aria-hidden="true">≡</span>Операції</a></nav>
      <div className="sidebar-note"><span className="connection-dot" />Локальний простір<p>Ваші фінанси. Під вашим контролем.</p></div>
      <div className="profile"><span className="profile-avatar">В</span><div><strong>Власний простір</strong><small>Навчальний dashboard</small></div></div>
    </aside>
    <main id="overview"><header className="topbar"><span>Робочий простір <span className="breadcrumb-divider">/</span> <strong>Огляд</strong></span><span className="local-pill"><span className="connection-dot" />Локальний режим</span></header>
      <div className="main-content"><div className="page-heading"><div><p className="eyebrow">ВАШІ ФІНАНСИ, ЗРОЗУМІЛО</p><h1>Фінансовий огляд</h1><p>Усі операції та головні цифри — в одному місці.</p></div>
        <button className="button primary" onClick={() => refresh()} disabled={busy || adminPending}><span aria-hidden="true">↻</span>{busy ? 'Оновлюємо…' : 'Оновити дані'}</button></div>
        <SummaryCards resource={summary} onRetry={() => setSummaryVersion((n) => n + 1)} />
        <div className="balance-notice"><span className="info-icon" aria-hidden="true">i</span><p><strong>Баланс є розрахунковим.</strong> Це різниця облікованих доходів і витрат, а не залишок на банківському рахунку.</p></div>
        <section className="panel admin-panel" aria-label="Адміністративний доступ">
          <AdminAccess enabled={Boolean(password)} busy={adminPending} onPassword={setPassword} onExit={() => { setPassword(''); setSelected(null); }} />
        </section>
        <TransactionComposer onCreated={() => refresh(0)} onRefresh={() => refresh()}
          password={password} onUnauthorized={() => setPassword('')} pending={adminPending} runAdmin={runAdmin}
          refreshFailed={summary.status === 'error' || transactions.status === 'error'} />
        {deleteNotice && <div className={`form-notice ${deleteNotice.error ? 'notice-error' : ''}`} role={deleteNotice.error ? 'alert' : 'status'}>
          <p>{deleteNotice.message}</p>
          {deleteNotice.success && (summary.status === 'error' || transactions.status === 'error') && <p>Операцію видалено, але дані не вдалося оновити.</p>}
          {(deleteNotice.unknown || (deleteNotice.success && (summary.status === 'error' || transactions.status === 'error'))) &&
            <button type="button" className="button secondary" disabled={busy || adminPending} onClick={() => refresh()}>Оновити список і показники</button>}
        </div>}
        <TransactionsTable resource={transactions} page={page} onPage={setPage} onRetry={() => setTransactionsVersion((n) => n + 1)}
          admin={Boolean(password)} pending={adminPending} deletionBlocked={Boolean(deleteNotice?.unknown)} onDelete={(transaction, trigger) => {
            if (adminPending) return;
            focusReturn.current = trigger; setSelected({ transaction, page, count: transactions.data.length });
          }} />
        {selected && <DeleteTransactionDialog transaction={selected.transaction} pending={adminPending} onConfirm={confirmDelete}
          onCancel={() => { if (!adminPending) setSelected(null); }} restoreFocus={restoreFocus} />}
        <footer className="page-footer"><span>finspace <span>·</span> Простір для фінансової ясності</span><span>Операції з dashboard і Telegram-бота</span></footer>
      </div>
    </main>
  </div>;
}
