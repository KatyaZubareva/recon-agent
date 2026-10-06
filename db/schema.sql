-- Схема отчётной БД. Применяется от роли importer (recon db-init / при старте приложения),
-- поэтому agent_reader автоматически получает только SELECT (см. postgres/init.sql).
-- Скрипт идемпотентен: повторный запуск ничего не ломает.

-- Справочник лицевых счетов (копия из 1С).
CREATE TABLE IF NOT EXISTS accounts (
    id             text PRIMARY KEY,               -- стабильный ID из источника (ВнешнийID в 1С)
    account_number text NOT NULL UNIQUE
);

-- Начисления. Суммы — целые копейки (bigint), никаких float/numeric с дробью.
CREATE TABLE IF NOT EXISTS charges (
    id             text PRIMARY KEY,
    account_id     text NOT NULL REFERENCES accounts (id),
    period         text NOT NULL CHECK (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),  -- YYYY-MM
    amount_kopecks bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS charges_period_idx ON charges (period);

-- Платежи импортируются с сохранением ID и связей; сверка платежей не требуется.
CREATE TABLE IF NOT EXISTS payments (
    id             text PRIMARY KEY,
    account_id     text NOT NULL REFERENCES accounts (id),
    date           date NOT NULL,
    amount_kopecks bigint NOT NULL
);

-- Журнал импортов: каждая попытка, включая неудачные.
CREATE TABLE IF NOT EXISTS import_runs (
    id          uuid PRIMARY KEY,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status      text NOT NULL CHECK (status IN ('running', 'ok', 'rejected', 'error')),
    source      text NOT NULL,
    counts      jsonb,                              -- {"accounts": 2, "charges": 4, ...}
    problems    jsonb,                              -- нарушения правил валидации (rejected)
    error       text                                -- причина ошибки источника/БД (error)
);
