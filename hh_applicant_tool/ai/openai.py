import logging

import requests

logger = logging.getLogger(__package__)


class OpenAIError(Exception):
    pass


class OpenAIChat:
    chat_endpoint: str = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        token: str,
        model: str,
        system_prompt: str,
        proxies: dict[str, str] = {}
    ):
        self.token = token
        self.model = model
        self.system_prompt = system_prompt
        self.proxies = proxies

    def default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def send_message(self, message: str) -> str:

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": self.system_prompt
                },
                {
                    "role": "user",
                    "content": message
                }
            ],
            "temperature": 0.7,
            "max_completion_tokens": 1000
        }

        try:
            response = requests.post(
                self.chat_endpoint,
                json=payload,
                headers=self.default_headers(),
                proxies=self.proxies,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            assistant_message = data["choices"][0]["message"]["content"]

            return assistant_message

        except requests.exceptions.RequestException as ex:
            raise OpenAIError(f"OpenAI API Error: {str(ex)}") from ex
