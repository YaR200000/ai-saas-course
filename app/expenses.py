"""Expense validation and atomic PostgreSQL persistence; no environment loading."""

from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models import Category, Transaction, User


def parse_expense(args: str | None) -> tuple[Decimal, str]:
    parts = (args or "").split(maxsplit=1)
    if not parts:
        raise ValueError("Вкажіть суму та опис. Приклад: /expense 125.50 кава (UAH).")
    try:
        amount = Decimal(parts[0])
    except InvalidOperation:
        raise ValueError("Некоректна сума. Приклад: /expense 125.50 кава.") from None
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Сума має бути додатним скінченним числом.")
    if amount.as_tuple().exponent < -2:
        raise ValueError("Сума може мати не більше двох знаків після крапки.")
    if amount > Decimal("9999999999.99"):
        raise ValueError("Максимальна сума: 9999999999.99 UAH.")
    description = parts[1].strip() if len(parts) > 1 else ""
    if not description:
        raise ValueError("Вкажіть непорожній опис витрати.")
    return amount, description


async def save_expense(session_factory, *, telegram_id: int, chat_id: int,
                       message_id: int, amount: Decimal, description: str) -> bool:
    """Return True for a committed new expense, False for a duplicate message.

    Requires the reviewed schema migration. Use PostgreSQL READ COMMITTED
    (the default): each SELECT sees a concurrent committed conflicting insert.
    Exceptions propagate only to the handler, which must never log their text.
    """
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                insert(User).values(telegram_id=telegram_id)
                .on_conflict_do_nothing(index_elements=[User.telegram_id])
            )
            user_id = await session.scalar(
                select(User.id).where(User.telegram_id == telegram_id)
            )
            await session.execute(
                insert(Category).values(name="Інше")
                .on_conflict_do_nothing(index_elements=[Category.name])
            )
            category_id = await session.scalar(
                select(Category.id).where(Category.name == "Інше")
            )
            expense_id = await session.scalar(
                insert(Transaction).values(
                    user_id=user_id, category_id=category_id, amount=amount,
                    description=description, telegram_chat_id=chat_id,
                    telegram_message_id=message_id,
                ).on_conflict_do_nothing(
                    constraint="uq_transactions_telegram_message"
                ).returning(Transaction.id)
            )
        # Exiting begin() successfully confirms commit before returning.
        return expense_id is not None
