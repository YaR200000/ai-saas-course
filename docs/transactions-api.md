# Локальні Transactions та Summary API — урок 7, блоки 1–2

API запускається окремо від Telegram polling, використовує моделі та фабрики
з `app/models.py` і `app/database.py`. Власний engine створюється в FastAPI
lifespan і закривається на завершенні. Кожен запит має окрему session.
Немає створення таблиць, міграцій або запису даних.

## Конфігурація та запуск у PowerShell

Встановлення лише в локальне віртуальне середовище:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Оператор самостійно задає `API_ALLOWED_USER_ID` — додатний **внутрішній users.id**,
не Telegram ID. Значення `1` у шаблоні є лише прикладом: його потрібно перевірити.
`DATABASE_URL` налаштовується на сервері так само, як для бота. Секрети не
передаються браузеру. Для локального запуску наявний `.env` завантажує Uvicorn:

```powershell
$env:API_ALLOWED_USER_ID = '1' # замініть на перевірений users.id
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000 --no-proxy-headers --env-file .env
```

Імпорт API не читає `.env`. Відсутня/некоректна конфігурація користувача
блокує запуск. API не потребує BOT_TOKEN і не запускає бота.

## Доступ та контракт

Відкрити `http://127.0.0.1:8000/api/transactions?limit=50&offset=0`.
Повертається JSON-масив (порожній `[]`, якщо даних немає):

```json
[{"id":"3","created_at":"2026-11-17T09:00:00Z","type":"expense","amount":"125.50","category":"Інше","description":"кава","currency":"UAH"}]
```

ID передається рядком для точного збереження BIGINT у JavaScript. Сума —
десятковий рядок з двома знаками. Дата — ISO 8601 (у PostgreSQL timezone-aware).
Валюта UAH і type expense відображають поточні домовленості, не нові поля БД.
JOIN отримує назву категорії. Фільтр власника задається сервером; параметри
user_id/telegram_id не впливають на нього. Сортування created_at DESC, id DESC.
limit: 1–100 (default 50), offset: 0–9223372036854775807 (default 0).
Некоректна пагінація — 422, помилка читання — контрольований 503.
Усі відповіді мають Cache-Control: no-store. Telegram-поля не повертаються.

Сервер прив'язується до IPv4 loopback. Додатково перевіряються адреса клієнта,
Host (localhost/127.0.0.1), Origin та Sec-Fetch-Site, щоб обмежити зовнішні
браузерні запити й DNS rebinding. CORS не ввімкнено, forwarded headers не
довіряються. Не запускати з 0.0.0.0, не публікувати через proxy/тунель.

Це локальний однокористувацький прототип без вебавторизації. Інші процеси та
користувачі цього комп'ютера можуть звернутися до API. Для зовнішнього доступу
потрібні автентифікація та авторизація. Майбутній frontend потребуватиме
узгодженого same-origin маршруту; довільні інші origins наразі блокуються.
API виконує тільки SELECT, але це не замінює окремої read-only ролі PostgreSQL.
Схема Neon має вже відповідати очікуванням проєкту; цей блок її не перевіряє
та не змінює. Можливі окремі пули з'єднань бота й API.

## Financial Summary API

`GET /api/summary` повертає підсумки всіх операцій дозволеного користувача:

```json
{"total_income":"0.00","total_expense":"245.50","balance":"-245.50"}
```

Цифри — приклад. `total_expense` обчислюється SQL SUM над NUMERIC amount із
фільтром за серверним API_ALLOWED_USER_ID, без LIMIT/OFFSET. `total_income`
завжди дорівнює "0.00", оскільки поточна модель підтримує лише витрати.
`balance` = total_income − total_expense; Python використовує Decimal без float.
Усі три значення — рядки з двома десятковими знаками, у домовленій валюті UAH.
Для користувача без операцій SQL NULL замінюється нулем: усі поля "0.00".
Це підсумок облікованих операцій, не підтверджений залишок на банківському рахунку.
Доходи та початковий баланс у поточній моделі не враховуються.

Параметри user_id, limit та offset не змінюють підсумків. Застосовуються ті самі
локальні перевірки доступу та Cache-Control: no-store. Помилка БД — контрольований
503 без SQL, параметрів чи секретів. Схема БД та логіка Telegram-бота не змінені.
Окремі запити transactions/summary можуть побачити різні стани, якщо між ними
бот запише нову витрату; спільного snapshot між HTTP-запитами немає.

## Перевірки без Neon

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_transactions_api.py tests/test_expense_handler.py tests/test_test_resources.py -p no:cacheprovider
```

API-тести виконують справжній SQLAlchemy SELECT у тимчасовій in-memory SQLite,
із підміною лише session factory/lifespan engine. Це перевіряє JOIN, фільтр,
сортування та пагінацію, але не сумісність TLS/asyncpg із живою Neon.
Існуючі інтеграційні тести PostgreSQL цим запуском не викликаються.
