from .api import ApiError
from .types import ApiListResponse


class GetResumeIdMixin:
    def _get_resume_id(self) -> str:
        try:
            resumes: ApiListResponse = self.api_client.get("/resumes/mine")
            return resumes["items"][0]["id"]
        except (ApiError, KeyError, IndexError) as ex:
            raise Exception("Не могу получить идентификатор резюме") from ex


