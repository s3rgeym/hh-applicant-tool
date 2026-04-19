from __future__ import annotations

import argparse
import io
import json
import logging
import threading
from contextlib import redirect_stdout
from typing import TYPE_CHECKING, Any

from .presets import PresetValidationError, PresetsManager

if TYPE_CHECKING:
    from ..main import HHApplicantTool

logger = logging.getLogger(__package__)

MASKED_KEYS = {"client_secret", "token"}
SENSITIVE_FIELD_NAMES = {
    "api_key",
    "password",
    "client_secret",
    "token",
    "proxy_url",
    "openai_proxy_url",
}
MASK_VALUE = "***"


def _mask_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: MASK_VALUE if k in SENSITIVE_FIELD_NAMES else _mask_secrets(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_mask_secrets(x) for x in obj]
    return obj


def _strip_masked(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _strip_masked(v)
            for k, v in obj.items()
            if v != MASK_VALUE
        }
    if isinstance(obj, list):
        return [_strip_masked(x) for x in obj]
    return obj


def _merge_config(current: Any, updates: Any) -> Any:
    if isinstance(current, dict) and isinstance(updates, dict):
        merged = dict(current)
        for key, value in updates.items():
            merged[key] = _merge_config(current.get(key), value)
        return merged
    return updates


class _ProgressHandler(logging.Handler):
    def __init__(self, api: "Api") -> None:
        super().__init__(logging.INFO)
        self._api = api
        self._count = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._count += 1
            self._api._send_progress(self._count, 0, msg)
        except Exception:
            pass


