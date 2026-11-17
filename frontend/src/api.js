const money = /^-?\d+\.\d{2}$/;
export const PAGE_SIZE = 20;

function validSummary(value) {
  return value && ['total_income', 'total_expense', 'balance'].every(
    (key) => typeof value[key] === 'string' && money.test(value[key]));
}

function validTransactions(value) {
  return Array.isArray(value) && value.every((row) => row &&
    typeof row.id === 'string' && /^\d+$/.test(row.id) &&
    typeof row.created_at === 'string' && Number.isFinite(Date.parse(row.created_at)) &&
    row.type === 'expense' && typeof row.amount === 'string' && /^\d+\.\d{2}$/.test(row.amount) &&
    typeof row.category === 'string' && typeof row.description === 'string' &&
    (row.currency === undefined || row.currency === 'UAH'));
}

async function request(path, validate, signal) {
  let response;
  try { response = await fetch(path, { signal, cache: 'no-store', credentials: 'omit' }); }
  catch (error) {
    if (signal?.aborted) throw error;
    throw new Error('Не вдалося з’єднатися з API. Перевірте локальний backend і спробуйте ще раз.');
  }
  if (!response.ok) throw new Error('Не вдалося отримати дані. Перевірте, чи запущено локальний API.');
  let data;
  try { data = await response.json(); }
  catch { throw new Error('API повернув некоректну відповідь. Спробуйте ще раз.'); }
  if (!validate(data)) throw new Error('Формат відповіді API не відповідає очікуваному.');
  return data;
}

export const getSummary = (signal) => request('/api/summary', validSummary, signal);
export function getTransactions(page = 0, signal) {
  if (!Number.isSafeInteger(page) || page < 0) throw new Error('Некоректна сторінка.');
  return request(`/api/transactions?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`, validTransactions, signal);
}

// Format decimal strings directly: never round financial data through Number.
export function formatMoney(value) {
  if (typeof value !== 'string' || !money.test(value)) return '—';
  const [whole, fraction] = value.split('.');
  const negative = whole.startsWith('-');
  const grouped = whole.replace('-', '').replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
  return `${negative ? '−' : ''}${grouped},${fraction}\u00a0₴`;
}

export function formatDate(value) {
  return new Intl.DateTimeFormat('uk-UA', {
    day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Europe/Kyiv',
  }).format(new Date(value));
}
