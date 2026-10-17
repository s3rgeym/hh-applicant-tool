from typing import Any, Literal, TypedDict

NegotiationStateId = Literal[
    "discard",
    "interview",
    "response",
    "invitation",
    "hired",
]


# --- Общие ---------------------------------------------------------------


class AccessToken(TypedDict):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: Literal["bearer"]


class PaginatedItems[T](TypedDict):
    items: list[T]
    found: int
    page: int
    pages: int
    per_page: int
    clusters: Any
    arguments: Any
    fixes: Any
    suggests: Any
    alternate_url: str


class IdName(TypedDict):
    id: str
    name: str


# Ключи "from" и "90"/"240" не годятся для class-синтаксиса,
# поэтому эти два типа остаются в функциональной форме.
Salary = TypedDict(
    "Salary",
    {
        "from": int | None,
        "to": int | None,
        "currency": str,
        "gross": bool,
    },
)

LogoUrls = TypedDict("LogoUrls", {"original": str, "90": str, "240": str})


class SalaryRange(Salary):
    mode: IdName
    frequency: IdName | None


# --- Работодатели --------------------------------------------------------


class EmployerShort(TypedDict):
    id: str
    name: str
    url: str
    alternate_url: str
    logo_urls: LogoUrls | None
    vacancies_url: str
    accredited_it_employer: bool
    trusted: bool


type NegotiationEmployer = EmployerShort


class SearchEmployer(EmployerShort):
    country_id: int | None


class VacancyEmployer(SearchEmployer):
    badges: list[Any]
    applicant_services: dict[str, dict[str, int]]
    blacklisted: bool
    is_identified_by_esia: bool
    employer_on_additional_check: bool


class Employer(EmployerShort):
    has_divisions: bool
    type: str
    description: str | None
    site_url: str
    relations: list[Any]
    area: IdName
    country_code: str
    industries: list[Any]
    is_identified_by_esia: bool
    badges: list[Any]
    branded_description: str | None
    branding: dict[str, Any] | None
    insider_interviews: list[Any]
    open_vacancies: int
    applicant_services: dict[str, dict[str, int]]


# --- Вакансии ------------------------------------------------------------


class VacancyBase(TypedDict):
    """Поля, общие для всех представлений вакансии."""

    id: str
    premium: bool
    name: str
    department: dict[str, Any] | None
    has_test: bool
    response_letter_required: bool
    area: IdName
    salary: Salary | None
    salary_range: SalaryRange | None
    type: IdName
    address: dict[str, Any] | None
    response_url: str | None
    published_at: str
    created_at: str
    archived: bool
    apply_alternate_url: str
    show_contacts: bool
    insider_interview: dict[str, Any] | None
    alternate_url: str
    professional_roles: list[IdName]


class VacancyDetails(VacancyBase):
    """Поля, которые есть и в поиске, и в полной вакансии."""

    relations: list[Any]
    experimental_modes: list[str]
    contacts: dict[str, Any] | None
    schedule: IdName
    working_days: list[Any]
    working_time_intervals: list[IdName]
    working_time_modes: list[Any]
    accept_temporary: bool
    fly_in_fly_out_duration: list[Any]
    work_format: list[IdName]
    working_hours: list[IdName]
    work_schedule_by_days: list[IdName]
    accept_labor_contract: bool
    civil_law_contracts: list[IdName]
    night_shifts: bool
    accept_incomplete_resumes: bool
    experience: IdName
    employment: IdName
    employment_form: IdName
    internship: bool
    allow_chat_with_manager: bool


class VacancyShort(VacancyBase):
    sort_point_distance: float | None
    benefits: list[Any]
    url: str


class NegotiationVacancy(VacancyShort):
    employer: EmployerShort
    show_logo_in_search: bool | None


class SearchVacancy(VacancyShort, VacancyDetails):
    employer: SearchEmployer
    manager_activity: dict[str, str] | None
    snippet: dict[str, str | None]
    adv_response_url: str | None
    is_adv_vacancy: bool
    adv_context: dict[str, Any] | None
    key_skills: list[dict[str, str]] | None


class Vacancy(VacancyDetails):
    employer: VacancyEmployer
    billing_type: IdName
    allow_messages: bool
    description: str
    inclusiveness_description: Any
    inclusiveness_types: list[Any]
    branded_description: Any
    vacancy_constructor_template: Any
    key_skills: list[dict[str, str]]
    auto_response: dict[str, bool]
    accept_handicapped: bool
    accept_kids: bool
    age_restriction: Any
    specializations: list[Any]
    code: Any
    hidden: bool
    quick_responses_allowed: bool
    driver_license_types: list[Any]
    initial_created_at: str
    negotiations_url: str
    suitable_resumes_url: str
    has_test: bool
    test: Any
    immediate_redirect_url: str
    languages: list[Any]
    branding: Any
    approved: bool
    show_logo_in_search: bool
    closed_for_applicants: bool
    vacancy_properties: dict[str, Any]
    show_question_input: bool


# --- Резюме и пользователь -----------------------------------------------


class ResumeShort(TypedDict):
    id: str
    title: str
    url: str
    alternate_url: str


class Resume(ResumeShort):
    status: IdName
    created_at: str
    updated_at: str
    can_publish_or_update: bool
    counters: dict[str, int]


class User(TypedDict):
    id: int
    first_name: str
    last_name: str
    middle_name: str | None
    email: str | None
    phone: str | None
    is_applicant: bool
    is_employer: bool
    is_admin: bool
    is_anonymous: bool
    is_application: bool
    counters: dict[str, int]


# --- Отклики -------------------------------------------------------------


class Message(TypedDict):
    id: str
    text: str
    author: dict[str, Any]
    created_at: str
    viewed_by_opponent: bool


class NegotiationState(TypedDict):
    id: NegotiationStateId
    name: str


class Negotiation(TypedDict):
    id: str
    state: NegotiationState
    created_at: str
    updated_at: str
    resume: ResumeShort
    viewed_by_opponent: bool
    has_updates: bool
    messages_url: str
    url: str
    counters: dict[str, int]
    chat_states: dict[str, dict[str, bool]]
    source: str
    chat_id: int
    messaging_status: str
    decline_allowed: bool
    read: bool
    has_new_messages: bool
    applicant_question_state: bool
    hidden: bool
    vacancy: NegotiationVacancy
    tags: list[Any]
