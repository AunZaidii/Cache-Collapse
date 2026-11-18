-- CacheCollapse database schema.
-- Runs automatically the first time the PostgreSQL container starts.

CREATE TABLE IF NOT EXISTS products (
    id          SERIAL PRIMARY KEY,
    name        TEXT        NOT NULL,
    description TEXT        NOT NULL,
    price       NUMERIC(10,2) NOT NULL,
    stock       INTEGER     NOT NULL DEFAULT 0,
    updated_at  TIMESTAMP   NOT NULL DEFAULT NOW()
);
