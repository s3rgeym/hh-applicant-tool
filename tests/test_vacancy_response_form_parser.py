from hh_applicant_tool.operations.apply_vacancies import (
    Operation,
    VacancyResponseFormParser,
)


def test_parser_extracts_question_choices_and_text_input():
    parser = VacancyResponseFormParser()
    parser.feed(
        """
        <div data-qa="task-question">Страна гражданства?</div>
        <label>
          <input type="radio" name="task_1" value="a">РФ
        </label>
        <label>
          <input type="radio" name="task_1" value="b">Свой вариант
        </label>
        <input type="text" name="task_1_text" value="">
        """
    )

    assert parser.questions == ["Страна гражданства?"]
    assert parser.choice_groups()["task_1"][1]["label"] == "Свой вариант"
    assert parser.text_inputs()[0]["name"] == "task_1_text"


def test_non_ai_selection_avoids_custom_answer_when_possible():
    op = Operation()
    selected = op._select_test_solution(
        "task_1",
        "Страна гражданства?",
        [
            {
                "type": "radio",
                "name": "task_1",
                "value": "a",
                "label": "РФ",
            },
            {
                "type": "radio",
                "name": "task_1",
                "value": "b",
                "label": "Свой вариант",
            },
        ],
    )

    assert selected
    assert selected["label"] == "РФ"
