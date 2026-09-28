import json
import re
from typing import Any

import anthropic

from app.ai.providers.base import ChatResult, Message, Provider, ProviderError, TextCallback, ToolCall, ToolSpec

# Ältere Modelle akzeptieren noch temperature; neuere (Claude 4.7+ / 5) lehnen es ab.
_TEMPERATURE_MODELS = re.compile(r"claude-(3|haiku-4-5|sonnet-4-5|sonnet-4-6|opus-4-5|opus-4-6|opus-4-1|opus-4-0|sonnet-4-0)")


class AnthropicProvider(Provider):
    name = "anthropic"

    def _client(self) -> anthropic.AsyncAnthropic:
        if not self.api_key:
            raise ProviderError("Kein Anthropic-API-Key konfiguriert", retryable=False)
        return anthropic.AsyncAnthropic(api_key=self.api_key, max_retries=2, timeout=120)

    def to_native(self, messages: list[Message]) -> list[dict[str, Any]]:
        out = []
        for m in messages:
            if m.images:
                blocks: list[dict[str, Any]] = [
                    {"type": "image", "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]}}
                    for img in m.images
                ]
                blocks.append({"type": "text", "text": m.content or "."})
                out.append({"role": m.role, "content": blocks})
            else:
                out.append({"role": m.role, "content": m.content or "."})
        return out

    async def complete(
        self, *, system: str, messages: list[dict[str, Any]], model: str, tools: list[ToolSpec] | None = None,
        temperature: float | None = None, max_tokens: int = 4096, on_text: TextCallback = None, json_mode: bool = False,
    ) -> ChatResult:
        client = self._client()
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        if temperature is not None and _TEMPERATURE_MODELS.match(model):
            kwargs["extra_body"] = {"temperature": temperature}
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "text" and on_text:
                        await on_text(event.text)
                final = await stream.get_final_message()
        except anthropic.RateLimitError as e:
            raise ProviderError(f"Anthropic Rate-Limit: {e}", retryable=True, status=429) from e
        except anthropic.AuthenticationError as e:
            raise ProviderError("Anthropic-API-Key ungültig", retryable=False, status=401) from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic-Fehler {e.status_code}: {e.message}", retryable=e.status_code >= 500, status=e.status_code) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"Anthropic nicht erreichbar: {e}", retryable=True) from e
        finally:
            await client.close()

        if final.stop_reason == "refusal":
            raise ProviderError("Anfrage vom Modell abgelehnt", retryable=True)
        text = "".join(b.text for b in final.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, b.input if isinstance(b.input, dict) else json.loads(b.input or "{}"))
                 for b in final.content if b.type == "tool_use"]
        if final.stop_reason == "max_tokens" and calls:
            calls = []  # abgeschnittene Tool-Eingaben niemals ausführen
        return ChatResult(
            text=text, tool_calls=calls, input_tokens=final.usage.input_tokens or 0,
            output_tokens=final.usage.output_tokens or 0, model=final.model or model, provider=self.name,
            stop_reason=final.stop_reason or "", raw=[b.model_dump(exclude_none=True) for b in final.content],
        )

    def continuation(self, result: ChatResult, tool_results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]:
        return [
            {"role": "assistant", "content": result.raw},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": c.id, "content": out} for c, out in tool_results]},
        ]

    async def list_models(self) -> list[str]:
        client = self._client()
        try:
            return [m.id async for m in client.models.list()]
        except anthropic.APIError as e:
            raise ProviderError(f"Modelle konnten nicht geladen werden: {e}", retryable=False) from e
        finally:
            await client.close()
