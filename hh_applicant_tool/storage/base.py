from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__package__)


class BaseRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_by_id(
        self,
        table: str,
        data: dict[str, Any],
        id_field: str = "id",
    ) -> None:
        columns = list(data.keys())
        placeholders = ", ".join(f":{c}" for c in columns)

        update_columns = [c for c in columns if c != id_field]
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_columns)

        sql = f"""
        INSERT INTO {table} ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT({id_field}) DO UPDATE SET
            {update_clause}
        """

        logger.debug(sql)
        self.conn.execute(sql, data)
        self.conn.commit()