class Api:
    def __init__(self, tool: HHApplicantTool):
        self._tool = tool
        self._window = None
        self._presets = PresetsManager(tool.storage.settings)
        self._cancel_event: threading.Event | None = None

    def set_window(self, window) -> None:
        self._window = window

    def _send_progress(self, current: int, total: int, message: str = "") -> None:
        if self._window:
            safe_msg = json.dumps(message)
            self._window.evaluate_js(
                f"updateProgress({current}, {total}, {safe_msg})"
            )

    def get_status(self) -> dict[str, Any]:
        try:
            user = self._tool.get_me()
            return {"authorized": True, "user": user}
        except Exception as e:
            logger.warning("get_status error: %s", e)
            return {"authorized": False, "user": None}

    def get_resumes(self) -> list[dict]:
        try:
            return self._tool.get_resumes()
        except Exception as e:
            logger.error("get_resumes error: %s", e)
            return []

    def get_config(self) -> dict[str, Any]:
        return _mask_secrets(dict(self._tool.config))

    def save_config(self, updates: dict[str, Any]) -> dict[str, str]:
        try:
            clean = {
                k: _strip_masked(v)
                for k, v in updates.items()
                if k not in MASKED_KEYS and v != MASK_VALUE
            }
            merged = {
                key: _merge_config(self._tool.config.get(key), value)
                for key, value in clean.items()
            }
            self._tool.config.save(**merged)
            return {"status": "ok"}
        except Exception as e:
            logger.error("save_config error: %s", e)
            return {"status": "error", "message": "Ошибка сохранения конфигурации"}

    def list_presets(self) -> list[str]:
        return self._presets.list_names()

    def save_preset(self, name: str, params: dict[str, Any]) -> dict[str, str]:
        try:
            self._presets.save(name, params)
            return {"status": "ok"}
        except PresetValidationError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.error("save_preset error: %s", e)
            return {"status": "error", "message": "Ошибка сохранения пресета"}

    def load_preset(self, name: str) -> dict[str, Any] | None:
        return self._presets.load(name)

    def delete_preset(self, name: str) -> None:
        self._presets.delete(name)

    def get_last_used_params(self) -> dict[str, Any] | None:
        return self._presets.load_last_used()

    def save_last_used_params(self, params: dict[str, Any]) -> None:
        try:
            self._presets.save_last_used(params)
        except PresetValidationError as e:
            logger.warning("save_last_used_params rejected: %s", e)
        except Exception as e:
            logger.error("save_last_used_params error: %s", e)

    def get_negotiations_from_db(self) -> list[dict]:
        try:
            conn = self._tool.storage.negotiations.conn
            cur = conn.execute(
                """
                SELECT n.id, n.state, n.vacancy_id, n.employer_id,
                       n.created_at,
                       v.name AS vacancy_name,
                       v.alternate_url AS vacancy_url,
                       e.name AS employer_name
                FROM negotiations n
                LEFT JOIN vacancies v ON v.id = n.vacancy_id
                LEFT JOIN employers e ON e.id = n.employer_id
                ORDER BY n.created_at DESC
                LIMIT 500
                """
            )
            cols = [d[0] for d in cur.description]
            return [
                dict(zip(cols, row, strict=True))
                for row in cur.fetchall()
            ]
        except Exception as e:
            logger.error("get_negotiations_from_db error: %s", e)
            return []

    def refresh_negotiations(self, status: str = "active") -> dict:
        try:
            from ..storage.models.negotiation import NegotiationModel

            count = 0
            for item in self._tool.get_negotiations(status):
                model = NegotiationModel.from_dict(item)
                self._tool.storage.negotiations.save(model)
                count += 1
            return {"status": "ok", "count": count}
        except Exception as e:
            logger.error("refresh_negotiations error: %s", e)
            return {
                "status": "error",
                "message": "Ошибка синхронизации откликов",
            }

    def get_statistics(self) -> dict:
        try:
            conn = self._tool.storage.negotiations.conn
            stats: dict[str, Any] = {}

            cur = conn.execute(
                "SELECT state, count(*) FROM negotiations GROUP BY state"
            )
            stats["by_state"] = dict(cur.fetchall())

            cur = conn.execute(
                "SELECT reason, count(*) FROM skipped_vacancies"
                " GROUP BY reason"
            )
            stats["skipped_by_reason"] = dict(cur.fetchall())

            cur = conn.execute(
                "SELECT date(created_at) AS day, count(*)"
                " FROM negotiations"
                " WHERE created_at >= date('now', '-30 days')"
                " GROUP BY day ORDER BY day"
            )
            stats["daily_negotiations"] = dict(cur.fetchall())

            cur = conn.execute(
                "SELECT date(created_at) AS day, count(*)"
                " FROM skipped_vacancies"
                " WHERE created_at >= date('now', '-30 days')"
                " GROUP BY day ORDER BY day"
            )
            stats["daily_skipped"] = dict(cur.fetchall())

            stats["total_negotiations"] = sum(
                stats["by_state"].values()
            )
            stats["total_skipped"] = sum(
                stats["skipped_by_reason"].values()
            )

            return stats
        except Exception as e:
            logger.error("get_statistics error: %s", e)
            return {}

    def apply_vacancies(self, params: dict[str, Any]) -> dict[str, Any]:
        self._presets.save_last_used(params)

        cancel_event = threading.Event()
        self._cancel_event = cancel_event

        handler = _ProgressHandler(self)
        pkg_logger = logging.getLogger("hh_applicant_tool")
        pkg_logger.addHandler(handler)

        class _PrintCapture(io.StringIO):
            def write(self_inner, s: str) -> int:
                s = s.rstrip("\n")
                if s:
                    handler._count += 1
                    self._send_progress(handler._count, 0, s)
                return len(s)

        try:
            from ..operations.apply_vacancies import Namespace, Operation

            argv = self._params_to_argv(params)
            op = Operation()
            parser = argparse.ArgumentParser()
            op.setup_parser(parser)
            try:
                args = parser.parse_args(argv, namespace=Namespace())
            except SystemExit:
                return {
                    "status": "error",
                    "message": "Неверные параметры поиска",
                }
            args._cancel_event = cancel_event
            op._cancel_event = cancel_event

            with redirect_stdout(_PrintCapture()):
                op.run(self._tool, args)

            if cancel_event.is_set():
                return {"status": "cancelled"}
            return {"status": "ok"}
        except Exception as e:
            logger.error("apply_vacancies error: %s", e)
            return {
                "status": "error",
                "message": "Ошибка выполнения операции",
            }
        finally:
            pkg_logger.removeHandler(handler)
            self._cancel_event = None

    def cancel_apply(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    @staticmethod
    def _params_to_argv(params: dict[str, Any]) -> list[str]:
        argv = []
        for key, value in params.items():
            if value is None or value is False:
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            flag = f"--{key.replace('_', '-')}"
            if value is True:
                argv.append(flag)
            elif isinstance(value, list):
                argv.append(flag)
                argv.extend(str(item) for item in value)
            else:
                argv.extend([flag, str(value)])
        return argv

    def get_areas(self) -> list[dict]:
        try:
            def flatten(nodes: list, result: list, depth: int = 0) -> None:
                for node in nodes:
                    result.append({
                        "id": node["id"],
                        "name": ("  " * depth) + node["name"],
                    })
                    if node.get("areas"):
                        flatten(node["areas"], result, depth + 1)

            data = self._tool.api_client.get("/areas")
            result: list[dict] = []
            flatten(data, result)
            return result
        except Exception as e:
            logger.error("get_areas error: %s", e)
            return []

    def get_professional_roles(self) -> list[dict]:
        try:
            data = self._tool.api_client.get("/professional_roles")
            result = []
            for cat in data.get("categories", []):
                for role in cat.get("roles", []):
                    result.append({"id": role["id"], "name": role["name"]})
            return result
        except Exception as e:
            logger.error("get_professional_roles error: %s", e)
            return []

    def get_industries(self) -> list[dict]:
        try:
            data = self._tool.api_client.get("/industries")
            result = []
            for item in data:
                result.append({"id": item["id"], "name": item["name"]})
                for sub in item.get("industries", []):
                    result.append({"id": sub["id"], "name": "  " + sub["name"]})
            return result
        except Exception as e:
            logger.error("get_industries error: %s", e)
            return []
