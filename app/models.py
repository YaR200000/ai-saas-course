from decimal import Decimal
from datetime import date as calendar_date, datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class User(Base):
    """Telegram user stored in PostgreSQL."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

class Category(Base):
    """Expense category stored in PostgreSQL."""

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("name", name="uq_categories_name"),)

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

class Transaction(Base):
    """Financial transaction stored in PostgreSQL."""

    __tablename__ = "transactions"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("type IN ('income', 'expense')", name="ck_transactions_type"),
        UniqueConstraint("telegram_chat_id", "telegram_message_id", name="uq_transactions_telegram_message"),
        CheckConstraint(
            "(telegram_chat_id IS NULL) = (telegram_message_id IS NULL)",
            name="ck_transactions_message_pair",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
    )

    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("categories.id"),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    type: Mapped[str] = mapped_column(
        String(7), nullable=False, server_default="expense",
    )

    date: Mapped[calendar_date] = mapped_column(
        Date, nullable=False,
        server_default=func.date(func.timezone("Europe/Kyiv", func.current_timestamp())),
    )

    # NULL for legacy expenses and operations created outside Telegram.
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
