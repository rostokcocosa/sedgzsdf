# Kelta Wallet Mini App — локальный тестовый стенд

Telegram-бот + Telegram Mini App на базе FastAPI, aiogram v3, BIP-39.

## Структура

```
миниапп/
├── app.py           # FastAPI сервер + aiogram v3 бот
├── requirements.txt
├── static/
│   └── index.html   # Mini App (SPA, 5 вкладок)
└── README.md
```

## Установка

```powershell
pip install -r requirements.txt
```

## Запуск

### Режим разработки (без бота, без Telegram)

```powershell
$env:DEV_MODE="true"; python app.py
```

Откройте [http://localhost:8000](http://localhost:8000) — кошелёк работает без initData.

### Полный режим (с ботом)

```powershell
$env:BOT_TOKEN="1234567890:AABBccDDee..."; $env:WEBAPP_URL="https://xxxx.trycloudflare.com"; python app.py
```

## HTTPS-туннель для Mini App

Telegram требует HTTPS для `web_app`. Запустите туннель **в отдельном окне**:

### cloudflared (рекомендуется, бесплатно)

```powershell
cloudflared tunnel --url http://localhost:8000
```

Скопируйте полученный URL вида `https://xxxx.trycloudflare.com` и передайте его как `WEBAPP_URL`.

### ngrok

```powershell
ngrok http 8000
```

Скопируйте `https://xxxx.ngrok-free.app`.

## Переменные окружения

| Переменная  | По умолчанию           | Описание                                   |
|-------------|------------------------|--------------------------------------------|
| `BOT_TOKEN` | —                      | Токен бота от @BotFather                   |
| `WEBAPP_URL`| `http://localhost:8000`| Публичный HTTPS URL (от туннеля)           |
| `DEV_MODE`  | `false`                | `true` — пропустить проверку initData      |
| `PORT`      | `8000`                 | Порт сервера                               |

## Регистрация Mini App в BotFather

1. `/mybots` → выберите бота → **Bot Settings → Menu Button → Edit Menu Button URL**
2. Вставьте HTTPS URL туннеля.

Или через `/setmenubutton` → введите URL.

## Команды бота

| Команда   | Описание                      |
|-----------|-------------------------------|
| `/start`  | Приветствие + кнопка Mini App |
| `/seed`   | Статус seed-фразы             |
| `/status` | Баланс кошелька               |

## Возможности Mini App

| Вкладка      | Функции                                                       |
|--------------|---------------------------------------------------------------|
| 💰 Кошелёк   | Баланс, QR-код, тестовое пополнение, вывод, история          |
| 💸 Переводы  | Перевод по адресу, создание / активация чеков                |
| 📋 Счета     | Выставление счёта, просмотр, оплата                          |
| 🔄 Своп      | Обмен TON/USDT/BTC по фиксированным тестовым курсам          |
| 🤝 P2P       | Список ордеров, создание BUY/SELL, закрытие ордера           |

## API

Все эндпоинты принимают заголовок `X-Init-Data` (Telegram initData).

```
GET  /api/wallet
POST /api/wallet/connect     { seed: "слова..." | "generate" }
POST /api/wallet/deposit     { asset, amount }
POST /api/wallet/withdraw    { asset, amount, address }
GET  /api/wallet/history
POST /api/transfer           { asset, amount, address, comment }
POST /api/check/create       { asset, amount, comment }
GET  /api/check/{code}
POST /api/check/{code}/activate
POST /api/invoice/create     { currency, amount, comment }
GET  /api/invoice/{id}
POST /api/invoice/{id}/pay
GET  /api/swap/rate?from_asset=TON&to_asset=USDT&amount=1
POST /api/swap               { from_asset, to_asset, amount }
GET  /api/p2p/orders
POST /api/p2p/order          { type: BUY|SELL, asset, amount, price, currency }
POST /api/p2p/order/{id}/take
GET  /api/qr/{address}       → PNG QR-код
```
