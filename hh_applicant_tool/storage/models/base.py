import builtins
from dataclasses import Field, asdict, dataclass, field, fields
from datetime import datetime
from logging import getLogger
from typing import Any, Callable, Mapping, Self, dataclass_transform, get_origin

from hh_applicant_tool.utils import jsonutil
from hh_applicant_tool.utils.dateutil import try_parse_datetime

logger = getLogger(__package__)

MISSING = object()


def mapped(
    path: str | None = None,
    transform: Callable[[Any], Any] | None = None,
    store_json: bool = False,
    **kwargs: Any,
):
    metadata = kwargs.get("metadata", {})
    metadata.setdefault("path", path)
    metadata.setdefault("transform", transform)
    metadata.setdefault("store_json", store_json)
    return field(metadata=metadata, **kwargs)


@dataclass_transform(field_specifiers=(field, mapped))
class BaseModel:
    def __init_subclass__(cls, /, **kwargs: Any):
        super().__init_subclass__()
        dataclass(cls, kw_only=True, **kwargs)

    @classmethod
    def from_db(cls, data: Mapping[str, Any]) -> Self:
        return cls._from_mapping(data)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Self:
        return cls._from_mapping(data, from_source=True)

    def to_db(self) -> dict[str, Any]:
        data = self.to_dict()
        for f in fields(self):
            # Если какого-то значения нет в словаре, то не ставим его или
            # ломается установка дефолтных значений.
            value = data.get(f.name, MISSING)
            if value is MISSING:
                continue
            if f.metadata.get("store_json"):
                value = jsonutil.dumps(value)
            # Точно не нужно типы приводить перед сохранением
            # else:
            #     value = self._coerce_type(value, f)
            data[f.name] = value
        return data

    @classmethod
    def _coerce_type(cls, value: Any, f: Field) -> Any:
        # Лишь создатель знает, что с тобой делать
        if get_origin(f.type):
            return value

        type_name = f.type if isinstance(f.type, str) else f.type.__name__
        if value is not None and type_name in (
            "bool",
            "str",
            "int",
            "float",
            "datetime",
        ):
            if type_name == "datetime":
                return try_parse_datetime(value)
            try:
                t = getattr(builtins, type_name)
                if not isinstance(value, t):
                    value = t(value)
            except (TypeError, ValueError):
                pass
        return value

    @classmethod
    def _from_mapping(
        cls,
        data: Mapping[str, Any],
        /,
        from_source: bool = False,
    ) -> Self:
        kwargs = {}
        for f in fields(cls):
            if from_source:
                if path := f.metadata.get("path"):
                    found = True
                    v = data
                    for key in path.split("."):
                        if isinstance(v, Mapping):
                            v = v.get(key)
                        else:
                            found = False
                            break
                    if not found:
                        continue
                    value = v
                else:
                    value = data.get(f.name, MISSING)
                    if value is MISSING:
                        continue

                if value is not None and (t := f.metadata.get("transform")):
                    if isinstance(t, str):
                        t = getattr(cls, t)
                    value = t(value)

                value = cls._coerce_type(value, f)
            else:
                value = data.get(f.name, MISSING)
                if value is MISSING:
                    continue

                if f.metadata.get("store_json"):
                    value = jsonutil.loads(value)
                else:
                    value = cls._coerce_type(value, f)

            kwargs[f.name] = value
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # pyright: ignore[reportArgumentType]

    # def to_json(self, **kwargs: Any) -> str:
    #     """Serializes the model to a JSON string."""
    #     kwargs.setdefault("ensure_ascii", False)
    #     return json_utils.dumps(self.to_dict(), **kwargs)

    # @classmethod
    # def from_json(cls, json_str: str, **kwargs: Any) -> Self:
    #     """Deserializes a model from a JSON string."""
    #     data = json_utils.loads(json_str, **kwargs)
    #     # from_api is probably more appropriate as JSON is a common API format
    #     # and it handles nested data sources.
    #     return cls.from_api(data)


if __name__ == "__main__":

    class CompanyModel(BaseModel):
        id: "int"
        name: str
        city_id: int = mapped(path="location.city.id")
        city: str = mapped(path="location.city.name")
        created_at: datetime

    c = CompanyModel.from_api(
        {
            "id": "42",
            "name": "ACME",
            "location": {
                "city": {
                    "id": "1",
                    "name": "Moscow",
                },
            },
            "created_at": "2026-01-09T04:12:00.114858",
        }
    )

    print(c)
    # assert c == CompanyModel(id=42, name="ACME", city_id=1, city="Moscow")
