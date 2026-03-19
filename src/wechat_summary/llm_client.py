"""OpenAI-compatible LLM client wrapper with retry handling.

Supports both the Chat Completions API (messages) and the newer
Responses API (input).  Tries Chat Completions first; if the server
returns a 400 indicating it only speaks the Responses API, automatically
falls back.
"""

import json
import time
import urllib.request
import urllib.error
from typing import Iterable, cast

from openai import APIConnectionError, APITimeoutError, BadRequestError, OpenAI
from openai.types.chat import ChatCompletionMessageParam

from wechat_summary.exceptions import LLMConnectionError


class LLMClient:
    """Small wrapper around an OpenAI-compatible chat completion API."""

    def __init__(self, base_url: str, api_key: str, model: str):
        """Initialize the OpenAI-compatible client."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self._use_responses_api = False

    def chat(self, messages: list[dict[str, str]]) -> str:
        """Send a chat completion request and return the first text response.

        Automatically falls back to the Responses API if the server rejects
        the Chat Completions ``messages`` parameter.
        """
        if self._use_responses_api:
            return self._chat_responses_api(messages)

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=cast(Iterable[ChatCompletionMessageParam], messages),
                )
                return response.choices[0].message.content or ""
            except BadRequestError as exc:
                if "Responses API" in str(exc) or "'input'" in str(exc):
                    self._use_responses_api = True
                    return self._chat_responses_api(messages)
                raise LLMConnectionError(f"LLM request failed: {exc}") from exc
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

    def _chat_responses_api(self, messages: list[dict[str, str]]) -> str:
        """Call the Responses API (``/responses``) with ``input`` parameter."""
        # Convert chat messages to Responses API input format
        input_items = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                input_items.append(
                    {
                        "role": "developer",
                        "content": content,
                    }
                )
            else:
                input_items.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )

        # Build the base URL for responses endpoint
        # e.g., http://host/v1 → http://host/v1/responses
        url = f"{self.base_url}/responses"

        payload = json.dumps(
            {
                "model": self.model,
                "input": input_items,
            }
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = json.loads(resp.read().decode("utf-8"))

                # Extract text from Responses API output
                output = body.get("output", [])
                for item in output:
                    if item.get("type") == "message":
                        for content_block in item.get("content", []):
                            if content_block.get("type") == "output_text":
                                return content_block.get("text", "")
                # Fallback: try top-level output_text
                if body.get("output_text"):
                    return body["output_text"]
                return str(body.get("output", ""))
            except urllib.error.HTTPError as exc:
                raise LLMConnectionError(
                    f"Responses API error {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
                ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise LLMConnectionError(self._connection_error_message()) from exc
                time.sleep(2**attempt)

        raise LLMConnectionError(self._connection_error_message())

    def check_connection(self) -> bool:
        """Return True when the server responds to a minimal completion request."""
        try:
            self.chat([{"role": "user", "content": "ping"}])
        except LLMConnectionError:
            return False
        return True

    def _connection_error_message(self) -> str:
        """Build a consistent connection failure message."""
        api_type = "Responses API" if self._use_responses_api else "Chat Completions API"
        return f"Cannot connect to {self.base_url} ({api_type}). Is the LLM server running?"
