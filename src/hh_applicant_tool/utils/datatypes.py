from typing import TypedDict


class CandidateSolution(TypedDict):
    id: str
    text: str


class VacancyTask(TypedDict):
    id: int
    description: str
    multiple: str
    open: str
    candidateSolutions: list[CandidateSolution]


class VacancyTest(TypedDict):
    uidPk: str
    guid: str
    name: str
    description: str
    required: str
    startTime: str
    tasks: list[VacancyTask]


type VacancyTestsData = dict[str, VacancyTest]
