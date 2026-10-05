"""Поисковая строка подставляется из тайтла резюме.

hh.ru подбирает похожие вакансии только по навыкам резюме, и на
«разработчике» в выдачу попадают сборщики компьютеров. Когда --search не
задан, запрос уходит в /resumes/{id}/similar_vacancies, поэтому текстовый
запрос в него не подставлялся вообще. Тест ловит именно params, которые
уходят в API, без обращения к hh.ru.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hh_applicant_tool.operations.apply_vacancies import Operation


def _make_operation(search: str | None = None, no_magic: bool = False):
    op = Operation()
    op.search = search or ""
    op.no_magic = no_magic
    op.per_page = 10
    op.total_pages = 1
    op.order_by = ""
    for attr in (
        "schedule",
        "work_format",
        "experience",
        "currency",
        "salary",
        "period",
        "date_from",
        "date_to",
        "top_lat",
        "bottom_lat",
        "left_lng",
        "right_lng",
        "sort_point_lat",
        "sort_point_lng",
        "search_field",
        "employment",
        "area",
        "metro",
        "professional_role",
        "industry",
        "employer_id",
        "excluded_employer_id",
        "label",
    ):
        setattr(op, attr, None)
    op.only_with_salary = False
    op.premium = False

    tool = MagicMock()
    # Одна страница, один элемент — иначе генератор уйдёт в пагинацию
    tool.api_client.get.return_value = {
        "found": 1,
        "pages": 1,
        "items": [{"id": "1"}],
    }
    op.tool = tool
    return op


def _last_params(op) -> tuple[str, dict]:
    url, params = op.tool.api_client.get.call_args[0]
    return url, params


class TestSearchTextFallback:
    def test_title_is_used_when_search_not_given(self):
        """Без --search текстовый запрос берётся из тайтла резюме."""
        op = _make_operation()

        list(
            op._get_vacancies(resume_id="r1", resume_title="Python разработчик")
        )

        url, params = _last_params(op)
        assert url == "/resumes/r1/similar_vacancies"
        assert params["text"] == "Python разработчик"

    def test_explicit_search_wins_over_title(self):
        """Явный --search не перебивается тайтлом."""
        op = _make_operation(search="python")

        list(
            op._get_vacancies(resume_id="r1", resume_title="Python разработчик")
        )

        url, params = _last_params(op)
        assert url == "/vacancies"
        assert params["text"] == "python"

    def test_magic_is_on_by_default(self):
        """Без --no-magic magic включён, параметр уходит явно."""
        op = _make_operation()

        list(op._get_vacancies(resume_id="r1", resume_title="Dev"))

        _, params = _last_params(op)
        assert params["no_magic"] == "false"

    def test_no_magic_flag_disables_magic(self):
        """--no-magic по-прежнему выключает авторазбор."""
        op = _make_operation(no_magic=True)

        list(op._get_vacancies(resume_id="r1", resume_title="Dev"))

        _, params = _last_params(op)
        assert params["no_magic"] == "true"

    def test_no_text_without_resume_title(self):
        """Без --search и без тайтла запрос уходит как раньше."""
        op = _make_operation()

        list(op._get_vacancies(resume_id="r1"))

        url, params = _last_params(op)
        assert url == "/resumes/r1/similar_vacancies"
        assert "text" not in params