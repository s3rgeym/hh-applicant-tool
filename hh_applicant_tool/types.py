from __future__ import annotations

from typing import Any, Generic, List, Literal, Optional, TypedDict, TypeVar

T = TypeVar("T")

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


class Paginated(TypedDict, Generic[T]):
    items: list[T]
    found: int
    page: int
    pages: int
    per_page: int


class Vacancy(TypedDict):
    accept_incomplete_resumes: bool
    address: dict
    alternate_url: str
    apply_alternate_url: str
    area: dict
    contacts: Optional[ContactData]
    counters: dict
    department: dict
    employer: dict
    has_test: bool
    id: int
    insider_interview: dict
    name: str
    professional_roles: list
    published_at: str
    relations: list
    response_letter_required: bool
    response_url: str | None
    salary: dict
    schedule: dict
    snippet: dict
    sort_point_distance: float
    type: dict
    url: str
    experience: dict


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


class IdName(TypedDict):
    id: str
    name: str


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


class NegotiationEmployer(TypedDict):
    id: str
    name: str
    url: str
    alternate_url: str
    logo_urls: Optional[LogoUrls]
    vacancies_url: str
    accredited_it_employer: bool
    trusted: bool


class NegotiationVacancy(TypedDict):
    id: str
    premium: bool
    name: str
    department: Optional[dict]
    has_test: bool
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
    show_logo_in_search: Optional[bool]
    show_contacts: bool
    benefits: List[Any]
    insider_interview: Optional[dict]
    url: str
    alternate_url: str
    employer: NegotiationEmployer
    professional_roles: List[IdName]


class ResumeShort(TypedDict):
    id: str
    title: str
    url: str
    alternate_url: str


class Counters(TypedDict):
    messages: int
    unread_messages: int


class ChatStates(TypedDict):
    response_reminder_state: dict[str, bool]


class Negotiation(TypedDict):
    id: str
    state: IdName  # Здесь id: "discard", "interview" и т.д.
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
