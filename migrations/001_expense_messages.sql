-- REVIEW ONLY. Never run automatically at bot startup.
-- Existing users/categories/transactions tables are required.
-- Before approval: review backups and category duplicates. No data is deleted.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM categories GROUP BY name HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'Category duplicates require manual review before migration';
    END IF;
END;
$$;

ALTER TABLE categories ADD CONSTRAINT uq_categories_name UNIQUE (name);
ALTER TABLE transactions
    ADD COLUMN telegram_chat_id BIGINT,
    ADD COLUMN telegram_message_id BIGINT,
    ADD CONSTRAINT uq_transactions_telegram_message
        UNIQUE (telegram_chat_id, telegram_message_id),
    ADD CONSTRAINT ck_transactions_message_pair CHECK (
        (telegram_chat_id IS NULL) = (telegram_message_id IS NULL)
    );

COMMIT;
-- One-time migration. Review existing constraint names before applying.
-- Legacy rows retain NULL message identifiers; no historical IDs are invented.
