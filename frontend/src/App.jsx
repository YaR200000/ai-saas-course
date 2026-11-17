import React, { useState } from 'react';
import { getSummary, getTransactions } from './api.js';
import { useResource } from './useResource.js';
import { SummaryCards, TransactionsTable } from './components.jsx';

const loadSummary = (_, signal) => getSummary(signal);

export default function App() {
  const [page, setPage] = useState(0);
  const [summaryVersion, setSummaryVersion] = useState(0);
  const [transactionsVersion, setTransactionsVersion] = useState(0);
  const summary = useResource(loadSummary, 0, summaryVersion);
  const transactions = useResource(getTransactions, page, transactionsVersion);
  const refresh = () => { setSummaryVersion((n) => n + 1); setTransactionsVersion((n) => n + 1); };
  const busy = summary.status === 'loading' || transactions.status === 'loading';

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
        <button className="button primary" onClick={refresh} disabled={busy}><span aria-hidden="true">↻</span>{busy ? 'Оновлюємо…' : 'Оновити дані'}</button></div>
        <SummaryCards resource={summary} onRetry={() => setSummaryVersion((n) => n + 1)} />
        <div className="balance-notice"><span className="info-icon" aria-hidden="true">i</span><p><strong>Баланс є розрахунковим.</strong> Зараз обліковуються лише витрати; доходи ще не реєструються. Це не залишок на банківському рахунку.</p></div>
        <TransactionsTable resource={transactions} page={page} onPage={setPage} onRetry={() => setTransactionsVersion((n) => n + 1)} />
        <footer className="page-footer"><span>finspace <span>·</span> Простір для фінансової ясності</span><span>Дані з вашого Telegram-бота</span></footer>
      </div>
    </main>
  </div>;
}
