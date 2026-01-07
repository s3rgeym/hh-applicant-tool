PRAGMA foreign_keys = ON;
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
CREATE INDEX IF NOT EXISTS idx_employers_name ON employers(name);
CREATE INDEX IF NOT EXISTS idx_employers_type ON employers(type);
CREATE INDEX IF NOT EXISTS idx_employers_area_id ON employers(area_id);
CREATE INDEX IF NOT EXISTS idx_employers_area_name ON employers(area_name);
/* ===================== employer_contacts ===================== */
CREATE TABLE IF NOT EXISTS employer_contacts (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    employer_id INTEGER NOT NULL,
    name TEXT,
    email TEXT,
    phone_numbers TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (employer_id, email),
    FOREIGN KEY (employer_id) REFERENCES employers(id) ON DELETE CASCADE
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
    -- JSON
    alternate_url TEXT
);
CREATE INDEX IF NOT EXISTS idx_vacancies_name ON vacancies(name);
CREATE INDEX IF NOT EXISTS idx_vacancies_area_id ON vacancies(area_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_area_name ON vacancies(area_name);
CREATE INDEX IF NOT EXISTS idx_vacancies_salary_from ON vacancies(salary_from);
CREATE INDEX IF NOT EXISTS idx_vacancies_salary_to ON vacancies(salary_to);
CREATE INDEX IF NOT EXISTS idx_vacancies_currency ON vacancies(currency);
CREATE INDEX IF NOT EXISTS idx_vacancies_gross ON vacancies(gross);
CREATE INDEX IF NOT EXISTS idx_vacancies_published_at ON vacancies(published_at);
CREATE INDEX IF NOT EXISTS idx_vacancies_created_at ON vacancies(created_at);
CREATE INDEX IF NOT EXISTS idx_vacancies_remote ON vacancies(remote);
CREATE INDEX IF NOT EXISTS idx_vacancies_experience ON vacancies(experience);
/* ===================== negotiations ===================== */
CREATE TABLE IF NOT EXISTS negotiations (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    vacancy_id INTEGER NOT NULL,
    employer_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    resume_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_negotiations_state ON negotiations(state);
CREATE INDEX IF NOT EXISTS idx_negotiations_vacancy ON negotiations(vacancy_id);
CREATE INDEX IF NOT EXISTS idx_negotiations_employer ON negotiations(employer_id);
CREATE INDEX IF NOT EXISTS idx_negotiations_chat ON negotiations(chat_id);
CREATE INDEX IF NOT EXISTS idx_negotiations_resume ON negotiations(resume_id);
/* ===================== settings ===================== */
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
/* триггеры */
CREATE TRIGGER IF NOT EXISTS trg_employers_updated
AFTER
UPDATE ON employers FOR EACH ROW
    WHEN NEW.updated_at <= OLD.updated_at BEGIN
UPDATE employers
SET updated_at = CURRENT_TIMESTAMP
WHERE id = OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_employer_contacts_updated
AFTER
UPDATE ON employer_contacts FOR EACH ROW
    WHEN NEW.updated_at <= OLD.updated_at BEGIN
UPDATE employer_contacts
SET updated_at = CURRENT_TIMESTAMP
WHERE id = OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_vacancies_updated
AFTER
UPDATE ON vacancies FOR EACH ROW
    WHEN NEW.updated_at <= OLD.updated_at BEGIN
UPDATE vacancies
SET updated_at = CURRENT_TIMESTAMP
WHERE id = OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_negotiations_updated
AFTER
UPDATE ON negotiations FOR EACH ROW
    WHEN NEW.updated_at <= OLD.updated_at BEGIN
UPDATE negotiations
SET updated_at = CURRENT_TIMESTAMP
WHERE id = OLD.id;
END;
COMMIT;
