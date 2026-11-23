import React, { useEffect, useRef, useState } from 'react';
import { formatCalendarDate, formatMoney, todayKyiv } from './api.js';
import { createAnalysisRequest } from './aiAnalysisRequest.js';

export function AiAnalysisResult({ data, stale }) {
  return <div className="ai-results">
    {stale && <p className="ai-stale" role="status">Аналіз застарів: дані або календарний день змінилися. Запустіть новий аналіз вручну.</p>}
    {data.transaction_count === 0 && <p role="status">За цей період немає записаних операцій. AI не викликався.</p>}
    <section aria-labelledby="ai-summary"><h3 id="ai-summary">Фінансовий підсумок</h3>
      <p>{data.summary}</p>
      <p>Період: <time dateTime={data.period_start}>{formatCalendarDate(data.period_start)}</time> — <time dateTime={data.period_end}>{formatCalendarDate(data.period_end)}</time> · {data.currency}</p>
      <dl className="ai-totals">{[['Доходи', data.total_income], ['Витрати', data.total_expense], ['Баланс', data.balance]].map(([label, value]) =>
        <div key={label}><dt>{label}</dt><dd>{formatMoney(value)}</dd></div>)}</dl>
      <p>Записано операцій: {data.transaction_count}. Баланс є розрахунковим.</p>
    </section>
    <section aria-labelledby="ai-categories"><h3 id="ai-categories">Найбільші категорії витрат</h3>
      {data.top_expense_categories.length ? <ul className="ai-categories">{data.top_expense_categories.map((item, index) =>
        <li key={index}><span>{item.category}</span><strong>{formatMoney(item.amount)}</strong><span>{item.share_percent.replace('.', ',')} %</span></li>)}</ul> : <p>Категорій витрат за цей період немає.</p>}
    </section>
    <section aria-labelledby="ai-risks"><h3 id="ai-risks">Потенційні ризики</h3>
      {data.risks.length ? <ul>{data.risks.map((text, index) => <li key={index}>{text}</li>)}</ul> : <p>Ризиків у цьому аналізі не зазначено.</p>}
    </section>
    <section aria-labelledby="ai-advice"><h3 id="ai-advice">Практичні рекомендації</h3>
      {data.advice.length ? <ul>{data.advice.map((text, index) => <li key={index}>{text}</li>)}</ul> : <p>Рекомендацій у цьому аналізі немає.</p>}
    </section>
  </div>;
}

export default function AiAnalysisPanel({ password = '', pending = false, runAdmin, onUnauthorized, revision = 0 }) {
  const [state, setState] = useState({ data: null, error: '', status: 'idle' });
  const request = useRef(null);
  if (!request.current) request.current = createAnalysisRequest();
  const [today, setToday] = useState(todayKyiv);
  useEffect(() => {
    if (!state.data) return;
    setToday(todayKyiv());
    const timer = setInterval(() => setToday(todayKyiv()), 60000);
    return () => clearInterval(timer);
  }, [state.data]);
  useEffect(() => {
    setState((previous) => !password && previous.errorStatus === 401
      ? { data: null, error: previous.error, errorStatus: 401, status: 'error' }
      : { data: null, error: '', status: 'idle' });
    return () => request.current.cancel();
  }, [password]);
  const start = () => {
    void request.current.start({ password, pending, revision, runAdmin, onState: setState, onUnauthorized });
  };
  const loading = state.status === 'loading';
  return <section className="panel ai-panel" aria-labelledby="ai-heading" aria-busy={loading}>
    <h2 id="ai-heading">AI-аналіз фінансів</h2>
    <p id="ai-hint">Аналіз запускається лише вручну та охоплює останні 30 календарних днів, включно із сьогодні, незалежно від фільтра таблиці. До сервісу AI передаються фінансові підсумки без описів операцій.</p>
    {!password && <p>Для запуску введіть адміністративний пароль вище.</p>}
    <button type="button" className="button primary ai-button" disabled={!password || pending || loading}
      aria-describedby="ai-hint" onClick={start}>Проаналізувати фінанси за допомогою AI</button>
    {loading && <p role="status"><span className="ai-spinner" aria-hidden="true" /> Аналізуємо фінанси… Це може тривати кілька хвилин.</p>}
    {state.error && <p className="notice-error" role="alert">{state.error}</p>}
    {password && state.status === 'ready' && <p role="status">Аналіз завершено.</p>}
    {password && state.data && <AiAnalysisResult data={state.data} stale={state.revision !== revision || state.data.period_end !== today} />}
    <p className="ai-footnote">Висновки AI можуть бути неточними. Перевіряйте їх за своїми записами. Повторний аналіз виконується тільки після натискання кнопки.</p>
  </section>;
}
