from typing import TypedDict


class CandidateSolution(TypedDict):
    id: str
    text: str


class VacancyTask(TypedDict):
    id: int
    description: str
    multiple: str  # В JSON прилетает строкой "false"/"true"
    open: str  # То же самое
    candidateSolutions: list[CandidateSolution]


class VacancyTest(TypedDict):
    uidPk: str
    guid: str
    name: str
    description: str
    required: str  # Опять же, строка "true"
    startTime: str
    tasks: list[VacancyTask]


# Финальный тип для всей структуры
VacancyTestsData = dict[str, VacancyTest]
