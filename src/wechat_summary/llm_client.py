"""OpenAI-compatible LLM client wrapper with retry handling."""

import time
from typing import Iterable, cast

from openai import APIConnectionError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessageParam

from wechat_summary.exceptions import LLMConnectionError

class LLMClient:
    """Small wrapper around an OpenAI-compatible chat completion API."""

    def __init__(self, base_url: str, api_key: str, model: str):
        """Initialize the OpenAI-compatible client."""
        self.base_url = base_url
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def chat(self, messages: list[dict[str, str]]) -> str:
        """Send a chat completion request and return the first text response."""
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=cast(Iterable[ChatCompletionMessageParam], messages),
                )
                return response.choices[0].message.content or ""
            except APITimeoutError as exc:
                if attempt == 2:
                    raise LLMConnectionError(self._connection_error_message()) from exc
                time.sleep(2**attempt)
            except TimeoutError as exc:
                if attempt == 2:
                    raise LLMConnectionError(self._connection_error_message()) from exc
                time.sleep(2**attempt)
            except APIConnectionError as exc:
                raise LLMConnectionError(self._connection_error_message()) from exc

        raise LLMConnectionError(self._connection_error_message())

    def check_connection(self) -> bool:
        """Return True when the server responds to a minimal completion request."""
        try:
            ping_message = [
                {"role": "user", "content": "ping"},
            ]
            self.chat(ping_message)
        except LLMConnectionError:
            return False
        return True

    def _connection_error_message(self) -> str:
        """Build a consistent connection failure message."""
        return f"Cannot connect to {self.base_url}. Is Ollama running?"
