# Telegram Бот з Мультиками

Telegram бот для перегляду та управління мультфільмами.

## Технології

- Python 3.11+
- aiogram 3.x - Telegram Bot фреймворк
- MongoDB - База даних
- Motor - Асинхронний драйвер для MongoDB

## Структура проекту

```
.
├── bot/
│   ├── handlers/       # Обробники команд та повідомлень
│   ├── database/       # Робота з базою даних
│   ├── utils/          # Допоміжні функції
│   └── config.py       # Конфігурація
├── data/               # Локальні дані
├── main.py             # Точка входу
└── requirements.txt    # Залежності
```

## Встановлення

1. Клонуйте репозиторій
2. Створіть віртуальне середовище:
   ```bash
   python -m venv venv
   source venv/bin/activate  # для Linux/Mac
   # або
   venv\Scripts\activate  # для Windows
   ```

3. Встановіть залежності:
   ```bash
   pip install -r requirements.txt
   ```

4. Скопіюйте `.env.example` в `.env` та заповніть своїми даними:
   ```bash
   cp .env.example .env
   ```

5. Отримайте токен бота у [@BotFather](https://t.me/BotFather)

6. Встановіть та запустіть MongoDB локально або використовуйте MongoDB Atlas

## Запуск

```bash
python main.py
```

## Конфігурація

Всі налаштування знаходяться в `.env` файлі:

- `BOT_TOKEN` - токен вашого Telegram бота
- `MONGODB_URL` - URL для підключення до MongoDB
- `MONGODB_DB` - назва бази даних
- `ADMIN_IDS` - ID адміністраторів (через кому)
