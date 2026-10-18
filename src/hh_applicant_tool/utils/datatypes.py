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


class ResumePlaceholders(TypedDict):
    first_name: str
    middle_name: str
    last_name: str
    resume_title: str
    resume_city: str
    resume_about: str
    resume_skills: str
    resume_employment_form: str
    resume_work_format: str
    resume_citizenship: str
    resume_salary: str
    resume_education: str
    resume_experience: str
