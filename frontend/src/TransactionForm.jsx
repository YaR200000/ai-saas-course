import React from 'react';

const labels = { type: 'Тип операції', amount: 'Сума, грн', category: 'Категорія', description: 'Опис', date: 'Дата операції' };

export default function TransactionForm({ values, errors, pending, onChange, onSubmit }) {
  return <form className="transaction-form" noValidate onSubmit={onSubmit} aria-busy={pending}>
    <fieldset disabled={pending}><legend className="sr-only">Дані фінансової операції</legend>
      {Object.entries(labels).map(([name, label]) => {
        const props = { id: `transaction-${name}`, name, value: values[name], required: true,
          onChange: (event) => onChange(name, event.target.value),
          'aria-invalid': Boolean(errors[name]), 'aria-describedby': errors[name] ? `${name}-error` : undefined };
        return <div className={`form-field field-${name}`} key={name}><label htmlFor={props.id}>{label}</label>
          {name === 'type' ? <select {...props}><option value="expense">Витрата</option><option value="income">Дохід</option></select> :
            name === 'description' ? <textarea {...props} rows={2} /> :
              <input {...props} type={name === 'date' ? 'date' : 'text'} inputMode={name === 'amount' ? 'decimal' : undefined} />}
          {errors[name] && <small className="field-error" id={`${name}-error`}>{errors[name]}</small>}
        </div>;
      })}
    </fieldset>
    <button type="submit" className="button primary" disabled={pending}>{pending ? 'Зберігаємо…' : 'Створити операцію'}</button>
  </form>;
}
