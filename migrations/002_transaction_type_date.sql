-- REVIEW BEFORE APPLYING. Requires 001_expense_messages.sql; never run on startup.
-- One-time migration: unexpected existing columns/constraints must fail loudly.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE transactions
    ADD COLUMN type VARCHAR(7) NOT NULL DEFAULT 'expense',
    ADD CONSTRAINT ck_transactions_type CHECK (type IN ('income', 'expense')),
    ADD COLUMN date DATE;

UPDATE transactions
SET date = (created_at AT TIME ZONE 'Europe/Kyiv')::date;

ALTER TABLE transactions
    ALTER COLUMN date SET DEFAULT date(timezone('Europe/Kyiv', CURRENT_TIMESTAMP)),
    ALTER COLUMN date SET NOT NULL;

COMMIT;
