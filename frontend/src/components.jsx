import React from 'react';
import { formatCalendarDate, formatMoney, PAGE_SIZE } from './api.js';

export function ErrorState({ message, onRetry }) {
  return <div className="error-state" role="alert"><span className="error-icon">!</span>
    <div><strong>Дані тимчасово недоступні</strong><p>{message}</p></div>
    <button className="button secondary" onClick={onRetry}>Спробувати ще раз</button>
  </div>;
}

export function SummaryCards({ resource, onRetry }) {
  const cards = [
    { key: 'total_income', label: 'Доходи', icon: '↙', note: 'Усі записані доходи', color: 'green' },
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

export function TransactionsTable({ resource, page, onPage, onRetry, admin = false, pending = false, deletionBlocked = false, onDelete }) {
  return <section className="transactions panel" aria-labelledby="transactions-heading">
    <div className="section-heading"><div><h2 id="transactions-heading" tabIndex={-1}>Останні операції</h2>
      <p>Нові записи першими · календарна дата операції</p></div><span className="badge">UAH · гривня</span></div>
    {resource.status === 'error' ? <ErrorState message={resource.error} onRetry={onRetry} /> :
      resource.status === 'loading' ? <div className="table-loading" role="status">{[0, 1, 2, 3].map((n) =>
        <div className="skeleton row-skeleton" key={n} />)}<span>Завантажуємо операції…</span></div> :
      resource.data.length === 0 ? <div className="empty-state"><span className="empty-icon" aria-hidden="true">≡</span>
        <h3>{page === 0 ? 'Історія починається тут' : 'На цій сторінці немає операцій'}</h3>
        <p>{page === 0 ? 'Створіть дохід або витрату у формі вище, або додайте витрату через Telegram-бота.' : 'Поверніться на попередню сторінку, щоб переглянути записи.'}</p>
        {page === 0 && <code>/expense 125.50 кава</code>}</div> :
      <div className="table-scroll"><table><caption className="sr-only">Фінансові операції, сторінка {page + 1}</caption>
        <thead><tr><th>Дата</th><th>Тип</th><th className="numeric">Сума</th><th>Категорія</th><th>Опис</th>{admin && <th>Дії</th>}</tr></thead>
        <tbody>{resource.data.map((row) => <tr key={row.id}>
          <td className="date-cell">{formatCalendarDate(row.date)}</td><td><span className={`type-badge ${row.type}`}>{row.type === 'income' ? 'Дохід' : 'Витрата'}</span></td>
          <td className={`numeric ${row.type}-amount`}>{row.type === 'income' ? '+' : '−'}{formatMoney(row.amount)}</td>
          <td><span className="category">{row.category}</span></td><td className="description">{row.description}</td>
          {admin && <td><button type="button" className="button danger" disabled={pending || deletionBlocked} onClick={(event) => onDelete(row, event.currentTarget)}
            aria-label={`Видалити ${row.type === 'income' ? 'дохід' : 'витрату'} ${formatMoney(row.amount)} від ${formatCalendarDate(row.date)}`}>Видалити</button></td>}
        </tr>)}</tbody></table></div>}
    <div className="table-footer"><span>Сторінка {page + 1} <span className="footer-detail">· до {PAGE_SIZE} операцій</span></span>
      <nav aria-label="Сторінки операцій"><button className="button secondary" disabled={pending || page === 0 || resource.status === 'loading'}
        onClick={() => onPage(page - 1)}>← Назад</button>
        <button className="button secondary" disabled={pending || resource.status !== 'ready' || resource.data.length < PAGE_SIZE}
          onClick={() => onPage(page + 1)}>Далі →</button></nav></div>
  </section>;
}
