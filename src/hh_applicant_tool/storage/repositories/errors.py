import sqlite3
from functools import wraps


class RepositoryError(sqlite3.Error):
    pass


def wrap_db_errors(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except sqlite3.Error as e:
            raise RepositoryError(
                f"Database error in {func.__name__}: {e}"
            ) from e

    return wrapper
