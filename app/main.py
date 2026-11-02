import asyncio
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv


async def start_handler(message: Message) -> None:
    await message.answer("Привіт! Я працюю через Docker з автоматичним оновленням! 🐳🚀")


async def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Помилка: BOT_TOKEN не задано. Встановіть змінну середовища "
            "BOT_TOKEN або додайте її до файлу .env."
        )

    dispatcher = Dispatcher()
    dispatcher.message.register(start_handler, CommandStart())

    async with Bot(token=token) as bot:
        await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
