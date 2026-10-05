"""Тесты промпта капчи и проверки алфавита ответа.

Причина бага: язык картинки hh.ru задаёт не ссылка на страницу капчи,
а параметр `lang` у `POST /captcha`. Мы его не просили, поэтому картинка
приходила кириллической. Под неё был написан промпт с прямым указанием
`the letters are Cyrillic, never transliterate them into Latin letters` —
и это указание вводило модель в заблуждение, стоило только попросить
английскую картинку.

Замер 2026-10-03 на живых картинках:

* `lang=EN` — картинка 71-89 КБ, чтения `stroot shippers` (3 из 3) и
  `landslips chuse` (2 из 3), формат чистый;
* `lang=RU` — картинка 80 КБ, чтения `РЫХЛ УДАВЛЕННУЮ` и `дрюнули` /
  `дрыгнули` / `дыгнули`, причём пять чтений единогласно давали три
  разных ответа на трёх вариантах промпта.

Вторая половина этих тестов проверяет, что ответ не чужого алфавита
больше не считается ответом. Раньше `_parse_captcha_json` проверяла
только непустоту полей, поэтому русские буквы спокойно уезжали в поле,
где hh.ru ждёт латиницу.
"""

from __future__ import annotations

from argparse import ArgumentParser
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hh_applicant_tool.ai.openai import (
    CAPTCHA_SCRIPT_ANY,
    CAPTCHA_SCRIPT_CYRILLIC,
    CAPTCHA_SCRIPT_LATIN,
    ChatOpenAI,
    OpenAIError,
    _foreign_letters,
    captcha_script,
)
from hh_applicant_tool.operations.apply_vacancies import Operation


def _raw(first: str, second: str) -> str:
    return f'{{"first_word": "{first}", "second_word": "{second}"}}'


class TestCaptchaScript:
    """Язык картинки однозначно задаёт ожидаемый алфавит ответа."""

    @pytest.mark.parametrize(
        ("language", "expected"),
        [
            ("en", CAPTCHA_SCRIPT_LATIN),
            ("EN", CAPTCHA_SCRIPT_LATIN),
            ("ru", CAPTCHA_SCRIPT_CYRILLIC),
            ("RU", CAPTCHA_SCRIPT_CYRILLIC),
            (" en ", CAPTCHA_SCRIPT_LATIN),
            # Неизвестный язык трактуем как английский: дефолт
            # DEFAULT_CAPTCHA_LANGUAGE тоже en
            ("fr", CAPTCHA_SCRIPT_LATIN),
            ("", CAPTCHA_SCRIPT_LATIN),
        ],
    )
    def test_language_maps_to_script(
        self, language: str, expected: str
    ) -> None:
        assert captcha_script(language) == expected

    def test_any_is_passed_through(self) -> None:
        """Браузерный путь не управляет языком и просит «любой алфавит»."""
        assert captcha_script(CAPTCHA_SCRIPT_ANY) == CAPTCHA_SCRIPT_ANY


class TestPrompts:
    """Промпт должен говорить про тот алфавит, который в картинке."""

    def prompts(self, script: str) -> str:
        return (
            ChatOpenAI.CAPTCHA_PROMPT_COMMON
            + ChatOpenAI.CAPTCHA_PROMPT_RULES[script]
        )

    def test_latin_prompt_does_not_claim_cyrillic(self) -> None:
        """Главная ошибка прежнего промпта: кириллическое указание в
        латинском варианте заставляло модель переводить буквы."""
        prompt = self.prompts(CAPTCHA_SCRIPT_LATIN)
        # Утверждения «буквы кириллические» быть не должно. Отрицание
        # «не превращай в кириллицу» наоборот нужно
        assert "The letters are Cyrillic" not in prompt
        assert "never turn them into Cyrillic" in prompt
        assert "The letters are LATIN" in prompt

    def test_cyrillic_prompt_keeps_dont_transliterate(self) -> None:
        prompt = self.prompts(CAPTCHA_SCRIPT_CYRILLIC)
        assert "The letters are Cyrillic" in prompt
        assert "never transliterate them into Latin" in prompt
        assert "Copy ё as ё" in prompt

    def test_latin_prompt_has_no_yo_instruction(self) -> None:
        """«Copy ё as ё» в латинском варианте бессмысленно и сбивает."""
        assert "ё" not in self.prompts(CAPTCHA_SCRIPT_LATIN)

    @pytest.mark.parametrize(
        "script", [CAPTCHA_SCRIPT_LATIN, CAPTCHA_SCRIPT_CYRILLIC]
    )
    def test_both_prompts_keep_arc_and_no_repair(self, script: str) -> None:
        """Дуга и запрет чинить слова работают в обоих алфавитах, их
        нашли на живых картинках и они не зависят от скрипта."""
        prompt = self.prompts(script)
        assert "along an arc" in prompt
        assert "do NOT" in prompt and "repair them" in prompt
        assert '"first_word"' in prompt and '"second_word"' in prompt

    @pytest.mark.parametrize(
        "script",
        [CAPTCHA_SCRIPT_LATIN, CAPTCHA_SCRIPT_CYRILLIC, CAPTCHA_SCRIPT_ANY],
    )
    def test_all_scripts_have_user_prompt(self, script: str) -> None:
        assert '"first_word"' in ChatOpenAI.CAPTCHA_USER_PROMPT[script]

    def test_no_cyrillic_wording_in_latin_user_prompt(self) -> None:
        assert "Latin" in ChatOpenAI.CAPTCHA_USER_PROMPT[CAPTCHA_SCRIPT_LATIN]

    def test_old_single_prompt_is_gone(self) -> None:
        """Старая константа с кириллицей намертво прибита: из неё
        собраны обе версии, и вернуться к ней нельзя."""
        assert not hasattr(ChatOpenAI, "CAPTCHA_SYSTEM_PROMPT")


