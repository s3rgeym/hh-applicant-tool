from typing import TypedDict, Literal


class AccessToken(TypedDict):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: Literal["bearer"]


class ApiListResponse(TypedDict):
    ...
    items: list
    found: int
    page: int
    pages: int
    per_page: int


class VacancyItem(TypedDict):
    accept_incomplete_resumes: bool
    address: dict
    alternate_url: str
    apply_alternate_url: str
    area: dict
    contacts: dict
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
