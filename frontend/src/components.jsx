import React from 'react';
import { formatDate, formatMoney, PAGE_SIZE } from './api.js';

export function ErrorState({ message, onRetry }) {
  return <div className="error-state" role="alert"><span className="error-icon">!</span>
    <div><strong>Дані тимчасово недоступні</strong><p>{message}</p></div>
    <button className="button secondary" onClick={onRetry}>Спробувати ще раз</button>
  </div>;
}

export function SummaryCards({ resource, onRetry }) {
  const cards = [
    { key: 'total_income', label: 'Доходи', icon: '↙', note: 'Ще не реєструються', color: 'green' },
    { key: 'total_expense', label: 'Витрати', icon: '↗', note: 'Усі записані витрати', color: 'rose' },
    { key: 'balance', label: 'Баланс', icon: '≈', note: 'Розрахунковий залишок', color: 'violet' },
  ];
  return <section aria-label="Фінансові підсумки" aria-busy={resource.status === 'loading'}>
    {resource.status === 'error' && <ErrorState message={resource.error} onRetry={onRetry} />}
    <div className="summary-grid">{cards.map((card) => <article className={`summary-card ${card.color}`} key={card.key}>
      <div className="card-top"><span>{card.label}</span><span className="card-icon" aria-hidden="true">{card.icon}</span></div>
      {resource.status === 'loading' ? <div className="skeleton amount-skeleton" aria-label="Завантаження суми" /> :
        <p className="amount">{resource.data ? formatMoney(resource.data[card.key]) : '—'}</p>}
      <p className="card-note">{card.note}</p>
    </article>)}</div>
  </section>;
}

export function TransactionsTable({ resource, page, onPage, onRetry }) {
  return <section className="transactions panel" aria-labelledby="transactions-heading">
    <div className="section-heading"><div><h2 id="transactions-heading">Останні операції</h2>
      <p>Від нових до старих · дати за київським часом</p></div><span className="badge">UAH · гривня</span></div>
    {resource.status === 'error' ? <ErrorState message={resource.error} onRetry={onRetry} /> :
      resource.status === 'loading' ? <div className="table-loading" role="status">{[0, 1, 2, 3].map((n) =>
        <div className="skeleton row-skeleton" key={n} />)}<span>Завантажуємо операції…</span></div> :
      resource.data.length === 0 ? <div className="empty-state"><span className="empty-icon" aria-hidden="true">≡</span>
        <h3>{page === 0 ? 'Історія починається тут' : 'На цій сторінці немає операцій'}</h3>
        <p>{page === 0 ? 'Додайте витрату в Telegram-боті — вона з’явиться у вашому огляді.' : 'Поверніться на попередню сторінку, щоб переглянути записи.'}</p>
        {page === 0 && <code>/expense 125.50 кава</code>}</div> :
      <div className="table-scroll"><table><caption className="sr-only">Фінансові операції, сторінка {page + 1}</caption>
        <thead><tr><th>Дата</th><th>Тип</th><th className="numeric">Сума</th><th>Категорія</th><th>Опис</th></tr></thead>
        <tbody>{resource.data.map((row) => <tr key={row.id}>
          <td className="date-cell">{formatDate(row.created_at)}</td><td><span className="type-badge">Витрата</span></td>
          <td className="numeric expense-amount">−{formatMoney(row.amount)}</td>
          <td><span className="category">{row.category}</span></td><td className="description">{row.description}</td>
        </tr>)}</tbody></table></div>}
    <div className="table-footer"><span>Сторінка {page + 1} <span className="footer-detail">· до {PAGE_SIZE} операцій</span></span>
      <nav aria-label="Сторінки операцій"><button className="button secondary" disabled={page === 0 || resource.status === 'loading'}
        onClick={() => onPage(page - 1)}>← Назад</button>
        <button className="button secondary" disabled={resource.status !== 'ready' || resource.data.length < PAGE_SIZE}
          onClick={() => onPage(page + 1)}>Далі →</button></nav></div>
  </section>;
}
