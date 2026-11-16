import asyncio
import logging
import os
from pathlib import Path
from aiogram.enums import ChatType
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import Message
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import create_database_engine, create_session_factory
from app.expenses import parse_expense, save_expense


logger = logging.getLogger(__name__)


async def answer_expense(message: Message, response: str) -> None:
    """Never propagate delivery exceptions or log their confidential context."""
    try:
        await message.answer(response)
    except Exception:
        logger.error("expense_confirmation_delivery_failed")


async def start_handler(
    message: Message,
    session_factory: async_sessionmaker,
) -> None:

    logger.info("received /start command")

    try:
        async with session_factory() as session:
            result = await session.scalar(text("SELECT 1"))
        if result != 1:
            raise RuntimeError("Unexpected connection check result")
    except Exception:
        # Do not expose connection details, SQL parameters or traceback.
        logger.error("start_database_check_failed")
        response = "Привіт! База даних тимчасово недоступна. Спробуйте пізніше."
    else:
        logger.info("start_database_check_passed")
        response = "Привіт! Я працюю через Docker з автоматичним оновленням! 🐳🚀"

    # Deliver outside except so a delivery failure cannot chain a DB exception.
    try:
        await message.answer(response)
    except Exception:
        logger.error("start_response_delivery_failed")


async def help_handler(message: Message) -> None:
    logger.info("received /help command")
    await message.answer(
        "🤖 Доступні команди:\n"
        "/start — привітання\n"
        "/help — список доступних команд\n"
        "/expense 125.50 кава — запис витрати в UAH; лише приватний чат"
    )



async def expense_handler(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker,
) -> None:
    if message.chat.type != ChatType.PRIVATE:
        await answer_expense(message, "Команда /expense доступна лише в приватному чаті з ботом.")
        return
    if message.from_user is None:
        await answer_expense(message, "Не вдалося визначити користувача Telegram.")
        return
    try:
        amount, description = parse_expense(command.args)
    except ValueError as error:
        validation_error = str(error)
    else:
        validation_error = None
    if validation_error is not None:
        await answer_expense(message, validation_error)
        return

    try:
        created = await save_expense(
            session_factory,
            telegram_id=message.from_user.id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            amount=amount,
            description=description,
        )
    except Exception:
        # Never pass database exception text, parameters or traceback to logging.
        logger.error("expense_storage_failed")
        response = (
            "Не вдалося підтвердити збереження. Не надсилайте нову команду "
            "одразу: витрату могло бути збережено. Зверніться до адміністратора."
        )
    else:
        if created:
            response = f"Витрату {amount:.2f} UAH збережено. Категорія: Інше."
        else:
            response = "Це повідомлення вже оброблено."

    # Outside the exception block: delivery must not inherit a database error.
    await answer_expense(message, response)


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
    dispatcher.message.register(expense_handler, Command("expense"))

    engine = create_database_engine()
    session_factory = create_session_factory(engine)

    try:
        async with Bot(token=token) as bot:
            logger.info("bot started")
            await dispatcher.start_polling(
                bot,
                session_factory=session_factory,
            )
    finally:
        await engine.dispose()
        logger.info("database engine disposed")



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
