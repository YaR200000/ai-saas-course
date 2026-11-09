import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv


logger = logging.getLogger(__name__)


async def start_handler(message: Message) -> None:
    logger.info("received /start command")
    await message.answer("Привіт! Я працюю через Docker з автоматичним оновленням! 🐳🚀")


async def help_handler(message: Message) -> None:
    logger.info("received /help command")
    await message.answer(
        "🤖 Доступні команди:\n"
        "/start — привітання\n"
        "/help — список доступних команд"
    )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        logger.error("BOT_TOKEN не задано або порожній. Запуск бота припинено.")
        raise SystemExit(
            "Помилка: BOT_TOKEN не задано. Встановіть змінну середовища "
            "BOT_TOKEN або додайте її до файлу .env."
        )

    dispatcher = Dispatcher()
    dispatcher.message.register(start_handler, CommandStart())
    dispatcher.message.register(help_handler, Command("help"))

    async with Bot(token=token) as bot:
        logger.info("bot started")
        await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
