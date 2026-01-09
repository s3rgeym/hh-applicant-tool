import datetime as dt
import json
from typing import Any

# class DateAwareJSONEncoder(json.JSONEncoder):
#     def default(self, o):
#         if isinstance(o, dt.datetime):
#             return o.isoformat()

#         return super().default(o)


# Костыль чтобы в key-value хранить даты
class DateAwareJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, dt.datetime):
            return int(o.timestamp())

        return super().default(o)


# def date_parser_hook(dct):
#     for k, v in dct.items():
#         if isinstance(v, str):
#             try:
#                 dct[k] = dt.datetime.fromisoformat(v)
#             except (ValueError, TypeError):
#                 pass
#     return dct


# class DateAwareJSONDecoder(json.JSONDecoder):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, object_hook=date_parser_hook, **kwargs)


def dumps(obj, *args: Any, **kwargs: Any) -> str:
    kwargs.setdefault("cls", DateAwareJSONEncoder)
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(obj, *args, **kwargs)


def dump(fp, obj, *args: Any, **kwargs: Any) -> None:
    kwargs.setdefault("cls", DateAwareJSONEncoder)
    kwargs.setdefault("ensure_ascii", False)
    json.dump(fp, obj, *args, **kwargs)


def loads(s, *args: Any, **kwargs: Any) -> Any:
    # kwargs.setdefault("object_hook", date_parser_hook)
    return json.loads(s, *args, **kwargs)


def load(fp, *args: Any, **kwargs: Any) -> Any:
    # kwargs.setdefault("object_hook", date_parser_hook)
    return json.load(fp, *args, **kwargs)


if __name__ == "__main__":
    d = {"created_at": dt.datetime.now()}
    print(loads(dumps(d)))
