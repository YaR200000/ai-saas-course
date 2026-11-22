import React, { useEffect, useRef } from 'react';
import { formatCalendarDate, formatMoney } from './api.js';

export default function DeleteTransactionDialog({ transaction, pending, onCancel, onConfirm, restoreFocus }) {
  const dialog = useRef(null);
  const cancel = useRef(null);
  const restore = useRef(restoreFocus);
  restore.current = restoreFocus;
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    cancel.current.focus();
    return () => { element.close(); restore.current(); };
  }, []);
  return <dialog ref={dialog} className="delete-dialog" aria-labelledby="delete-title" aria-describedby="delete-warning" aria-busy={pending}
    onCancel={(event) => { event.preventDefault(); if (!pending) onCancel(); }}
    onKeyDown={(event) => { if (event.key === 'Enter' && event.target !== cancel.current) event.preventDefault(); }}>
    <h2 id="delete-title">Видалити операцію?</h2>
    <p id="delete-warning">Видалення не можна скасувати через dashboard. Перевірте вибрану операцію.</p>
    <dl><dt>Тип</dt><dd>{transaction.type === 'income' ? 'Дохід' : 'Витрата'}</dd>
      <dt>Сума</dt><dd>{transaction.type === 'income' ? '+' : '−'}{formatMoney(transaction.amount)}</dd>
      <dt>Дата</dt><dd>{formatCalendarDate(transaction.date)}</dd>
      <dt>Категорія</dt><dd>{transaction.category}</dd><dt>Опис</dt><dd>{transaction.description}</dd></dl>
    <div className="dialog-actions"><button ref={cancel} type="button" className="button secondary" disabled={pending} onClick={onCancel}>Скасувати</button>
      <button type="button" className="button danger" disabled={pending} onClick={onConfirm}>{pending ? 'Видаляємо…' : 'Так, видалити операцію'}</button></div>
    <p className="dialog-hint">Для підтвердження з клавіатури використайте Tab і пробіл.</p>
    {pending && <p role="status">Очікуємо підтвердження сервера…</p>}
  </dialog>;
}
