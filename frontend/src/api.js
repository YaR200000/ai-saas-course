const money = /^-?\d+\.\d{2}$/;
export const PAGE_SIZE = 20;

function validSummary(value) {
  return value && ['total_income', 'total_expense', 'balance'].every(
    (key) => typeof value[key] === 'string' && money.test(value[key]));
}

export function validCalendarDate(value) {
  if (typeof value !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith('0000')) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function validTransaction(row) {
  return row &&
    typeof row.id === 'string' && /^\d+$/.test(row.id) &&
    typeof row.created_at === 'string' && Number.isFinite(Date.parse(row.created_at)) &&
    ['income', 'expense'].includes(row.type) && validCalendarDate(row.date) &&
    typeof row.amount === 'string' && /^\d+\.\d{2}$/.test(row.amount) && !/^0+\.00$/.test(row.amount) &&
    typeof row.category === 'string' && typeof row.description === 'string' &&
    row.currency === 'UAH';
}

const validTransactions = (value) => Array.isArray(value) && value.every(validTransaction);

export class ApiError extends Error {
  constructor(message, status = 0, fieldErrors = {}, outcomeUnknown = false) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
    this.outcomeUnknown = outcomeUnknown;
  }
}

const boundedText = (value, limit) => typeof value === 'string' && value.trim().length > 0 && [...value].length <= limit;
const nonnegativeMoney = (value) => typeof value === 'string' && value.length <= 100 && /^[0-9]+\.[0-9]{2}$/.test(value);
export function validAiAnalysis(value) {
  return value && validCalendarDate(value.period_start) && validCalendarDate(value.period_end) &&
    value.period_start <= value.period_end && value.currency === 'UAH' &&
    Number.isSafeInteger(value.transaction_count) && value.transaction_count >= 0 &&
    nonnegativeMoney(value.total_income) && nonnegativeMoney(value.total_expense) &&
    typeof value.balance === 'string' && value.balance.length <= 101 && money.test(value.balance) &&
    boundedText(value.summary, 1200) &&
    ['risks', 'advice'].every((key) => Array.isArray(value[key]) && value[key].length <= 5 && value[key].every((text) => boundedText(text, 500))) &&
    Array.isArray(value.top_expense_categories) && value.top_expense_categories.length <= 5 &&
    value.top_expense_categories.every((item) => item && boundedText(item.category, 100) &&
      nonnegativeMoney(item.amount) && typeof item.share_percent === 'string' &&
      /^(?:100\.00|[0-9]{1,2}\.[0-9]{2})$/.test(item.share_percent));
}

