PRAGMA foreign_keys = OFF;
-- На всякий случай выключаем проверки
BEGIN;
/* ===================== employers ===================== */
CREATE TABLE IF NOT EXISTS employers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT,
    description TEXT,
    site_url TEXT,
    area_id INTEGER,
    area_name TEXT,
    alternate_url TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
/* ===================== employer_contacts ===================== */
CREATE TABLE IF NOT EXISTS employer_contacts (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    employer_id INTEGER NOT NULL,
    -- Просто поле, без REFERENCES
    name TEXT,
    email TEXT,
    phone_numbers TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (employer_id, email)
);
/* ===================== vacancies ===================== */
CREATE TABLE IF NOT EXISTS vacancies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    area_id INTEGER,
    area_name TEXT,
    salary_from INTEGER,
    salary_to INTEGER,
    currency VARCHAR(3),
    gross BOOLEAN,
    published_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    remote BOOLEAN,
    experience TEXT,
    professional_roles TEXT,
    alternate_url TEXT
);
/* ===================== negotiations ===================== */
CREATE TABLE IF NOT EXISTS negotiations (
    id INTEGER PRIMARY KEY,
    state TEXT NOT NULL,
    vacancy_id INTEGER NOT NULL,
    employer_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    resume_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
/* ===================== settings ===================== */
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
/* ===================== resumes ===================== */
CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
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
/* ===================== ИНДЕКСЫ ДЛЯ СТАТИСТИКИ ===================== */
-- Чтобы выборка для отправки на сервер по updated_at не тормозила
CREATE INDEX IF NOT EXISTS idx_vac_upd ON vacancies(updated_at);
CREATE INDEX IF NOT EXISTS idx_emp_upd ON employers(updated_at);
CREATE INDEX IF NOT EXISTS idx_neg_upd ON negotiations(updated_at);
/* ===================== ТРИГГЕРЫ (Всегда обновляют дату) ===================== */
-- Убрал условие WHEN. Теперь при любом UPDATE дата актуализируется принудительно.
CREATE TRIGGER IF NOT EXISTS trg_resumes_updated
AFTER
UPDATE ON resumes BEGIN
UPDATE resumes
SET updated_at = CURRENT_TIMESTAMP
WHERE id = OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_employers_updated
AFTER
UPDATE ON employers BEGIN
UPDATE employers
SET updated_at = CURRENT_TIMESTAMP
WHERE id = OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_employer_contacts_updated
AFTER
UPDATE ON employer_contacts BEGIN
UPDATE employer_contacts
SET updated_at = CURRENT_TIMESTAMP
WHERE id = OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_vacancies_updated
AFTER
UPDATE ON vacancies BEGIN
UPDATE vacancies
SET updated_at = CURRENT_TIMESTAMP
WHERE id = OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_negotiations_updated
AFTER
UPDATE ON negotiations BEGIN
UPDATE negotiations
SET updated_at = CURRENT_TIMESTAMP
WHERE id = OLD.id;
END;
COMMIT;
