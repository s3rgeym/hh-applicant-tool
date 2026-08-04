"""Deterministic tests for two apply fixes:

1. --max-responses is actually enforced in the apply loop.
2. Ctrl+C (SIGINT) triggers graceful shutdown, not a raw traceback.

These tests avoid live hh.ru credentials — they mock the network/API layer,
so they run in any environment (the real /me and /resumes/mine calls return
403 here because the HH token is server-rejected, unrelated to the code).
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from hh_applicant_tool.operations.apply_vacancies import Operation


def _make_vacancy(i: int) -> dict:
    return {
        "id": str(i),
        "name": f"Vacancy {i}",
        "alternate_url": f"https://hh.ru/vacancy/{i}",
        "employer": {},  # no employer id -> no profile fetch
        "snippet": {},
    }


def _make_operation(max_responses: int = 5) -> Operation:
    op = Operation()
    # Namespace-like args used by _apply_resume.
    # NOTE: `args` is a read-only property backed by `_args` (set in run()).
    op._args = SimpleNamespace(
        skip_tests=False,
        send_email=False,
        letter_file=None,
        use_ai=False,
        system_prompt="",
        ai_rate_limit=0,
    )
    op.max_responses = max_responses
    op.dry_run = False
    op.ai_filter = None
    op.vacancy_filter_ai = None
    op.excluded_filter = None
    op.cover_letter = "hello"
    op.force_message = False
    op.send_email = False
    op.json_decoder = __import__(
        "hh_applicant_tool.utils.json",
        fromlist=["JSONDecoder"],
    ).JSONDecoder()

    # Mocked tool with a storage that no-ops saves
    tool = MagicMock()
    tool.storage.vacancies.save.return_value = None
    tool.storage.vacancy_contacts.save.return_value = None
    tool.storage.employers.save.return_value = None
    tool.storage.skipped_vacancies.find.return_value = []
    tool.storage.negotiations.save.return_value = None
    op.tool = tool

    # Each post returns empty dict -> assert res == {} passes, applied_count++.
    # `api_client` is a read-only property returning `tool.api_client`.
    op.tool.api_client = MagicMock()
    op.tool.api_client.post.return_value = {}
    return op


class TestMaxResponses:
    def test_loop_stops_after_max_responses(self):
        """With --max-responses 5 and 20 vacancies, only 5 are applied."""
        op = _make_operation(max_responses=5)
        total = 20
        op._get_vacancies = lambda resume_id=None: iter(
            _make_vacancy(i) for i in range(total)
        )

        resume = {"id": "r1", "title": "Dev", "alternate_url": "u"}
        user = {"first_name": "A", "last_name": "B", "email": "a@b.c", "phone": ""}
        op._apply_resume(resume=resume, user=user, seen_employers=set())

        assert op.tool.api_client.post.call_count == 5

    def test_no_limit_means_no_early_stop(self):
        """Without max-responses, all vacancies are attempted."""
        op = _make_operation(max_responses=0)
        total = 8
        op._get_vacancies = lambda resume_id=None: iter(
            _make_vacancy(i) for i in range(total)
        )

        resume = {"id": "r1", "title": "Dev", "alternate_url": "u"}
        user = {"first_name": "A", "last_name": "B", "email": "a@b.c", "phone": ""}
        op._apply_resume(resume=resume, user=user, seen_employers=set())

        assert op.tool.api_client.post.call_count == total


class TestGracefulShutdown:
    def test_cancel_event_stops_loop_between_vacancies(self):
        """Setting _cancel_event gracefully halts the loop (UI + new CLI path)."""
        op = _make_operation(max_responses=0)
        cancel_event = threading.Event()
        op._cancel_event = cancel_event

        applied = []

        def fake_get(resume_id=None):
            for i in range(20):
                applied.append(i)
                if i == 2:
                    cancel_event.set()
                yield _make_vacancy(i)

        op._get_vacancies = fake_get
        resume = {"id": "r1", "title": "Dev", "alternate_url": "u"}
        user = {"first_name": "A", "last_name": "B", "email": "a@b.c", "phone": ""}
        op._apply_resume(resume=resume, user=user, seen_employers=set())

        # The cancel event yields the first 3, then the loop must break
        assert len(applied) == 3
        assert op.tool.api_client.post.call_count <= 3
