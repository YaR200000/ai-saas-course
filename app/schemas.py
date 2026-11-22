"""Financial API contracts; money enters as decimal text, never JSON floats."""
from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["income", "expense"]
    amount: Decimal
    category: str
    description: str
    date: date

    @field_validator("amount", mode="before")
    @classmethod
    def money(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,2})?", value):
            raise ValueError("Invalid amount")
        amount = Decimal(value)
        if not Decimal("0") < amount <= Decimal("9999999999.99"):
            raise ValueError("Invalid amount")
        return amount

    @field_validator("category", "description", mode="before")
    @classmethod
    def nonempty_text(cls, value, info):
        maximum = 100 if info.field_name == "category" else 2000
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum or "\x00" in value:
            raise ValueError("Invalid text")
        return value.strip()

    @field_validator("date", mode="before")
    @classmethod
    def calendar_date(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("Invalid date")
        return date.fromisoformat(value)


class TransactionResponse(BaseModel):
    id: str
    created_at: datetime
    date: date
    type: Literal["income", "expense"]
    amount: str
    category: str
    description: str
    currency: Literal["UAH"] = "UAH"


class SummaryResponse(BaseModel):
    total_income: str
    total_expense: str
    balance: str
