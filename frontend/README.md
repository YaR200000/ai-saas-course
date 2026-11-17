# React Admin Dashboard — урок 7, блок 3

Потрібен Node.js 22.12+ або актуальний LTS та npm. З кореня репозиторію:

```powershell
cd frontend
npm install
npm run dev
```

Відкрити **http://127.0.0.1:5173**. Окремо з кореня запустити FastAPI за
інструкцією [API](../docs/transactions-api.md), вибравши перевірений внутрішній
API_ALLOWED_USER_ID. Frontend не читає backend .env: Vite envDir=false вимикає
завантаження env-файлів; секретна конфігурація для frontend не потрібна.

## Компоненти й дані

- `App.jsx`: оболонка, сторінка операцій, окремі повторні завантаження.
- `components.jsx`: SummaryCards, TransactionsTable та ErrorState.
- `useResource.js`: незалежні стани запитів, скасування при зміні сторінки або
  демонтуванні. Помилка одного endpoint не приховує дані іншого.
- `api.js`: тільки відносні `/api/summary` та `/api/transactions`, перевірка
  JSON-контрактів. Гроші форматуються без перетворення на float, ID — рядки.

Картки показують всі операції користувача, таблиця — по 20. Порядок залишається
таким, як повернув backend. Загальної кількості API не повертає: кнопка «Далі»
доступна для повної сторінки; після останньої повної сторінки може бути порожня
з можливістю повернутися. Зміни записів між запитами можуть зсувати offset.
Баланс розрахунковий: доходи поки не реєструються. Дати — Europe/Kyiv.
Є loading, error з повторною спробою та empty states; усі робочі дані тільки з API.

## Локальний proxy та безпека

Vite слухає 127.0.0.1:5173, strictPort не дозволяє непомітно змінити порт.
`/api` проксіюється на 127.0.0.1:8000 з `changeOrigin: false`: зберігаються
Host 127.0.0.1:5173 та браузерний Origin того самого frontend. Backend приймає
цей локальний Host і однаковий Origin; Fetch Metadata залишається same-origin,
TCP-клієнт backend — loopback. Не додаються X-Forwarded-* заголовки.
FastAPI змінювати не потрібно. Додатковий middleware Vite перевіряє loopback,
локальний Host, Origin та Fetch Metadata до proxy. CORS вимкнено.
Це локальний однокористувацький інтерфейс без авторизації; не публікувати через
тунель або reverse proxy. Інші локальні процеси мають доступ.

## Перевірки

```powershell
npm test
npm run build
npm run preview
```

Тести використовують Node test runner: контракти API-клієнта, форматування,
рендер компонентів через React SSR та справжній Vite proxy з ізольованим
HTTP-сервером. Дані у тестах — лише фікстури, вони не входять до робочого dashboard.
Тести не запускають FastAPI, не читають секрети й не підключаються до Neon.
`npm run preview` дозволяє локально переглянути dist з тим самим proxy;
це не production-сервер. Статична публікація dist без локального backend/proxy
не працюватиме. node_modules, dist, .tools та логи виключені з Git.
