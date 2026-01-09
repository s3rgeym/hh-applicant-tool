from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any, ClassVar, Iterator, Mapping, Self, Type

from ..models.base import BaseModel
from ..utils import model2table

DEFAULT_PRIMARY_KEY = "id"

logger = logging.getLogger(__package__)


@dataclass
class BaseRepository:
    model: ClassVar[Type[BaseModel] | None] = None
    pkey: ClassVar[str] = DEFAULT_PRIMARY_KEY

    conn: sqlite3.Connection
    auto_commit: bool = True

    @cached_property
    def table_name(self) -> str:
        return model2table(self.model)

    def commit(self):
        if self.conn.in_transaction:
            self.conn.commit()

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
        logger.debug("%.2000s", sql)
        cur = self.conn.execute(sql, sql_params)
        yield from (self._row_to_model(cur, row) for row in cur.fetchall())

    def get(self, pk: Any) -> BaseModel | None:
        return next(self.find(**{f"{self.pkey}": pk}), None)

    def count_total(self) -> int:
        cur = self.conn.execute(f"SELECT count(*) FROM {self.table_name};")
        return cur.fetchone()[0]

    def delete(self, o: BaseModel, /, commit: bool | None = None) -> None:
        sql = f"DELETE FROM {self.table_name} WHERE {self.pkey} = ?"
        pk_value = getattr(o, self.pkey)
        self.conn.execute(sql, (pk_value,))
        self.maybe_commit(commit=commit)

    remove = delete

    def clear(self, commit: bool | None = None):
        self.conn.execute(f"DELETE FROM {self.table_name};")
        self.maybe_commit(commit)

    clean = clear

    def _insert(
        self,
        data: Mapping[str, Any],
        /,
        upsert: bool = True,
        conflict_columns: Sequence[str] | None = None,
        update_excludes: Sequence[str] = ("created_at", "updated_at"),
        commit: bool | None = None,
    ):
        columns = list(data.keys())
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
                    cols_set - conflict_set - {self.pkey} - set(update_excludes)
                )

                if update_set:
                    update_clause = ", ".join(
                        f"{c} = excluded.{c}" for c in update_set
                    )
                    sql += f" DO UPDATE SET {update_clause}"
                else:
                    sql += " DO NOTHING"

        sql += ";"
        logger.debug("%.2000s", sql)
        self.conn.execute(sql, data)
        self.maybe_commit(commit)

    def save(
        self, obj: BaseModel | Mapping[str, Any], /, **kwargs: Any
    ) -> None:
        if isinstance(obj, Mapping):
            obj = self.model.from_api(obj)
        data = obj.to_db()
        self._insert(data, **kwargs)
