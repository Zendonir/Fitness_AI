import json
from typing import Any

import openai

from app.ai.providers.base import ChatResult, Message, Provider, ProviderError, TextCallback, ToolCall, ToolSpec

_NO_TEMPERATURE = ("o1", "o3", "o4", "gpt-5")


class OpenAIProvider(Provider):
    name = "openai"
    uses_max_completion_tokens = True

    def _client(self) -> openai.AsyncOpenAI:
        if not self.api_key:
            raise ProviderError(f"Kein {self.name}-API-Key konfiguriert", retryable=False)
        return openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url or None, max_retries=2, timeout=120)

    def to_native(self, messages: list[Message]) -> list[dict[str, Any]]:
        out = []
        for m in messages:
            if m.images:
                parts: list[dict[str, Any]] = [{"type": "text", "text": m.content or "."}]
                parts += [{"type": "image_url", "image_url": {"url": f"data:{i['media_type']};base64,{i['data']}"}} for i in m.images]
                out.append({"role": m.role, "content": parts})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    async def complete(
        self, *, system: str, messages: list[dict[str, Any]], model: str, tools: list[ToolSpec] | None = None,
        temperature: float | None = None, max_tokens: int = 4096, on_text: TextCallback = None, json_mode: bool = False,
    ) -> ChatResult:
        client = self._client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        kwargs["max_completion_tokens" if self.uses_max_completion_tokens else "max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                                 "parameters": t.parameters}} for t in tools]
        if temperature is not None and not model.startswith(_NO_TEMPERATURE):
            kwargs["temperature"] = temperature
        if json_mode and not tools:
            kwargs["response_format"] = {"type": "json_object"}
        text, calls_acc, usage_in, usage_out, finish = "", {}, 0, 0, ""
        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.usage:
                    usage_in, usage_out = chunk.usage.prompt_tokens or 0, chunk.usage.completion_tokens or 0
                if not chunk.choices:
                    continue
                ch = chunk.choices[0]
                finish = ch.finish_reason or finish
                d = ch.delta
                if d and d.content:
                    text += d.content
                    if on_text:
                        await on_text(d.content)
                for tc in (d.tool_calls or []) if d else []:
                    acc = calls_acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    acc["id"] = tc.id or acc["id"]
                    if tc.function:
                        acc["name"] += tc.function.name or ""
                        acc["args"] += tc.function.arguments or ""
        except openai.RateLimitError as e:
            raise ProviderError(f"{self.name} Rate-Limit: {e}", retryable=True, status=429) from e
        except openai.AuthenticationError as e:
            raise ProviderError(f"{self.name}-API-Key ungültig", retryable=False, status=401) from e
        except openai.APIStatusError as e:
            raise ProviderError(f"{self.name}-Fehler {e.status_code}: {e.message}", retryable=e.status_code >= 500, status=e.status_code) from e
        except openai.APIConnectionError as e:
            raise ProviderError(f"{self.name} nicht erreichbar: {e}", retryable=True) from e
        finally:
            await client.close()

        calls = []
        for acc in calls_acc.values():
            try:
                args = json.loads(acc["args"] or "{}")
            except json.JSONDecodeError:
                continue
            calls.append(ToolCall(acc["id"] or f"call_{len(calls)}", acc["name"], args))
        if finish == "length":
            calls = []
        raw = {"role": "assistant", "content": text or None}
        if calls:
            raw["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                                 for c in calls]
        return ChatResult(text=text, tool_calls=calls, input_tokens=usage_in, output_tokens=usage_out, model=model,
                          provider=self.name, stop_reason=finish, raw=raw)

    def continuation(self, result: ChatResult, tool_results: list[tuple[ToolCall, str]]) -> list[dict[str, Any]]:
        return [result.raw, *({"role": "tool", "tool_call_id": c.id, "content": out} for c, out in tool_results)]

    async def list_models(self) -> list[str]:
        client = self._client()
        try:
            models = [m.id async for m in client.models.list()]
        except openai.APIError as e:
            raise ProviderError(f"Modelle konnten nicht geladen werden: {e}", retryable=False) from e
        finally:
            await client.close()
        if self.name == "openai":
            models = [m for m in models if m.startswith(("gpt-", "o1", "o3", "o4", "chatgpt"))
                      and not any(x in m for x in ("audio", "realtime", "transcribe", "tts", "image", "search"))]
        return sorted(models)


class OllamaProvider(OpenAIProvider):
    """Lokales Ollama über dessen OpenAI-kompatible API."""

    name = "ollama"
    uses_max_completion_tokens = False

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        url = (base_url or "").rstrip("/")
        if url and not url.endswith("/v1"):
            url += "/v1"
        super().__init__(api_key or "ollama", url)

    def _client(self) -> openai.AsyncOpenAI:
        if not self.base_url:
            raise ProviderError("Keine Ollama-URL konfiguriert", retryable=False)
        return openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=1, timeout=300)
