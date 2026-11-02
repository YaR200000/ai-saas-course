# AI SaaS Course

## Project Goal
Help beginners learn programming with AI.

## Target User
Beginner programmers and students.

## Basic Features
- AI coding assistant
- Code explanations
- Learning progress tracking

## Development Plan
- Build the first prototype
- Test the AI assistant
- Improve the user experience

## Урок 3. Telegram-бот на Python та Docker

### Призначення та можливості

Навчальний Telegram-бот демонструє асинхронні обробники команд на Python з aiogram 3.x. Бот отримує повідомлення через polling і підтримує дві команди:

- `/start` — надсилає привітання.
- `/help` — показує список доступних команд українською.

### Структура файлів

```text
ai-saas-course/
├── app/
│   ├── __init__.py     # Python-пакет застосунку
│   └── main.py         # Обробники команд і запуск polling
├── requirements.txt   # aiogram, python-dotenv, watchfiles
├── Dockerfile         # Образ Python 3.12 slim і встановлення залежностей
├── compose.yaml       # Сервіс bot, змінні середовища та режим розробки
├── .dockerignore      # Виключення секретів і зайвих файлів зі збірки
├── .gitignore         # Виключення локальних файлів із Git
├── .env.example       # Шаблон змінних без справжнього токена
├── .env               # Локальний файл із токеном, створюється вручну
└── README.md          # Документація проєкту
```

### Вимоги для запуску

- Для локального запуску: Python 3.12 з pip і Windows PowerShell.
- Для запуску в контейнері: встановлений і запущений Docker Desktop з Docker Compose (`docker compose`) та підтримкою Linux-контейнерів. Локальний Python для цього способу не потрібний.
- Інтернет-з'єднання та Telegram-бот із токеном, отриманим у BotFather.

Усі команди нижче виконуйте з кореня репозиторію `ai-saas-course`.

### Налаштування BOT_TOKEN

Якщо `.env` ще не існує, створіть його з шаблону в PowerShell:

```powershell
Copy-Item .env.example .env
```

Не перезаписуйте вже налаштований `.env`. Відкрийте його локально в редакторі й замініть значення-заглушку `BOT_TOKEN` на власний токен із BotFather. Не публікуйте токен, не вставляйте його в навчальні промпти, скриншоти чи команди термінала.

`.gitignore` виключає `.env` із Git, а `.dockerignore` виключає `.env` і `.env.*` із контексту збірки. Dockerfile не містить токена. Compose передає змінні з `.env` у контейнер під час запуску через `env_file: .env`.

Під час локального запуску `python-dotenv` читає `.env` із кореня проєкту. Якщо `BOT_TOKEN` уже заданий у змінних середовища, він має пріоритет. Без непорожнього токена бот завершує запуск із повідомленням про помилку.

### Локальний запуск у Windows PowerShell

Створіть і активуйте віртуальне середовище, встановіть залежності та запустіть бота:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m app.main
```

Якщо PowerShell блокує скрипт активації, можна запускати Python середовища напряму, без активації:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

Зупиніть локальний процес натисканням `Ctrl+C`. Звичайний локальний запуск не вмикає автоматичний перезапуск. Детальніше про середовища — у [документації Python venv](https://docs.python.org/3/library/venv.html).

### Запуск через Docker Compose

Після налаштування `.env` і запуску Docker Desktop виконайте:

```powershell
docker compose up --build
```

Compose збирає образ із залежностями та запускає сервіс `bot`, показуючи його вивід у терміналі. Локальне віртуальне середовище для цього не використовується. Команда сервісу запускає `python -m app.main` через `watchfiles`; політика `restart: unless-stopped` збережена. Параметр `--build` описаний у [документації Docker Compose](https://docs.docker.com/reference/cli/docker/compose/up/).

Не запускайте одночасно локальну й Docker-версії з одним токеном: обидві намагатимуться отримувати оновлення одного бота через polling. Перед переходом у Docker зупиніть локальний процес через `Ctrl+C`; перед локальним запуском зупиніть контейнер.

### Автоматичний перезапуск під час розробки

У `compose.yaml` каталог `./app` монтується в `/app/app` через bind mount. Збережені локально зміни стають доступними всередині контейнера без повторної збірки образу.

Сервіс виконує команду:

```text
watchfiles --filter python "python -m app.main" /app/app
```

`watchfiles` запускає бота, рекурсивно стежить за Python-файлами каталогу `app` і після змін зупиняє та повторно запускає Python-процес. Сам контейнер при цьому не перебудовується. `WATCHFILES_FORCE_POLLING: "true"` вмикає періодичну перевірку файлів для роботи зі змонтованим каталогом, зокрема на Windows. Це окремий механізм від політики перезапуску контейнера `unless-stopped`.

Після зміни `requirements.txt` або Dockerfile знову виконайте `docker compose up --build`, щоб оновити образ. Деталі роботи спостерігача: [CLI watchfiles](https://watchfiles.helpmanual.io/cli/) та [режим polling](https://watchfiles.helpmanual.io/api/watch/#force-polling).

### Зупинка контейнера

В іншому вікні PowerShell, відкритому в корені проєкту, виконайте:

```powershell
docker compose stop
```

Команда зупиняє контейнер без його видалення. Після явної зупинки політика `unless-stopped` не запускає його знову автоматично. Дивіться [документацію docker compose stop](https://docs.docker.com/reference/cli/docker/compose/stop/).

### Перевірка в Telegram

Запустіть один екземпляр бота й відкрийте в Telegram чат із ботом, для якого налаштували токен.

1. Надішліть `/start`. Очікувана відповідь: «Привіт! Я працюю через Docker з автоматичним оновленням! 🐳🚀». Цей текст однаковий і за локального запуску.
2. Надішліть `/help`. Очікувана відповідь:

   ```text
   🤖 Доступні команди:
   /start — привітання
   /help — список доступних команд
   ```

Для перевірки автоматичного перезапуску під час роботи через Compose змініть текст відповіді в `app/main.py`, збережіть файл, дочекайтеся перезапуску процесу та повторно надішліть відповідну команду в Telegram.

### Робота з Codex і приклади навчальних промптів

У межах уроку за допомогою Codex виконувалися такі завдання:

| Завдання | Короткий приклад промпту |
| --- | --- |
| Створення бота | «Створи Telegram-бота на aiogram 3.x із командою /start і запуском python -m app.main. Читай BOT_TOKEN зі змінних середовища або .env, не показуй секрети». |
| Docker-конфігурація | «Додай Dockerfile, compose.yaml і .dockerignore для бота. Передавай .env лише під час запуску, не копіюй його в образ». |
| Автоматичний перезапуск | «Додай watchfiles і bind mount ./app:/app/app, щоб зміни Python-файлів перезапускали бота в Compose». |
| Команда /help | «Додай окремий асинхронний help_handler із фільтром Command(\"help\") та українським списком команд. Збережи поведінку /start». |
| Документація | «Онови лише README.md: опиши локальний запуск у PowerShell, Docker Compose, автоматичний перезапуск і перевірку команд. Збережи наявний текст і не читай .env». |

У промптах варто зазначати очікувану поведінку, дозволені для зміни файли та спосіб перевірки результату. Справжній токен для роботи над кодом чи документацією Codex не потрібний.
