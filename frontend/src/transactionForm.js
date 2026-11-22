import { todayKyiv, validCalendarDate } from './api.js';

export const emptyTransaction = () => ({ type: 'expense', amount: '', category: '', description: '', date: todayKyiv() });

export function validateTransaction(values) {
  const errors = {};
  const amount = values.amount.trim().replace(',', '.');
  if (!['income', 'expense'].includes(values.type)) errors.type = 'Виберіть тип операції.';
  // Lexical bound matches NUMERIC(12,2); no financial conversion through Number.
  if (!/^[0-9]{1,10}(?:\.[0-9]{1,2})?$/.test(amount) || /^0+(?:\.0{1,2})?$/.test(amount)) {
    errors.amount = 'Введіть суму від 0,01 до 9 999 999 999,99, максимум два десяткові знаки.';
  }
  for (const [name, maximum] of [['category', 100], ['description', 2000]]) {
    if (!values[name].trim() || [...values[name].trim()].length > maximum || values[name].includes('\0')) {
      errors[name] = `Введіть від 1 до ${maximum} символів.`;
    }
  }
  if (!validCalendarDate(values.date)) errors.date = 'Введіть справжню календарну дату.';
  return { errors, payload: { type: values.type, amount, category: values.category.trim(), description: values.description.trim(), date: values.date } };
}

// Synchronous latch also blocks submissions before React renders pending=true.
export function submissionGate() {
  let active = false;
  return async (operation) => {
    if (active) return false;
    active = true;
    try { await operation(); return true; } finally { active = false; }
  };
}
