# Урок 8, блок B: локальний Backend API

## Передумови та схема

API запускається окремо від Telegram. Імпорт не читає .env. DATABASE_URL,
API_ALLOWED_USER_ID та ADMIN_PASSWORD надходять із середовища; за потреби
наявний env-файл завантажує оператор через Uvicorn, а не модулі застосунку.
API_ALLOWED_USER_ID — перевірений внутрішній users.id, ніколи не Telegram ID.

Під час lifespan виконується read-only інспекція каталогу PostgreSQL: колонки,
NOT NULL, типи type/date/amount, defaults, CHECK, валідованість constraints,
унікальність категорії/Telegram-пари та зовнішні ключі операції.
Потрібна схема після 001 і 002. Застаріла/недоступна схема блокує запуск із
контрольованим повідомленням. Немає автоматичного DDL, міграцій або create_all.

Робоча Neon до 002 несумісна з новим API та вже оновленим ботом. Старий GET
міг працювати, оскільки не вибирав type/date. Спочатку окремо погодити й
застосувати 002, зберігши baseline двох старих витрат 120/75 та резервне
відновлення; потім перезапустити процеси, щоб не повторно використовувати
prepared statements зі старою схемою. Цей блок не застосовує SQL до Neon.

## Доступ

Зберігаються loopback, Host/Origin/Fetch Metadata, no-store, nosniff та вимкнений
CORS. Не публікувати через зовнішню адресу або тунель. GET не потребують пароля.

POST захищений спільною dependency require_admin, придатною для майбутнього
DELETE. ADMIN_PASSWORD читається тільки на startup, порівняння UTF-8 bytes —
secrets.compare_digest. Порожня/відсутня конфігурація вимикає запис (503),
але залишає GET. Заголовок запиту: Authorization: Bearer <введений пароль>.
Відсутній/некоректний пароль — 401 з WWW-Authenticate: Bearer. Перевірка
передує JSON parsing: навіть malformed JSON без credentials отримує 401.

Не передавати пароль у URL, тілі операції, VITE_*, Git або frontend bundle.
Не зберігати в localStorage; майбутній UI може тримати введений пароль у пам'яті.
Не експортувати HAR із credentials. Логи не містять headers, payload, SQL
або exception text. Це спільний локальний секрет без персональних ролей,
rate limiting і production-сесій. Для мережевого розгортання потрібні HTTPS
і повноцінна автентифікація. Локальні процеси й надалі можуть читати GET.

## Контракти

POST /api/transactions, Content-Type: application/json:

```json
{"type":"income","amount":"300.00","category":"Зарплата","description":"Виплата","date":"2026-11-21"}
```

Усі поля обов'язкові, невідомі заборонені. amount — тільки десятковий рядок
без експоненти, float, NaN/Infinity чи округлення: >0, <=9999999999.99,
максимум 2 знаки. category після trim: 1–100 символів; description: 1–2000.
NUL відхиляється. date — календарна YYYY-MM-DD; майбутні дати дозволені.
Категорії з різним регістром залишаються різними, семантика точних назв збережена.

Власник береться лише із сервера. Існуючий User перевіряється перед записом.
Одна транзакція створює/знаходить категорію через ON CONFLICT та вставляє
операцію; Telegram-поля NULL. Помилка відкочує й нову категорію. Лише після
commit повертається 201 із представленням операції:

```json
{"id":"17","created_at":"2026-11-21T10:00:00Z","date":"2026-11-21","type":"income","amount":"300.00","category":"Зарплата","description":"Виплата","currency":"UAH"}
```

GET /api/transactions повертає масив такого формату, справжній type та date.
Порядок created_at DESC, id DESC; limit 1–100 (default 50), offset >=0.
ID і гроші — рядки. Немає фільтрів і DELETE.

GET /api/summary одним SELECT агрегує всі операції власника, без пагінації:

```json
{"total_income":"300.00","total_expense":"195.00","balance":"105.00"}
```

Обчислення — NUMERIC/Decimal; відсутні суми дають 0.00. Balance — різниця,
не підтверджений банківський залишок. Список і summary — різні snapshots.

422: контрольовані помилки без echo вводу. 403: порушення локального доступу.
503: запис вимкнений або збереження не підтверджено/БД недоступна. Commit може
мати неоднозначний результат при втраті з'єднання: немає автоматичного retry.
Перед ручним повтором оновити список. HTTP idempotency ще не реалізована.

## React та наступний блок

React не змінено: картки приймають той самий summary JSON, але старі пояснення
ще говорять про відсутність доходів. API-клієнт таблиці приймає лише expense,
компонент завжди показує мінус. До frontend-блоку не створювати income в
робочому середовищі. Не маскувати доходи як витрати заради старого dashboard.

## Перевірки

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests -p no:cacheprovider -q -rs
```

Реальні записи використовують тільки guarded local_engine: потрібні
EXPENSE_TEST_DB_DISPOSABLE=yes та окрема EXPENSE_TEST_DATABASE_URL на локальну
expense_test. Немає fallback на DATABASE_URL або читання .env. Без opt-in
PostgreSQL-тести пропускаються. SQLite GET-тести не доводять роботу PostgreSQL.
Dashboard integration піднімає лише ізольовані loopback HTTP/Vite та SQLite.
