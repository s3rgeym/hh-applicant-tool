-- Убираем NOT NULL с колонки title в таблице resumes.
-- SQLite не поддерживает ALTER COLUMN, поэтому пересоздаём таблицу.
PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE IF NOT EXISTS resumes_new (
    id TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    url TEXT,
    alternate_url TEXT,
    status_id TEXT,
    status_name TEXT,
    can_publish_or_update BOOLEAN,
    total_views INTEGER DEFAULT 0,
    new_views INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO resumes_new SELECT * FROM resumes;
DROP TABLE resumes;
ALTER TABLE resumes_new RENAME TO resumes;

-- Восстанавливаем триггер
CREATE TRIGGER IF NOT EXISTS trg_resumes_updated
AFTER UPDATE ON resumes BEGIN
    UPDATE resumes SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;

COMMIT;
PRAGMA foreign_keys = ON;
