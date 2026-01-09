from .base import BaseModel, mapped


# Из вакансии извлекается
class EmployerContactModel(BaseModel):
    id: int
    employer_id: int = mapped(path="employer.id")
    email: str = mapped(path="contacts.email")
    name: str = mapped(path="contacts.name", default=None)
    phone_numbers: str = mapped(
        path="contacts.phones",
        transform=lambda phones: ", ".join(
            p["formatted"] for p in phones if p.get("number")
        ),
        default=None,
    )
