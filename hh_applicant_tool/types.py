from __future__ import annotations

from typing import Any, Generic, List, Literal, Optional, TypedDict, TypeVar

NegotiationState = Literal[
    "discard",  # отказ
    "interview",  # собес
    "response",  # отклик
    "invitation",  # приглашение
    "hired",  # выход на работу
]


class AccessToken(TypedDict):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: Literal["bearer"]


Item = TypeVar("T")


class PaginatedItems(TypedDict, Generic[Item]):
    items: list[Item]
    found: int
    page: int
    pages: int
    per_page: int
    # Это не все поля
    clusters: Optional[Any]
    arguments: Optional[Any]
    fixes: Optional[Any]
    suggests: Optional[Any]
    alternate_url: str


class IdName(TypedDict):
    id: str
    name: str


class Snippet(TypedDict):
    requirement: Optional[str]
    responsibility: Optional[str]


class ManagerActivity(TypedDict):
    last_activity_at: str


Salary = TypedDict(
    "Salary",
    {
        "from": Optional[int],
        "to": Optional[int],
        "currency": str,
        "gross": bool,
    },
)

SalaryRange = TypedDict(
    "SalaryRange",
    {
        "from": Optional[int],
        "to": Optional[int],
        "currency": str,
        "gross": bool,
        "mode": IdName,
        "frequency": IdName,
    },
)


LogoUrls = TypedDict(
    "LogoUrls",
    {
        "original": str,
        "90": str,
        "240": str,
    },
)


class EmployerShort(TypedDict):
    id: str
    name: str
    url: str
    alternate_url: str
    logo_urls: Optional[LogoUrls]
    vacancies_url: str
    accredited_it_employer: bool
    trusted: bool


class SearchEmployer(EmployerShort):
    country_id: Optional[int]


class NegotiationEmployer(EmployerShort):
    pass


class VacancyShort(TypedDict):
    id: str
    premium: bool
    name: str
    department: Optional[dict]
    has_test: bool
    # HH API fields
    response_letter_required: bool
    area: IdName
    salary: Optional[Salary]
    salary_range: Optional[SalaryRange]
    type: IdName
    address: Optional[dict]
    response_url: Optional[str]
    sort_point_distance: Optional[float]
    published_at: str
    created_at: str
    archived: bool
    apply_alternate_url: str
    show_contacts: bool
    benefits: List[Any]
    insider_interview: Optional[dict]
    url: str
    alternate_url: str
    professional_roles: List[IdName]


class NegotiationVacancy(VacancyShort):
    employer: NegotiationEmployer
    show_logo_in_search: Optional[bool]


class SearchVacancy(VacancyShort):
    employer: SearchEmployer
    relations: List[Any]
    experimental_modes: List[str]
    manager_activity: Optional[ManagerActivity]
    snippet: Snippet
    contacts: Optional[dict]
    schedule: IdName
    working_days: List[Any]
    working_time_intervals: List[Any]
    working_time_modes: List[Any]
    accept_temporary: bool
    fly_in_fly_out_duration: List[Any]
    work_format: List[IdName]
    working_hours: List[IdName]
    work_schedule_by_days: List[IdName]
    accept_labor_contract: bool
    civil_law_contracts: List[Any]
    night_shifts: bool
    accept_incomplete_resumes: bool
    experience: IdName
    employment: IdName
    employment_form: IdName
    internship: bool
    adv_response_url: Optional[str]
    is_adv_vacancy: bool
    adv_context: Optional[dict]
    allow_chat_with_manager: bool


class Phone(TypedDict):
    country: str
    city: str
    number: str
    formatted: str
    comment: Optional[str]


class ContactData(TypedDict):
    name: Optional[str]
    email: Optional[str]
    phones: List[Phone]
    call_tracking_enabled: bool


class ResumeShort(TypedDict):
    id: str
    title: str
    url: str
    alternate_url: str


class Counters(TypedDict):
    messages: int
    unread_messages: int


class ChatStates(TypedDict):
    # response_reminder_state: {"allowed": bool}
    response_reminder_state: dict[str, bool]


class Negotiation(TypedDict):
    id: str
    state: IdName
    created_at: str
    updated_at: str
    resume: ResumeShort
    viewed_by_opponent: bool
    has_updates: bool
    messages_url: str
    url: str
    counters: Counters
    chat_states: ChatStates
    source: str
    chat_id: int
    messaging_status: str
    decline_allowed: bool
    read: bool
    has_new_messages: bool
    applicant_question_state: bool
    hidden: bool
    vacancy: NegotiationVacancy
    tags: List[Any]


class EmployerApplicantServices(TypedDict):
    target_employer: dict[str, int]


class Employer(EmployerShort):
    has_divisions: bool
    type: str
    description: Optional[str]
    site_url: str
    relations: List[Any]
    area: IdName
    country_code: str
    industries: List[Any]
    is_identified_by_esia: bool
    badges: List[Any]
    branded_description: Optional[str]
    branding: Optional[dict]
    insider_interviews: List[Any]
    open_vacancies: int
    applicant_services: EmployerApplicantServices
