from __future__ import annotations

from hh_applicant_tool.operations.apply_vacancies import (
    Operation,
    VacancyTestsNotFoundError,
)


def test_solve_vacancy_test_handles_missing_tests(monkeypatch) -> None:
    op = Operation()

    def raise_missing_tests(_response_url: str) -> None:
        raise VacancyTestsNotFoundError("tests not found.")

    monkeypatch.setattr(op, "_get_vacancy_tests", raise_missing_tests)

    assert (
        op._solve_vacancy_test(
            vacancy_id=123,
            resume_hash="resume-hash",
        )
        == {"success": "false", "error": "tests-not-found"}
    )
