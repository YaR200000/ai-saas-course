"""Atomic PostgreSQL operations for HTTP routes, without environment access."""
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.models import Category, Transaction, User
from app.schemas import TransactionCreate, TransactionResponse


class OwnerUnavailable(Exception):
    pass


async def create_transaction(session_factory, owner_id: int, data: TransactionCreate):
    async with session_factory() as session:
        async with session.begin():
            if await session.scalar(select(User.id).where(User.id == owner_id)) is None:
                raise OwnerUnavailable()
            await session.execute(insert(Category).values(name=data.category).on_conflict_do_nothing(
                index_elements=[Category.name]))
            category_id = await session.scalar(select(Category.id).where(Category.name == data.category))
            row = (await session.execute(insert(Transaction).values(
                user_id=owner_id, category_id=category_id, type=data.type,
                amount=data.amount, description=data.description, date=data.date,
                telegram_chat_id=None, telegram_message_id=None,
            ).returning(Transaction.id, Transaction.created_at))).one()
            response = TransactionResponse(
                id=str(row.id), created_at=row.created_at, date=data.date,
                type=data.type, amount=format(data.amount, ".2f"),
                category=data.category, description=data.description,
            )
        # The transaction context has confirmed commit. Never retry uncertain commits.
        return response


async def delete_transaction(session_factory, owner_id: int, transaction_id: int) -> bool:
    """Delete only this owner's row; report success only after commit.

    No ORM objects are staged: the Core DELETE executes immediately, and there
    is no pending ORM flush. The transaction context rolls back on execution
    errors. Commit errors propagate without retry or claims about durability.
    """
    async with session_factory() as session:
        async with session.begin():
            deleted_id = await session.scalar(
                delete(Transaction).where(
                    Transaction.id == transaction_id,
                    Transaction.user_id == owner_id,
                ).returning(Transaction.id)
            )
        return deleted_id is not None
