from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

QUERIES_PATH: Path = Path(__file__).parent / "queries"
MIGRATION_PATH: Path = QUERIES_PATH / "migrations"


logger: logging.Logger = logging.getLogger(__package__)


def init_db(conn: sqlite3.Connection) -> None:
    """Создает схему БД"""
    conn.executescript(
        (QUERIES_PATH / "schema.sql").read_text(encoding="utf-8")
    )
    logger.debug("Database scheme created or updated")


def list_migrations() -> list[str]:
    """Выводит имена миграций без расширения, отсортированные по дате"""
    if not MIGRATION_PATH.exists():
        return []
    return sorted([f.stem for f in MIGRATION_PATH.glob("*.sql")])


def apply_migration(conn: sqlite3.Connection, name: str) -> None:
    """Находит файл по имени и выполняет его содержимое"""
    conn.executescript(
        (MIGRATION_PATH / f"{name}.sql").read_text(encoding="utf-8")
    )


def model2table(o: type) -> str:
    name: str = o.__name__
    if name.endswith("Model"):
        name = name[:-5]
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    # y -> ies (если перед y согласная: vacancy -> vacancies)
    if name.endswith("y") and not name.endswith(("ay", "ey", "iy", "oy", "uy")):
        return name[:-1] + "ies"
    # s, x, z, ch, sh -> +es (bus -> buses, match -> matches)
    if name.endswith(("s", "x", "z", "ch", "sh")):
        return name + "es"
    # Обычный случай
    return name + "s"
