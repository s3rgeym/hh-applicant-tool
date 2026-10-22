from abc import ABC, abstractmethod


class AIError(Exception):
    pass


class AIClient(ABC):
    @abstractmethod
    def create_chat(
        self,
        system_prompt: str,
        *,
        history: list[dict] | None = None,
        **kwargs,
    ) -> "AIChat":
        """Создаёт чат с фиксированным system_prompt, историей
        и параметрами генерации."""

    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        message: str,
        *,
        history: list[dict] | None = None,
        **kwargs,
    ) -> str:
        """Генерация текста."""

    @abstractmethod
    def recognize_text(
        self,
        system_prompt: str,
        data: bytes,
        *,
        mime_type: str = "image/png",
        history: list[dict] | None = None,
        **kwargs,
    ) -> str:
        """Распознавание текста на изображении."""


class AIChat(ABC):
    @abstractmethod
    def complete(self, message: str) -> str:
        """Генерация текста с параметрами чата."""

    @abstractmethod
    def recognize_text(
        self,
        data: bytes,
        *,
        mime_type: str = "image/png",
    ) -> str:
        """Распознавание текста на изображении с параметрами чата."""
