PRAGMA foreign_keys = OFF;
BEGIN;
/* Удаляем старые триггеры, чтобы они не мешали переносу данных */
DROP TRIGGER IF EXISTS trg_employers_updated;
DROP TRIGGER IF EXISTS trg_employer_contacts_updated;
DROP TRIGGER IF EXISTS trg_vacancies_updated;
DROP TRIGGER IF EXISTS trg_negotiations_updated;
/* =========================================================
 1. employer_contacts (изменение UNIQUE и добавление дат)
 ========================================================= */
ALTER TABLE employer_contacts
  RENAME TO employer_contacts_old;
CREATE TABLE employer_contacts (
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
INSERT
  OR IGNORE INTO employer_contacts (
    id,
    employer_id,
    name,
    email,
    phone_numbers,
    created_at,
    updated_at
  )
SELECT id,
  employer_id,
  name,
  email,
  phone_numbers,
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP
FROM employer_contacts_old;
DROP TABLE employer_contacts_old;
/* =========================================================
 2. employers (добавление дат)
 ========================================================= */
ALTER TABLE employers
  RENAME TO employers_old;
CREATE TABLE employers (
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
INSERT INTO employers (
    id,
    name,
    type,
    description,
    site_url,
    area_id,
    area_name,
    alternate_url,
    created_at,
    updated_at
  )
SELECT id,
  name,
  type,
  description,
  site_url,
  area_id,
  area_name,
  alternate_url,
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP
FROM employers_old;
DROP TABLE employers_old;
/* =========================================================
 3. vacancies (добавление дат и professional_roles)
 ========================================================= */
DROP INDEX IF EXISTS idx_vacancies_expirence;
ALTER TABLE vacancies
  RENAME TO vacancies_old;
CREATE TABLE vacancies (
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
INSERT INTO vacancies (
    id,
    name,
    area_id,
    area_name,
    salary_from,
    salary_to,
    currency,
    gross,
    published_at,
    created_at,
    updated_at,
    remote,
    experience,
    alternate_url
  )
SELECT id,
  name,
  area_id,
  area_name,
  salary_from,
  salary_to,
  currency,
  gross,
  published_at,
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP,
  remote,
  -- Опечатка
  expirence,
  alternate_url
FROM vacancies_old;
DROP TABLE vacancies_old;
COMMIT;
PRAGMA foreign_keys = ON;
