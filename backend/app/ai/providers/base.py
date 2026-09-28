"""Einheitliches Provider-Interface.

Ablauf einer Anfrage:
    native = provider.to_native(messages)              # neutrale -> providerspezifische Nachrichten
    result = await provider.complete(system, native, tools, …)
    native += provider.continuation(result, tool_results)   # für die nächste Tool-Runde
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

TextCallback = Callable[[str], Awaitable[None]] | None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResult:
    text: str
    tool_calls: list[ToolCall]
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
    stop_reason: str = ""
    raw: Any = None  # providerspezifische Assistant-Nachricht


@dataclass
class Message:
    """Neutrale Nachricht. images: [{"media_type": "image/jpeg", "data": "<base64>"}]"""

    role: str  # user|assistant
    content: str
    images: list[dict[str, str]] = field(default_factory=list)


class ProviderError(Exception):
    def __init__(self, message: str, retryable: bool = True, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class Provider(ABC):
    name: str = "base"
    supports_vision: bool = True

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key
        self.base_url = base_url

    @abstractmethod
    def to_native(self, messages: list[Message]) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        on_text: TextCallback = None,
        json_mode: bool = False,
    ) -> ChatResult: ...

    @abstractmethod
    def continuation(self, result: ChatResult, tool_results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def list_models(self) -> list[str]: ...