class TestForeignLetters:
    def test_latin_in_cyrillic_answer_found(self) -> None:
        assert _foreign_letters("драфт latin", CAPTCHA_SCRIPT_CYRILLIC)

    def test_cyrillic_in_latin_answer_found(self) -> None:
        found = _foreign_letters("драфт latin", CAPTCHA_SCRIPT_LATIN)
        assert found == ["а", "д", "р", "т", "ф"]

    def test_clean_answer_has_none(self) -> None:
        assert _foreign_letters("stroot shippers", CAPTCHA_SCRIPT_LATIN) == []
        assert _foreign_letters("рыхл удавленную", CAPTCHA_SCRIPT_CYRILLIC) == []

    def test_any_script_accepts_both(self) -> None:
        assert _foreign_letters("драфт latin", CAPTCHA_SCRIPT_ANY) == []


class TestParseCaptchaJson:
    """Парсер ответа модели."""

    def test_latin_answer_accepted(self) -> None:
        result = ChatOpenAI._parse_captcha_json(
            _raw("Stroot", " Shippers "), CAPTCHA_SCRIPT_LATIN
        )
        assert result == "stroot shippers"

    def test_cyrillic_answer_accepted(self) -> None:
        result = ChatOpenAI._parse_captcha_json(
            _raw("РЫХЛ", "удавленную"), CAPTCHA_SCRIPT_CYRILLIC
        )
        assert result == "рыхл удавленную"

    def test_yo_preserved(self) -> None:
        result = ChatOpenAI._parse_captcha_json(
            _raw("ёлка", "пень"), CAPTCHA_SCRIPT_CYRILLIC
        )
        assert result == "ёлка пень"

    def test_cyrillic_answer_rejected_when_latin_expected(self) -> None:
        """Раньше такое уезжало в поле ввода как есть, и hh.ru засчитывал
        ответ как промах."""
        with pytest.raises(OpenAIError, match="алфавит"):
            ChatOpenAI._parse_captcha_json(
                _raw("рыхл", "удав"), CAPTCHA_SCRIPT_LATIN
            )

    def test_latin_answer_rejected_when_cyrillic_expected(self) -> None:
        with pytest.raises(OpenAIError, match="алфавит"):
            ChatOpenAI._parse_captcha_json(
                _raw("stroot", "shippers"), CAPTCHA_SCRIPT_CYRILLIC
            )

    def test_any_script_takes_either(self) -> None:
        assert (
            ChatOpenAI._parse_captcha_json(
                _raw("рыхл", "удав"), CAPTCHA_SCRIPT_ANY
            )
            == "рыхл удав"
        )
        assert (
            ChatOpenAI._parse_captcha_json(
                _raw("stroot", "ship"), CAPTCHA_SCRIPT_ANY
            )
            == "stroot ship"
        )

    def test_missing_json_still_raises(self) -> None:
        with pytest.raises(OpenAIError):
            ChatOpenAI._parse_captcha_json("stroot shippers", CAPTCHA_SCRIPT_LATIN)

    def test_empty_word_still_raises(self) -> None:
        with pytest.raises(OpenAIError, match="оба слова"):
            ChatOpenAI._parse_captcha_json(
                _raw("", "shippers"), CAPTCHA_SCRIPT_LATIN
            )

    def test_wording_around_json_tolerated(self) -> None:
        raw = f'The text is {_raw("stroot", "shippers")} I hope'
        result = ChatOpenAI._parse_captcha_json(raw, CAPTCHA_SCRIPT_LATIN)
        assert result == "stroot shippers"


