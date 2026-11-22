# Урок 8, блок B: локальний Backend API

## Урок 8, блок D: фізичне видалення

`DELETE /api/transactions/{id}` без тіла, з `Authorization: Bearer <пароль>`.
Використовує той самий require_admin та middleware. Credentials перевіряються
до ID. ID: десятковий додатний BIGINT 1–9223372036854775807, без float.
Клієнтські user_id/headers не надають прав: власник тільки API_ALLOWED_USER_ID.

Одна транзакція виконує DELETE WHERE id=:id AND user_id=:owner RETURNING id.
Немає окремого SELECT власника. Категорії, користувачі й інші записи не змінюються.
204 повертається тільки після успішного виходу з transaction context (commit),
без JSON/тіла. Відсутній і чужий запис мають однаковий 404 Transaction not found.
Повторний DELETE дає 404; два конкурентні DELETE — один 204, другий 404.

401: credentials відсутні/неправильні; 403: локальний захист; 422: ID;
503: запис вимкнено або помилка транзакції. При транзакційній помилці:
`{"detail":"Deletion could not be confirmed; refresh before retrying."}`.
Ця відповідь не стверджує ні успішне видалення, ні гарантовану відсутність зміни.
SQL-помилка до commit виходить через session.begin(), який відкочує транзакцію.
Core DELETE виконується негайно, сесія нова, pending ORM objects відсутні;
явний flush не потрібний. Commit context може виконувати flush, але тут йому
нема що записувати. При commit error SQLAlchemy намагається відкотити активну
транзакцію; розрив з'єднання після server commit не дозволяє довести результат.
Немає автоматичного retry або грубого визначення результату лише за фазою.
Навіть помилка закриття сесії після commit не є доказом невиконання операції.

Frontend цього блоку не змінено. Майбутній клієнт має обробляти 204 без json(),
після успіху повторити GET списку й summary, а після мережевого збою спершу
перевірити стан. HTTP-ідемпотентність не означає однаковий статус повторів:
перший запит прибирає рядок, наступний уже нічого не змінює і повертає 404.

Видалення незворотне через dashboard і не створює журнал історії. Фізичне
видалення Telegram-операції прибирає також ключ дедуплікації повідомлення:
повторна обробка старого повідомлення потенційно створить витрату знову.
Бот і механізм дедуплікації цього блоку не змінені. Міграцій не потрібно.

Перевірки без міграційних наборів:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_transaction_delete.py tests/test_transaction_delete_pg.py tests/test_transactions_api.py tests/test_transaction_post.py tests/test_expense_handler.py tests/test_expense_storage.py -p no:cacheprovider -q -rs
```

DELETE PostgreSQL-тести потребують наявного opt-in disposable local_engine
з conftest: окрема локальна expense_test, випадкова ізольована схема. Вони
не запускають SQL-міграції. Ін'єкція помилки перед commit перевіряє rollback,
але не моделює втрату підтвердження вже виконаного commit у мережі.

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
ID і гроші — рядки. Фільтрів немає; DELETE описаний у блоці D вище.

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
