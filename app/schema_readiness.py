"""Read-only PostgreSQL catalog inspection; never creates or migrates tables."""
import re

from sqlalchemy import Date, DateTime, Numeric, String, inspect, text


def normalized(expression):
    # PostgreSQL deparses varchar checks with casts and extra parentheses.
    expression = re.sub(r"::(?:character varying|text|numeric)(?:\[\])?", "", expression.lower())
    return re.sub(r"[\s()]", "", expression)


def compatible_schema(connection):
    inspector = inspect(connection)
    columns = {c["name"]: c for c in inspector.get_columns("transactions")}
    required = {"id", "user_id", "category_id", "amount", "description", "created_at",
                "telegram_chat_id", "telegram_message_id", "type", "date"}
    if not required <= columns.keys():
        return False
    kind, day, amount = (columns[n] for n in ("type", "date", "amount"))
    if any(columns[n]["nullable"] for n in required - {"telegram_chat_id", "telegram_message_id"}):
        return False
    if not (isinstance(kind["type"], String) and kind["type"].length == 7
            and isinstance(day["type"], Date) and not isinstance(day["type"], DateTime)
            and isinstance(amount["type"], Numeric)
            and (amount["type"].precision, amount["type"].scale) == (12, 2)):
        return False
    if normalized(kind.get("default") or "") != "'expense'":
        return False
    if normalized(day.get("default") or "") not in {
        "datetimezone'europe/kyiv',current_timestamp",
        "timezone'europe/kyiv',current_timestamp::date",
    }:
        return False
    checks = {c["name"]: c["sqltext"] for c in inspector.get_check_constraints("transactions")}
    unvalidated = connection.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = to_regclass('transactions') AND NOT convalidated
        )
    """)).scalar_one()
    if unvalidated:
        return False
    type_check = checks.get("ck_transactions_type", "")
    if normalized(type_check) not in {
        "typein'income','expense'", "type=anyarray['income','expense']",
        "typein'expense','income'", "type=anyarray['expense','income']",
    }:
        return False
    if normalized(checks.get("ck_transactions_amount_positive", "")) != "amount>0":
        return False
    if normalized(checks.get("ck_transactions_message_pair", "")) != "telegram_chat_idisnull=telegram_message_idisnull":
        return False
    uniques = {tuple(c["column_names"]) for c in inspector.get_unique_constraints("categories")}
    message_uniques = {tuple(c["column_names"]) for c in inspector.get_unique_constraints("transactions")}
    foreign_keys = {tuple(c["constrained_columns"]): (c["referred_table"], tuple(c["referred_columns"]))
                    for c in inspector.get_foreign_keys("transactions")}
    return (("name",) in uniques and ("telegram_chat_id", "telegram_message_id") in message_uniques
            and foreign_keys.get(("user_id",)) == ("users", ("id",))
            and foreign_keys.get(("category_id",)) == ("categories", ("id",)))


async def check_schema_ready(engine):
    try:
        async with engine.connect() as connection:
            if not await connection.run_sync(compatible_schema):
                raise ValueError("Incompatible schema")
    except Exception:
        raise RuntimeError("API schema is unavailable or incompatible; migration 002 is required.") from None