class TestPayload:
    """В запрос к модели уходит промпт нужного алфавита."""

    def client(self) -> ChatOpenAI:
        return ChatOpenAI.__new__(ChatOpenAI)

    def test_payload_uses_latin_prompt_for_english(self) -> None:
        payload = self.client()._captcha_payload(
            "YmFzZTY0", "image/png", 0.7, CAPTCHA_SCRIPT_LATIN
        )
        system = payload["messages"][0]["content"]
        assert "The letters are LATIN" in system
        assert "The letters are Cyrillic" not in system
        assert "Latin words" in payload["messages"][1]["content"][1]["text"]

    def test_payload_keeps_high_detail(self) -> None:
        payload = self.client()._captcha_payload(
            "YmFzZTY0", "image/png", 0.7, CAPTCHA_SCRIPT_LATIN
        )
        image = payload["messages"][1]["content"][0]["image_url"]
        assert image["detail"] == "high"
        assert image["url"] == "data:image/png;base64,YmFzZTY0"

    def test_payload_keeps_token_budget(self) -> None:
        payload = self.client()._captcha_payload(
            "YmFzZTY0", "image/png", 0.7, CAPTCHA_SCRIPT_LATIN
        )
        assert payload["max_completion_tokens"] == 100


def _operation(config: dict | None = None, **flags) -> Operation:
    operation = Operation()
    operation._args = SimpleNamespace(**flags)
    operation.tool = MagicMock()
    operation.tool.config = config or {}
    return operation


class TestSettingsResolution:
    """Флаг важнее config.json, config важнее встроенного умолчания."""

    def test_transport_defaults_to_http(self) -> None:
        """Браузер нужен был только чтобы прочитать PNG и отправить одно
        поле, после чего поток возвращался в requests."""
        assert _operation()._captcha_transport() == "http"

    def test_transport_from_config(self) -> None:
        operation = _operation({"captcha_transport": "browser"})
        assert operation._captcha_transport() == "browser"

    def test_transport_flag_wins_over_config(self) -> None:
        operation = _operation(
            {"captcha_transport": "browser"}, captcha_transport="http"
        )
        assert operation._captcha_transport() == "http"

    def test_transport_normalizes_case(self) -> None:
        operation = _operation({"captcha_transport": " HTTP "})
        assert operation._captcha_transport() == "http"

    def test_unknown_transport_falls_back(self) -> None:
        operation = _operation({"captcha_transport": "telepathy"})
        assert operation._captcha_transport() == "http"

    def test_language_defaults_to_latin(self) -> None:
        assert _operation()._captcha_language() == "en"

    def test_language_from_config(self) -> None:
        operation = _operation({"captcha_language": "ru"})
        assert operation._captcha_language() == "ru"

    def test_language_flag_wins(self) -> None:
        operation = _operation(
            {"captcha_language": "ru"}, captcha_language="en"
        )
        assert operation._captcha_language() == "en"

    def test_unknown_language_falls_back(self) -> None:
        operation = _operation({"captcha_language": "de"})
        assert operation._captcha_language() == "en"

    def test_empty_config_value_falls_back(self) -> None:
        operation = _operation({"captcha_language": "  "})
        assert operation._captcha_language() == "en"


class TestParser:
    """Новые флаги доходят до аргументов операции."""

    def parser(self) -> ArgumentParser:
        parser = ArgumentParser()
        Operation().setup_parser(parser)
        return parser

    def test_transport_flag_parses(self) -> None:
        args = self.parser().parse_args(["--captcha-transport", "browser"])
        assert args.captcha_transport == "browser"

    def test_language_flag_parses(self) -> None:
        args = self.parser().parse_args(["--captcha-language", "ru"])
        assert args.captcha_language == "ru"

    def test_flags_default_to_none(self) -> None:
        """None значит «не задано», чтобы дать config.json chance."""
        args = self.parser().parse_args([])
        assert args.captcha_transport is None
        assert args.captcha_language is None

    def test_rejects_unknown_transport(self) -> None:
        with pytest.raises(SystemExit):
            self.parser().parse_args(["--captcha-transport", "telepathy"])

    def test_rejects_unknown_language(self) -> None:
        with pytest.raises(SystemExit):
            self.parser().parse_args(["--captcha-language", "de"])

    def test_existing_captcha_flags_still_work(self) -> None:
        args = self.parser().parse_args(
            [
                "--captcha-strategy", "single",
                "--captcha-samples", "3",
                "--captcha-min-votes", "2",
            ]
        )
        assert args.captcha_strategy == "single"
        assert args.captcha_samples == 3
        assert args.captcha_min_votes == 2