# Урок 8: тип та календарна дата операції

Міграція `migrations/002_transaction_type_date.sql` підготовлена для ручного
перегляду. Застосування до робочої Neon не є частиною цього блоку.
Спочатку потрібна схема після `001_expense_messages.sql`. Старий SQL не змінено.

## Контракт

- `type VARCHAR(7) NOT NULL DEFAULT 'expense'`, CHECK: income або expense.
- `date DATE NOT NULL`: календарна дата операції за Europe/Kyiv.
- `created_at TIMESTAMPTZ` залишається фактичним часом створення.
- Сума залишається додатною NUMERIC(12,2) незалежно від типу.
- Старі записи отримують expense та дату з created_at за Europe/Kyiv.
- Серверні defaults підтримують INSERT без нових полів. Telegram явно задає
  expense і SQL-вираз київської дати. CURRENT_TIMESTAMP означає початок транзакції.
  Дата не залежить від timezone сесії чи наявності tzdata у Windows.

## Перевірка до застосування

1. Перевірити цільову БД та резервне відновлення, версію PostgreSQL, наявні
   колонки/constraints та застосування 001. Не повторювати 001 автоматично.
2. На disposable локальній PostgreSQL виконати тести нижче. Вони створюють
   випадкову тестову схему та прибирають тільки її через наявну фікстуру.
   Не використовувати робочий DATABASE_URL; .env тести не читають.
3. За окремим погодженням повторити на ізольованій гілці Neon.
4. Приватно зафіксувати baseline старих полів усіх рядків. Для двох очікуваних
   витрат 120/75 сума дорівнює 195. Після міграції порівняти всі старі поля,
   включно з Telegram ID, а не тільки COUNT/SUM. Усі старі type мають бути expense;
   date має дорівнювати (created_at AT TIME ZONE 'Europe/Kyiv')::date.

Після налаштування ОКРЕМОЇ локальної disposable БД expense_test:

```powershell
$env:EXPENSE_TEST_DB_DISPOSABLE = 'yes'
# EXPENSE_TEST_DATABASE_URL налаштувати приватно: postgresql+asyncpg, loopback,
# database expense_test, без query options. Не копіювати робочу URL.
.\.venv\Scripts\python.exe -B -m pytest tests/test_transaction_model.py tests/test_transaction_migration.py tests/test_migration.py tests/test_expense_storage.py tests/test_expense_handler.py -p no:cacheprovider -q
```

Без явного opt-in PostgreSQL-тести пропускаються. SQLite не замінює перевірку
цього SQL. Компіляція моделі та mocked bot tests не доводять роботу міграції.

## Транзакція, блокування та відкат

Скрипт виконується повністю одним з'єднанням: BEGIN/COMMIT, локальні lock_timeout
5s і statement_timeout 30s. ALTER TABLE бере сильне блокування, UPDATE date
торкається всіх старих рядків; на великій таблиці потрібна окрема оцінка часу,
WAL та тривалості блокування. statement_timeout обмежує окремі SQL-команди.
Неочікувана існуюча колонка/constraint спричиняє помилку; IF NOT EXISTS
навмисно не приховує розбіжності схеми. При помилці виконати ROLLBACK на тому
самому з'єднанні; не залишати aborted-транзакцію з блокуваннями.

До COMMIT весь DDL і backfill можна відкотити ROLLBACK. Після COMMIT потрібна
окрема погоджена зворотна міграція. Автоматичного downgrade немає.
За наявності income видалення type втрачає зміст операцій: старий API рахує
всі записи витратами. Видалення date втрачає введені календарні дати.
Не перекласифіковувати доходи й не видаляти дані заради відкату; перевага —
виправленню вперед. Відновлення backup також може втратити нові записи.

GET API та React цього блоку не змінені: вони ще трактують записи як витрати.
До їх наступного оновлення не створювати income у робочому середовищі.
Новий код бота потребує 002; запускати його на старій схемі не можна.
