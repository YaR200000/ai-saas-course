import React, { useState } from 'react';

export default function AdminAccess({ enabled, busy, onPassword, onExit }) {
  const [input, setInput] = useState('');
  if (enabled) return <div className="admin-access"><p>Пароль зберігається лише до завершення режиму або перезавантаження сторінки.</p>
    <button type="button" className="button secondary" disabled={busy} onClick={onExit}>Завершити адміністративний режим</button></div>;
  return <form className="admin-access" onSubmit={(event) => {
    event.preventDefault();
    if (!input) return;
    onPassword(input); setInput('');
  }}>
    <div className="form-field"><label htmlFor="admin-password">Адміністративний пароль</label>
      <input id="admin-password" type="password" autoComplete="off" value={input} required
        onChange={(event) => setInput(event.target.value)} aria-describedby="admin-hint" />
      <small id="admin-hint">Сервер перевірить пароль під час адміністративного запиту.</small></div>
    <button className="button secondary" type="submit" disabled={!input || busy}>Увімкнути адміністративний режим</button>
  </form>;
}
