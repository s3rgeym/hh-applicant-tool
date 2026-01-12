from .base import BaseModel, mapped


# Из вакансии извлекается
class VacancyContactsModel(BaseModel):
    id: int
    vacancy_id: int = mapped(path="id")

    vacancy_name: str = mapped(path="name")
    vacancy_alternate_url: str = mapped(path="alternate_url", default=None)
    vacancy_area_id: int = mapped(path="area.id", default=None)
    vacancy_area_name: str = mapped(path="area.name", default=None)
    vacancy_salary_from: int = mapped(path="salary.from", default=0)
    vacancy_salary_to: int = mapped(path="salary.to", default=0)
    vacancy_currency: str = mapped(path="salary.currency", default="RUR")
    vacancy_gross: bool = mapped(path="salary.gross", default=False)

    employer_id: int = mapped(path="employer.id", default=None)
    employer_name: str = mapped(path="employer.name", default=None)
    email: str = mapped(path="contacts.email")
    name: str = mapped(path="contacts.name", default=None)
    phone_numbers: str = mapped(
        path="contacts.phones",
        transform=lambda phones: ", ".join(
            p["formatted"] for p in phones if p.get("number")
        ),
        default=None,
    )
