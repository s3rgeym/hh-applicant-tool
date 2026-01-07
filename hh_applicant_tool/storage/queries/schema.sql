BEGIN;

-- employer_contacts
CREATE TABLE IF NOT EXISTS employer_contacts (
    id TEXT PRIMARY KEY
        DEFAULT (lower(hex(randomblob(16)))),

    employer_id   INTEGER NOT NULL,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL,
    phone_numbers TEXT NOT NULL,

    UNIQUE (employer_id, name, email, phone_numbers),
    FOREIGN KEY (employer_id) REFERENCES employers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_employer_contacts_employer_id
    ON employer_contacts(employer_id);

-- employers
CREATE TABLE IF NOT EXISTS employers (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    type          TEXT NOT NULL,
    description   TEXT,
    site_url      TEXT,
    area_id       INTEGER,
    area_name     TEXT,
    alternate_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_employers_name
    ON employers(name);
CREATE INDEX IF NOT EXISTS idx_employers_type
    ON employers(type);
CREATE INDEX IF NOT EXISTS idx_employers_area_id
    ON employers(area_id);
CREATE INDEX IF NOT EXISTS idx_employers_area_name
    ON employers(area_name);

-- vacancies
CREATE TABLE IF NOT EXISTS vacancies (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    area_id       INTEGER,
    area_name     TEXT,
    salary_from   INTEGER,
    salary_to     INTEGER,
    currency      VARCHAR(3),
    gross         BOOLEAN,
    published_at  DATETIME,
    created_at    DATETIME,
    remote        BOOLEAN,
    expirence     TEXT,
    alternate_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_vacancies_name
    ON vacancies(name);
CREATE INDEX IF NOT EXISTS idx_vacancies_area_id
    ON vacancies(area_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_area_name
    ON vacancies(area_name);
CREATE INDEX IF NOT EXISTS idx_vacancies_salary_from
    ON vacancies(salary_from);
CREATE INDEX IF NOT EXISTS idx_vacancies_salary_to
    ON vacancies(salary_to);
CREATE INDEX IF NOT EXISTS idx_vacancies_currency
    ON vacancies(currency);
CREATE INDEX IF NOT EXISTS idx_vacancies_gross
    ON vacancies(gross);
CREATE INDEX IF NOT EXISTS idx_vacancies_published_at
    ON vacancies(published_at);
CREATE INDEX IF NOT EXISTS idx_vacancies_created_at
    ON vacancies(created_at);
CREATE INDEX IF NOT EXISTS idx_vacancies_remote
    ON vacancies(remote);
CREATE INDEX IF NOT EXISTS idx_vacancies_expirence
    ON vacancies(expirence);

COMMIT;