export async function analyzeTransactions(password, signal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  let timer;
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  signal?.addEventListener('abort', abort, { once: true });
  const deadline = new Promise((_, reject) => {
    controller.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    // Backend permits 10 seconds for DB + up to 120 seconds for Gemini.
    timer = setTimeout(abort, 140000);
  });
  try {
    return await Promise.race([deadline, (async () => {
      const response = await fetch('/api/ai/analyze-transactions', {
        method: 'POST', headers: { Authorization: `Bearer ${password}` },
        credentials: 'omit', cache: 'no-store', redirect: 'error', signal: controller.signal,
      });
      if (!response.ok) {
        const messages = {
          401: 'Неправильний пароль. Введіть його повторно.',
          403: 'Локальний захист відхилив запит. Відкрийте панель за локальною адресою.',
          429: 'Досягнуто ліміту AI-запитів. Зачекайте перед наступною спробою.',
          502: 'AI повернув непридатну відповідь. Повторіть аналіз пізніше вручну.',
          503: 'AI-аналіз тимчасово недоступний або не налаштований на сервері.',
          504: 'Час очікування AI вичерпано. Повторіть спробу пізніше вручну.',
        };
        const raw = response.headers.get('Retry-After');
        const retryAfter = raw && /^[0-9]{1,6}$/.test(raw) ? Math.min(Number(raw), 172800) : null;
        const message = messages[response.status] || 'Не вдалося виконати AI-аналіз. Спробуйте пізніше.';
        throw new ApiError(message + (response.status === 429 && retryAfter ? ` Зачекайте щонайменше ${retryAfter} с.` : ''), response.status);
      }
      let data;
      try { data = await response.json(); } catch { throw new ApiError('AI API повернув некоректну відповідь.'); }
      if (response.status !== 200 || !validAiAnalysis(data)) throw new ApiError('Формат AI-аналізу не відповідає контракту сервера.');
      return data;
    })()]);
  } catch (error) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (controller.signal.aborted) throw new ApiError('Час очікування AI вичерпано. Запит міг бути врахований сервісом; повторіть його пізніше вручну.');
    if (error instanceof ApiError) throw error;
    throw new ApiError('Не вдалося з’єднатися з AI API. Повторіть спробу пізніше вручну.');
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

async function httpError(response, writing = false) {
  let data;
  try { data = await response.json(); } catch { /* Never expose raw response bodies. */ }
  const fields = {};
  if (response.status === 422 && Array.isArray(data?.detail)) {
    for (const item of data.detail) {
      if (['type', 'amount', 'category', 'description', 'date'].includes(item?.field)) {
        fields[item.field] = 'Перевірте значення цього поля.';
      }
    }
  }
  const disabled = response.status === 503 && data?.detail === 'Writing is disabled.';
  const messages = {
    401: 'Неправильний пароль. Введіть його повторно.',
    403: 'Локальний захист відхилив запит. Відкрийте dashboard за локальною адресою.',
    422: writing === 'delete' ? 'Некоректний ідентифікатор операції.' : 'Перевірте поля форми.',
    ...(writing === 'delete' ? { 404: 'Операція вже недоступна. Оновіть список.' } : {}),
  };
  const knownFailures = writing === 'delete' ? [401, 403, 404, 422] : [401, 403, 422];
  const unknown = Boolean(writing) && !knownFailures.includes(response.status) && !disabled;
  return new ApiError(disabled ? 'Адміністративний запис вимкнений на сервері.' :
    messages[response.status] || (writing === 'delete' ? 'Видалення не підтверджено. Перевірте список перед повторною дією.' : writing ? 'Збереження не підтверджено. Перевірте список операцій перед повторним надсиланням.' :
      'Не вдалося отримати дані API. Перевірте локальний backend.'), response.status, fields, unknown);
}

export function validTransactionId(id) {
  return typeof id === 'string' && /^[0-9]{1,19}$/.test(id) &&
    !/^0+$/.test(id) && (id.length < 19 || id <= '9223372036854775807');
}

export async function deleteTransaction(id, password) {
  if (!validTransactionId(id)) throw new ApiError('Некоректний ідентифікатор операції.', 422);
  const controller = new AbortController();
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new DOMException('DELETE deadline exceeded', 'AbortError'));
    }, 15000);
  });
  try {
    // The deadline includes body parsing. Race also bounds a stalled body reader
    // even if it does not promptly reject after the transport is aborted.
    await Promise.race([deadline, (async () => {
      const response = await fetch(`/api/transactions/${id}`, {
        method: 'DELETE', credentials: 'omit', redirect: 'error', cache: 'no-store',
        headers: { Authorization: `Bearer ${password}` }, signal: controller.signal,
      });
      if (response.status === 204) return;
      if (!response.ok) throw await httpError(response, 'delete');
      throw new ApiError('Відповідь сервера неоднозначна. Перевірте список перед повторною дією.', response.status, {}, true);
    })()]);
  } catch (error) {
    if (controller.signal.aborted) {
      throw new ApiError('Час очікування видалення вичерпано (15 секунд). Результат не підтверджено: спершу перевірте список операцій.', 0, {}, true);
    }
    if (error instanceof ApiError) throw error;
    throw new ApiError('З’єднання перервано. Видалення не підтверджено: спершу перевірте список операцій.', 0, {}, true);
  } finally {
    clearTimeout(timer);
  }
}

async function request(path, validate, signal, transform = (data) => data) {
  let response;
  try { response = await fetch(path, { signal, cache: 'no-store', credentials: 'omit' }); }
  catch (error) {
    if (signal?.aborted) throw error;
    throw new Error('Не вдалося з’єднатися з API. Перевірте локальний backend і спробуйте ще раз.');
  }
  if (!response.ok) throw await httpError(response);
  let data;
  try { data = await response.json(); }
  catch { throw new Error('API повернув некоректну відповідь. Спробуйте ще раз.'); }
  if (!validate(data)) throw new Error('Формат відповіді API не відповідає очікуваному.');
  return transform(data, response);
}

export async function createTransaction(payload, password) {
  let response;
  try {
    response = await fetch('/api/transactions', {
      method: 'POST', redirect: 'error', credentials: 'omit', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${password}` },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ApiError('З’єднання перервано. Результат невідомий: перевірте список операцій перед повторним надсиланням.', 0, {}, true);
  }
  if (!response.ok) throw await httpError(response, true);
  let data;
  try { data = await response.json(); } catch { /* A successful write may already exist. */ }
  if (response.status !== 201 || !validTransaction(data)) {
    throw new ApiError('Сервер не підтвердив коректну відповідь. Перевірте список операцій перед повторним надсиланням.', response.status, {}, true);
  }
  return data;
}

export function todayKyiv(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Kyiv', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const get = (name) => parts.find((part) => part.type === name).value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}

export function formatCalendarDate(value) {
  if (!validCalendarDate(value)) return '—';
  const [year, month, day] = value.split('-');
  return `${day}.${month}.${year}`;
}

export const getSummary = (signal) => request('/api/summary', validSummary, signal);
export function getTransactionPage(page = 0, signal, type = 'all') {
  if (!Number.isSafeInteger(page) || page < 0) throw new Error('Некоректна сторінка.');
  if (!['all', 'income', 'expense'].includes(type)) throw new Error('Некоректний тип операцій.');
  return request(`/api/transactions?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}&type=${type}`,
    validTransactions, signal, (items, response) => {
      const raw = response.headers.get('X-Total-Count');
      if (raw === null || !/^[0-9]+$/.test(raw) || !Number.isSafeInteger(Number(raw))) {
        throw new Error('API повернув некоректну кількість операцій.');
      }
      return { items, total: Number(raw) };
    });
}

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
