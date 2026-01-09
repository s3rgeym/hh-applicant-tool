from .base import BaseModel, mapped


# Из вакансии извлекается
class EmployerContactModel(BaseModel):
    id: int
    employer_id: int = mapped(src="employer.id")
    email: str = mapped(src="contacts.email")
    name: str = mapped(src="contacts.name", default=None)
    phone_numbers: str = mapped(
        src="contacts.phones",
        parse_src=lambda phones: ", ".join(
            p["formatted"] for p in phones if p.get("number")
        ),
        default=None,
    )
