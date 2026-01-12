from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Iterator, Mapping, Self, Type

from ..models.base import BaseModel
from .errors import wrap_db_errors

DEFAULT_PRIMARY_KEY = "id"

logger = logging.getLogger(__package__)


@dataclass
class BaseRepository:
    model: ClassVar[Type[BaseModel] | None] = None
    pkey: ClassVar[str] = DEFAULT_PRIMARY_KEY
    conflict_columns: ClassVar[tuple[str, ...] | None] = None
    update_excludes: ClassVar[tuple[str, ...]] = ("created_at", "updated_at")
    __table__: ClassVar[str | None] = None

    conn: sqlite3.Connection
    auto_commit: bool = True

    @property
    def table_name(self) -> str:
        return self.__table__ or self.model.__name__

    @wrap_db_errors
    def commit(self):
        if self.conn.in_transaction:
            self.conn.commit()

    @wrap_db_errors
    def rollback(self):
        if self.conn.in_transaction:
            self.conn.rollback()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def maybe_commit(self, commit: bool | None = None) -> bool:
        if commit is not None and commit or self.auto_commit:
            self.commit()

    def _row_to_model(self, cursor: sqlite3.Cursor, row: tuple) -> BaseModel:
        data = {col[0]: value for col, value in zip(cursor.description, row)}  # noqa: B905
        return self.model.from_db(data)

    @wrap_db_errors
    def find(self, **kwargs: Any) -> Iterator[BaseModel]:
        # logger.debug(kwargs)
        operators = {
            "lt": "<",
            "le": "<=",
            "gt": ">",
            "ge": ">=",
            "ne": "!=",
            "eq": "=",
            "like": "LIKE",
            "is": "IS",
            "is_not": "IS NOT",
            "in": "IN",
            "not_in": "NOT IN",
        }
        conditions = []
        sql_params = {}
        for key, value in kwargs.items():
            try:
                key, op = key.rsplit("__", 1)
            except ValueError:
                op = "eq"
            if op in ("in", "not_in"):
                if not isinstance(value, (list, tuple)):
                    value = [value]
                in_placeholders = []
                for i, v in enumerate(value, 1):
                    p_name = f"{key}_{i}"
                    in_placeholders.append(f":{p_name}")
                    sql_params[p_name] = v
                conditions.append(
                    f"{key} {operators[op]} ({', '.join(in_placeholders)})"
                )
            else:
                placeholder = f":{key}"
                sql_params[key] = value
                conditions.append(f"{key} {operators[op]} {placeholder}")
        sql = f"SELECT * FROM {self.table_name}"
        if conditions:
            sql += f" WHERE {' AND '.join(conditions)}"
        sql += " ORDER BY rowid DESC;"
        try:
            cur = self.conn.execute(sql, sql_params)
        except sqlite3.Error:
            logger.warning("SQL ERROR: %s", sql)
            raise

        yield from (self._row_to_model(cur, row) for row in cur.fetchall())

    @wrap_db_errors
    def get(self, pk: Any) -> BaseModel | None:
        return next(self.find(**{f"{self.pkey}": pk}), None)

    @wrap_db_errors
    def count_total(self) -> int:
        cur = self.conn.execute(f"SELECT count(*) FROM {self.table_name};")
        return cur.fetchone()[0]

    @wrap_db_errors
    def delete(self, obj_or_pkey: Any, /, commit: bool | None = None) -> None:
        sql = f"DELETE FROM {self.table_name} WHERE {self.pkey} = ?"
        pk_value = (
            getattr(obj_or_pkey, self.pkey)
            if isinstance(obj_or_pkey, BaseModel)
            else obj_or_pkey
        )
        self.conn.execute(sql, (pk_value,))
        self.maybe_commit(commit=commit)

    remove = delete

    @wrap_db_errors
    def clear(self, commit: bool | None = None):
        self.conn.execute(f"DELETE FROM {self.table_name};")
        self.maybe_commit(commit)

    clean = clear

    def _insert(
        self,
        data: Mapping[str, Any] | list[Mapping[str, Any]],
        /,
        batch: bool = False,
        upsert: bool = True,
        conflict_columns: Sequence[str] | None = None,
        update_excludes: Sequence[str] | None = None,
        commit: bool | None = None,
    ):
        conflict_columns = conflict_columns or self.conflict_columns
        update_excludes = update_excludes or self.update_excludes

        if batch and not data:
            return

        columns = list(dict(data[0] if batch else data).keys())
        sql = (
            f"INSERT INTO {self.table_name} ({', '.join(columns)})"
            f" VALUES (:{', :'.join(columns)})"
        )

        if upsert:
            cols_set = set(columns)

            # Определяем поля конфликта: или переданные, или pkey
            if conflict_columns:
                conflict_set = set(conflict_columns) & cols_set
            else:
                conflict_set = {self.pkey} & cols_set

            if conflict_set:
                sql += f" ON CONFLICT({', '.join(conflict_set)})"

                # Исключаем из обновления:
                # 1. Поля конфликта (нельзя обновлять по законам SQL)
                # 2. Primary key (никогда не меняем)
                # 3. Технические поля (created_at и т.д.)
                update_set = (
                    cols_set
                    - conflict_set
                    - {self.pkey}
                    - set(update_excludes or [])
                )

                if update_set:
                    update_clause = ", ".join(
                        f"{c} = excluded.{c}" for c in update_set
                    )
                    sql += f" DO UPDATE SET {update_clause}"
                else:
                    sql += " DO NOTHING"

        sql += ";"
        # logger.debug("%.2000s", sql)
        try:
            if batch:
                self.conn.executemany(sql, data)
            else:
                self.conn.execute(sql, data)
        except sqlite3.Error:
            logger.warning("SQL ERROR: %s", sql)

            raise
        self.maybe_commit(commit)

    @wrap_db_errors
    def save(
        self,
        obj: BaseModel | Mapping[str, Any],
        /,
        **kwargs: Any,
    ) -> None:
        if isinstance(obj, Mapping):
            obj = self.model.from_api(obj)
        data = obj.to_db()
        self._insert(data, **kwargs)

    @wrap_db_errors
    def save_batch(
        self,
        items: list[BaseModel | Mapping[str, Any]],
        /,
        **kwargs: Any,
    ) -> None:
        if not items:
            return
        data = [
            (self.model.from_api(i) if isinstance(i, Mapping) else i).to_db()
            for i in items
        ]
        self._insert(data, batch=True, **kwargs)
