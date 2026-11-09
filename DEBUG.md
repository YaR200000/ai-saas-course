# Lesson 4: Logs, Errors & Debugging

## Помилка №1: Missing BOT_TOKEN

### Команда запуску

```powershell
.\.venv\Scripts\python.exe -m app.main
```

### Повідомлення про помилку

```text
2026-11-09 22:42:31,941 | ERROR | BOT_TOKEN не задано або порожній. Запуск бота припинено.
Помилка: BOT_TOKEN не задано. Встановіть змінну середовища BOT_TOKEN або додайте її до файлу .env.
```

### Причина

Для тестування тимчасово закоментували рядок BOT_TOKEN у локальному файлі `.env`. Змінна BOT_TOKEN у PowerShell була відсутня.

### Traceback і діагностика

Traceback відсутній, оскільки код викликає `SystemExit` із повідомленням. Головний діагностичний рядок — ERROR про відсутній токен.

### Гіпотеза

Програма не може отримати токен ні зі змінних середовища, ні з `.env`.

### Виправлення

Прибрали символ `#` перед BOT_TOKEN у `.env` та зберегли файл.

### Перевірка

Після відновлення BOT_TOKEN виконали повторний запуск:

```powershell
.\.venv\Scripts\python.exe -m app.main
```

Отримано такі повідомлення:

```text
2026-11-09 22:54:18,935 | INFO | bot started
2026-11-09 22:54:18,935 | INFO | Start polling
2026-11-09 22:54:19,085 | INFO | Run polling for bot ...
```

Висновок: бот успішно пройшов перевірку токена та розпочав polling.

Під час завершення тесту з'явилися `CancelledError`, `KeyboardInterrupt` і повідомлення про мережеве відключення. Це окремі події під час завершення роботи, а не повторення помилки Missing BOT_TOKEN. Причину мережевого відключення точно не встановлено.

### AI prompt — приклад запиту

Наведений нижче запит є прикладом, а не фактично надісланим раніше запитом.

```text
Python-бот завершує запуск із SystemExit та ERROR «BOT_TOKEN не задано або порожній».
Рядок BOT_TOKEN у .env тимчасово закоментований, а змінна в PowerShell відсутня.
Поясни причину та запропонуй виправлення і перевірку без розкриття токена.
```

## Помилка №2: ModuleNotFoundError

Помилку відтворили окремою командою, без змін у коді Telegram-бота.

### Фактична команда запуску

```powershell
.\.venv\Scripts\python.exe -c "import nonexistent_training_module"
```

### Фактичний traceback

```text
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import nonexistent_training_module
ModuleNotFoundError: No module named 'nonexistent_training_module'
```

### Що сталося і де виникла помилка

Python не зміг імпортувати модуль `nonexistent_training_module`. Помилка виникла в першому рядку коду, переданого через `python -c`. У traceback цей код позначено як `<string>`.

Головний рядок traceback:

```text
ModuleNotFoundError: No module named 'nonexistent_training_module'
```

### Гіпотеза

Модуль не існує або не встановлений у поточному Python-середовищі.

### Фактична причина

Для навчального тесту навмисно використали вигадану назву модуля `nonexistent_training_module`.

### Спосіб виправлення

Видалити неправильний імпорт або замінити його на імпорт наявного модуля.

### Перевірка

Фактично виконана команда:

```powershell
.\.venv\Scripts\python.exe -c "import logging; print('Import successful: logging')"
```

Фактичний результат:

```text
Import successful: logging
```

Імпорт стандартного модуля `logging` пройшов успішно. Це підтверджує, що Python може імпортувати наявні модулі з поточного середовища.

Вигаданий модуль не встановлювали: неправильний імпорт замінили на коректний для окремого навчального тесту.

### AI prompt — приклад запиту

Наведений нижче запит є прикладом, а не фактично надісланим раніше запитом.

```text
Проаналізуй traceback після запуску Python з командою -c "import nonexistent_training_module":
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import nonexistent_training_module
ModuleNotFoundError: No module named 'nonexistent_training_module'
Поясни, де виникла помилка, що означає останній рядок і як виправити імпорт.
```
