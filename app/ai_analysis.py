"""Read-only financial snapshot and process-local admission control."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
import math
import time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, true

from app.models import Category, Transaction
from app.schemas import AiAnalysisResponse, AiExpenseCategory, GeminiAnalysis

KYIV = ZoneInfo("Europe/Kyiv")


def kyiv_now():
    return datetime.now(KYIV)


class AnalysisLimited(Exception):
    def __init__(self, retry_after):
        self.retry_after = max(1, math.ceil(retry_after))


class AnalysisLimiter:
    """No awaits during admission: atomic in this application's event loop.

    Counts all admitted attempts (including failures/empty snapshots). Never
    refunds uncertain provider outcomes. Not shared across workers/restarts.
    """
    def __init__(self, daily_limit, *, clock=time.monotonic, now=kyiv_now):
        self.daily_limit = daily_limit
        self.clock = clock
        self.now = now
        self.active = False
        self.last_started = None
        self.day = None
        self.count = 0

    @contextmanager
    def reserve(self):
        now = self.now().astimezone(KYIV)
        tick = self.clock()
        if self.active:
            raise AnalysisLimited(60)
        if self.day != now.date():
            self.day, self.count = now.date(), 0
        if self.count >= self.daily_limit:
            midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), KYIV)
            raise AnalysisLimited(midnight.timestamp() - now.timestamp())
        if self.last_started is not None and tick - self.last_started < 60:
            raise AnalysisLimited(60 - (tick - self.last_started))
        self.active, self.last_started = True, tick
        self.count += 1
        try:
            yield
        finally:
            self.active = False


@dataclass(frozen=True)
class FinancialSnapshot:
    facts: dict
    categories: list[AiExpenseCategory]
    income_count: int
    expense_count: int
    other_expense: str

    def gemini_payload(self):
        # Category labels can contain personal information or instructions.
        # Only ephemeral aliases leave this service, never database identifiers.
        return {
            **self.facts,
            "period_start": self.facts["period_start"].isoformat(),
            "period_end": self.facts["period_end"].isoformat(),
            "income_count": self.income_count,
            "expense_count": self.expense_count,
            "top_expense_categories": [
                {"category": f"category_{index}", "amount": item.amount,
                 "share_percent": item.share_percent}
                for index, item in enumerate(self.categories, 1)
            ],
            "other_expense": self.other_expense,
        }

    def response(self, prose: GeminiAnalysis):
        return AiAnalysisResponse(**self.facts, top_expense_categories=self.categories,
                                  **prose.model_dump())


async def load_financial_snapshot(session_factory, owner_id, *, today=None):
    end = today if today is not None else kyiv_now().date()
    start = end - timedelta(days=29)
    grouped = (select(Transaction.type.label("kind"), Category.name.label("category"),
                      func.count().label("count"), func.sum(Transaction.amount).label("amount"))
               .join(Category, Transaction.category_id == Category.id)
               .where(Transaction.user_id == owner_id,
                      Transaction.date >= start, Transaction.date <= end)
               .group_by(Transaction.type, Category.name).cte("ai_grouped"))
    totals = select(
        func.coalesce(func.sum(grouped.c.amount).filter(grouped.c.kind == "income"), 0).label("income"),
        func.coalesce(func.sum(grouped.c.amount).filter(grouped.c.kind == "expense"), 0).label("expense"),
        func.coalesce(func.sum(grouped.c.count).filter(grouped.c.kind == "income"), 0).label("income_count"),
        func.coalesce(func.sum(grouped.c.count).filter(grouped.c.kind == "expense"), 0).label("expense_count"),
    ).cte("ai_totals")
    top = (select(grouped.c.category, grouped.c.amount).where(grouped.c.kind == "expense")
           .order_by(grouped.c.amount.desc(), grouped.c.category.asc()).limit(5).cte("ai_top"))
    # One PostgreSQL statement -> one READ COMMITTED snapshot for every aggregate.
    statement = (select(totals, top).select_from(totals.outerjoin(top, true()))
                 .order_by(top.c.amount.desc(), top.c.category.asc()))
    async with session_factory() as session:
        rows = (await session.execute(statement)).mappings().all()
    # Session has closed before any provider interaction.
    row = rows[0]
    income, expense = Decimal(row["income"]), Decimal(row["expense"])
    with localcontext() as context:
        context.prec = max(len(format(income, "f")), len(format(expense, "f")), 28) + 10
        categories = [AiExpenseCategory(
            category=item["category"], amount=format(item["amount"], ".2f"),
            share_percent=format((Decimal(item["amount"]) * 100 / expense).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f"),
        ) for item in rows if item["category"] is not None]
        other_expense = expense - sum((Decimal(item.amount) for item in categories), Decimal(0))
        facts = dict(period_start=start, period_end=end, currency="UAH",
                     transaction_count=int(row["income_count"] + row["expense_count"]),
                     total_income=format(income, ".2f"), total_expense=format(expense, ".2f"),
                     balance=format(income - expense, ".2f"))
    return FinancialSnapshot(facts, categories, int(row["income_count"]),
                             int(row["expense_count"]), format(other_expense, ".2f"))
