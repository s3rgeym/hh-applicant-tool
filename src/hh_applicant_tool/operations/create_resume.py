from __future__ import annotations

import argparse
import logging
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..api import ApiError
from ..main import BaseNamespace, BaseOperation
from ..utils import json
from ..utils.resume_md import parse_resume_md

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


def _load_template(path: Path) -> dict[str, Any]:
    if path.suffix == ".toml":
        with path.open("rb") as f:
            return tomllib.load(f)
    # .md — markdown-шаблон с русскими заголовками
    return parse_resume_md(path.read_text(encoding="utf-8"))


def _drop_nulls(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _drop_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_drop_nulls(v) for v in obj if v is not None]
    return obj


def _suggest_first(api_client: Any, endpoint: str, text: str) -> dict | None:
    try:
        items = api_client.get(endpoint, text=text).get("items", [])
        return items[0] if items else None
    except ApiError as ex:
        logger.warning("suggest %s %r: %s", endpoint, text, ex)
        return None


def _resolve_suggests(api_client: Any, obj: Any) -> None:
    """
    Рекурсивно заменяет {_suggest: endpoint, text: name}
    на результат запроса к suggest-эндпоинту: {id: ..., name: ...}
    """
    if isinstance(obj, dict):
        if "_suggest" in obj and "text" in obj:
            endpoint = obj.pop("_suggest")
            text = obj.pop("text")
            found = _suggest_first(api_client, endpoint, text)
            if found:
                obj.update({"id": found.get("id"), "name": found.get("name")})
                logger.debug("resolved %r → id=%s", text, obj.get("id"))
            else:
                logger.warning("suggest не нашёл результатов для %r (endpoint: %s)", text, endpoint)
        else:
            for v in obj.values():
                _resolve_suggests(api_client, v)
    elif isinstance(obj, list):
        for item in obj:
            _resolve_suggests(api_client, item)


def _resolve_industries(api_client: Any, experience: list[dict]) -> None:
    """Разрешает названия отраслей в ID через GET /industries."""
    needs_resolve = any(
        not ind.get("id")
        for exp in experience
        for ind in exp.get("industries", [])
    )
    if not needs_resolve:
        return
    try:
        tree = api_client.get("/industries")
    except ApiError as ex:
        logger.warning("Не удалось загрузить справочник отраслей: %s", ex)
        return

    flat: dict[str, str] = {}
    for industry in tree:
        flat[industry["name"].lower()] = industry["id"]
        for sub in industry.get("industries", []):
            flat[sub["name"].lower()] = sub["id"]

    for exp in experience:
        for ind in exp.get("industries", []):
            if ind.get("id"):
                continue
            name = ind.get("name", "")
            name_l = name.lower()
            match = flat.get(name_l) or next(
                (v for k, v in flat.items() if name_l in k or k in name_l), None
            )
            if match:
                ind["id"] = match
            else:
                logger.warning("Отрасль не найдена в справочнике: %r", name)


class Namespace(BaseNamespace):
    template: Path
    dry_run: bool
    publish: bool


class Operation(BaseOperation):
    """Создать резюме из markdown-шаблона (docs/resume_template.md)"""

    __aliases__ = ["create-resume"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "template",
            type=Path,
            help="Путь до шаблона резюме (.md или .toml)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать итоговый payload без отправки запроса",
        )
        parser.add_argument(
            "--publish",
            action="store_true",
            help="Опубликовать резюме сразу после создания",
        )

    def run(self, tool: HHApplicantTool, args: Namespace) -> int | None:
        if not args.template.exists():
            logger.error("Файл шаблона не найден: %s", args.template)
            return 1

        try:
            data = _load_template(args.template)
        except Exception as ex:
            logger.error("Ошибка разбора шаблона: %s", ex)
            return 1

        api_client = tool.api_client

        _resolve_suggests(api_client, data)
        if experience := data.get("experience"):
            _resolve_industries(api_client, experience)

        payload = _drop_nulls(data)

        if args.dry_run:
            print(json.dumps(payload, indent=2))
            return None

        before_ids = {r["id"] for r in tool.get_resumes()}

        try:
            result = api_client.post("/resumes", payload, as_json=True)
            logger.debug("POST /resumes response: %s", result)
        except ApiError as ex:
            logger.error("Ошибка при создании резюме: %s", ex)
            return 1

        resume_id: str | None = result.get("id")
        if not resume_id:
            new = [r for r in tool.get_resumes() if r["id"] not in before_ids]
            if new:
                resume_id = new[0]["id"]

        print("✅ Резюме создано")
        if resume_id:
            print(f"   https://hh.ru/resume/{resume_id}")

        if args.publish and resume_id:
            try:
                api_client.post(f"/resumes/{resume_id}/publish")
                print("✅ Резюме опубликовано")
            except ApiError as ex:
                logger.error("Ошибка при публикации: %s", ex)

        return None
