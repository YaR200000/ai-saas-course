import React, { useEffect, useRef, useState } from 'react';
import AdminAccess from './AdminAccess.jsx';
import TransactionForm from './TransactionForm.jsx';
import { createTransaction } from './api.js';
import { emptyTransaction, submissionGate, validateTransaction } from './transactionForm.js';

export default function TransactionComposer({ onCreated, onRefresh, refreshFailed }) {
  const [password, setPassword] = useState('');
  const [values, setValues] = useState(emptyTransaction);
  const [errors, setErrors] = useState({});
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState(null);
  const mounted = useRef(true);
  const gate = useRef(null);
  if (!gate.current) gate.current = submissionGate();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const submit = (event) => {
    event.preventDefault();
    if (!password) return;
    const { errors: validation, payload } = validateTransaction(values);
    setErrors(validation);
    if (Object.keys(validation).length) { setNotice({ message: 'Перевірте поля форми.', error: true }); return; }
    void gate.current(async () => {
      setPending(true); setNotice(null);
      let created;
      try { created = await createTransaction(payload, password); }
      catch (error) {
        if (!mounted.current) return;
        if (error.status === 401) setPassword('');
        setErrors(error.fieldErrors || {});
        setNotice({ message: error.message, error: true, unknown: error.outcomeUnknown });
      } finally { if (mounted.current) setPending(false); }
      if (created && mounted.current) {
        setValues(emptyTransaction()); setErrors({});
        setNotice({ message: 'Операцію створено.', success: true });
        onCreated();
      }
    });
  };

  return <section className="panel transaction-composer" aria-labelledby="create-heading">
    <div className="section-heading"><div><h2 id="create-heading">Створити операцію</h2>
      <p>Доходи та витрати в гривнях · локальний адміністративний доступ</p></div></div>
    <div className="composer-content">
      <AdminAccess enabled={Boolean(password)} busy={pending} onPassword={(value) => { setPassword(value); setNotice(null); }}
        onExit={() => { setPassword(''); setNotice(null); }} />
      {password && <TransactionForm values={values} errors={errors} pending={pending} onSubmit={submit}
        onChange={(name, value) => { setValues((previous) => ({ ...previous, [name]: value })); setErrors((previous) => ({ ...previous, [name]: '' })); }} />}
      {notice && <div className={`form-notice ${notice.error ? 'notice-error' : ''}`} role={notice.error ? 'alert' : 'status'}>
        <p>{notice.success && refreshFailed ? 'Операцію створено, але дані не вдалося оновити.' : notice.message}</p>
        {(notice.unknown || (notice.success && refreshFailed)) && <button type="button" className="button secondary" onClick={onRefresh}>Оновити список і показники</button>}
      </div>}
    </div>
  </section>;
}
