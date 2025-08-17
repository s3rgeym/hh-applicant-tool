# Этот модуль можно использовать как образец для других
import argparse
import json
import logging

from ..api import ApiClient
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Выведет текущего пользователя"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, api_client: ApiClient, _) -> dict:
        result = api_client.get("/resumes/mine")
        resume_ids = [i['id'] for i in result['items']]
        resume_infos = dict()
        for id in resume_ids:
            resume_infos[id] = api_client.get(f'resumes/{id}')
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return resume_infos
