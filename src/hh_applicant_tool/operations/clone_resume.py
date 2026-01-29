# Этот модуль можно использовать как образец для других
from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from hh_applicant_tool.api.errors import ApiError

from ..api import datatypes
from ..main import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    resume_id: str = None


class Operation(BaseOperation):
    """Клонировать резюме"""

    __aliases__ = []

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--resume-id",
            help="Необязательный идентификатор резюме. Если не указать, то будет клонировано дефолтное (первое)",
        )

    def run(self, tool: HHApplicantTool) -> None:
        resumes: list[datatypes.Resume] = tool.get_resumes()
        tool.storage.resumes.save_batch(resumes)
        args = tool.args
        api_client = tool.api_client
        resume = (
            {res["id"]: res for res in resumes}[args.resume_id]
            if args.resume_id
            else resumes[0]
        )

        # payload = {
        #     "additional_properties": {"any_job": True},
        #     # "creds": {"question_to_answer_map": {"14": ["27"]}},
        #     "current_screen_id": "experience",
        #     "profile": {
        #         "last_name": resume.get("last_name"),
        #         "first_name": resume.get("first_name"),
        #         "middle_name": resume.get("middle_name"),
        #         "gender": resume.get("gender"),
        #         "area": resume.get("area"),
        #         "education": {
        #             "level": resume.get("education", {}).get("level"),
        #             "primary": resume.get("education", {}).get("primary", []),
        #             "additional": resume.get("education", {}).get(
        #                 "additional", []
        #             ),
        #             "attestation": resume.get("education", {}).get(
        #                 "attestation", []
        #             ),
        #             "elementary": resume.get("education", {}).get(
        #                 "elementary", []
        #             ),
        #         },
        #     },
        #     "resume": {
        #         "experience": [
        #             {
        #                 "start": exp.get("start"),
        #                 "end": exp.get("end"),
        #                 "company": exp.get("company"),
        #                 "company_id": exp.get("company_id"),
        #                 "company_url": exp.get("company_url"),
        #                 "position": exp.get("position"),
        #                 "description": exp.get("description"),
        #                 "area": exp.get("area"),
        #                 "industries": exp.get("industries", []),
        #             }
        #             for exp in resume.get("experience", [])
        #         ]
        #     },
        # }

        # Добавляем опциональные поля, если они есть в исходнике
        # if "language" in resume:
        #     payload["profile"]["language"] = resume["language"]

        # if "has_vehicle" in resume:
        #     payload["profile"]["has_vehicle"] = resume["has_vehicle"]

        # if "relocation" in resume:
        #     payload["profile"]["relocation"] = resume["relocation"]

        try:
            true = True
            payload = {
                "additional_properties": {"any_job": true},
                "clone_resume_id": resume["id"],
                # "entry_point": "vacancy_response",
                # "lat": 123,
                # "lng": 456,
                # "update_profile": true,
                # "vacancy_id": 1,
            }

            result = api_client.post("/resume_profile", payload, as_json=True)
            logger.debug(result)
        except ApiError as ex:
            logger.error(f"Произошла ошибка при клонировании резюме: {ex}")
