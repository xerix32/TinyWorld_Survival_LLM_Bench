"""OpenAI-compatible chat-completions wrapper (used for Vercel AI Gateway)."""

from __future__ import annotations

import json
import threading
import time
from time import perf_counter
from typing import Any, Mapping
import urllib.error
import urllib.request

from models.base import BaseModelWrapper, ModelResponse, RenderedPrompts


class _ProviderLimiter:
    def __init__(self, requests_per_minute: int, max_concurrent_requests: int) -> None:
        self._min_interval_seconds = 0.0
        if requests_per_minute > 0:
            self._min_interval_seconds = 60.0 / float(requests_per_minute)
        self._next_allowed_ts = 0.0
        self._rate_lock = threading.Lock()
        self._concurrency = threading.Semaphore(max(1, int(max_concurrent_requests)))

    def acquire(self) -> float:
        self._concurrency.acquire()
        wait_seconds = 0.0

        if self._min_interval_seconds > 0:
            with self._rate_lock:
                now = time.monotonic()
                wait_seconds = max(0.0, self._next_allowed_ts - now)
                self._next_allowed_ts = max(self._next_allowed_ts, now) + self._min_interval_seconds

        if wait_seconds > 0:
            time.sleep(wait_seconds)
        return wait_seconds

    def release(self) -> None:
        self._concurrency.release()


class OpenAIWrapper(BaseModelWrapper):
    _LIMITERS_BY_PROVIDER: dict[str, _ProviderLimiter] = {}
    _LIMITERS_LOCK = threading.Lock()

    def __init__(
        self,
        *,
        model_name: str,
        api_base: str,
        api_key: str,
        temperature: float,
        max_tokens: int,
        requests_per_minute: int,
        max_retries: int,
        retry_base_seconds: float,
        retry_max_seconds: float,
        request_timeout_seconds: float,
        max_concurrent_requests: int,
        provider_id: str,
        profile_name: str,
    ) -> None:
        super().__init__(model_name=model_name)
        self._api_base = api_base
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens

        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._request_timeout_seconds = request_timeout_seconds

        self._provider_id = provider_id
        self._profile_name = profile_name

        self._provider_limiter = self._get_provider_limiter(
            provider_id=provider_id,
            requests_per_minute=requests_per_minute,
            max_concurrent_requests=max_concurrent_requests,
        )

    @classmethod
    def _get_provider_limiter(
        cls,
        *,
        provider_id: str,
        requests_per_minute: int,
        max_concurrent_requests: int,
    ) -> _ProviderLimiter:
        with cls._LIMITERS_LOCK:
            limiter = cls._LIMITERS_BY_PROVIDER.get(provider_id)
            if limiter is None:
                limiter = _ProviderLimiter(
                    requests_per_minute=requests_per_minute,
                    max_concurrent_requests=max_concurrent_requests,
                )
                cls._LIMITERS_BY_PROVIDER[provider_id] = limiter
            return limiter

    @staticmethod
    def _extract_message_text(content: Any) -> str:
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "\n".join(chunks)

        return ""

    @staticmethod
    def _is_retriable_http_code(status_code: int) -> bool:
        if status_code in {408, 409, 425, 429}:
            return True
        return 500 <= status_code <= 599

    def _build_request_payload(self, prompts: RenderedPrompts) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": prompts.system_prompt},
                {"role": "user", "content": prompts.user_prompt},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }

    def generate(self, prompts: RenderedPrompts, metadata: Mapping[str, Any]) -> ModelResponse:
        del metadata

        payload = self._build_request_payload(prompts)
        body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            self._api_base,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )

        last_error_message = "unknown_error"

        for attempt in range(self._max_retries + 1):
            limiter_acquired = False
            try:
                self._provider_limiter.acquire()
                limiter_acquired = True
                started_at = perf_counter()
                with urllib.request.urlopen(request, timeout=self._request_timeout_seconds) as response:
                    raw_response = response.read().decode("utf-8")
                latency_ms = (perf_counter() - started_at) * 1000.0

                data = json.loads(raw_response)
                choices = data.get("choices") or []
                if not choices:
                    raise RuntimeError("provider response missing choices")

                message = choices[0].get("message") or {}
                raw_text = self._extract_message_text(message.get("content", "")).strip()

                usage = data.get("usage") or {}
                total_tokens = usage.get("total_tokens")
                if total_tokens is not None:
                    total_tokens = int(total_tokens)

                prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
                if prompt_tokens is not None:
                    prompt_tokens = int(prompt_tokens)

                completion_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
                if completion_tokens is not None:
                    completion_tokens = int(completion_tokens)

                if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
                    total_tokens = prompt_tokens + completion_tokens

                cache_read_tokens = usage.get("cache_read_input_tokens")
                if cache_read_tokens is None:
                    cache_read_tokens = usage.get("prompt_cache_hit_tokens")
                if cache_read_tokens is not None:
                    cache_read_tokens = int(cache_read_tokens)

                cache_write_tokens = usage.get("cache_creation_input_tokens")
                if cache_write_tokens is None:
                    cache_write_tokens = usage.get("prompt_cache_miss_tokens")
                if cache_write_tokens is not None:
                    cache_write_tokens = int(cache_write_tokens)

                estimated_cost = usage.get("estimated_cost", data.get("estimated_cost"))
                if estimated_cost is not None:
                    estimated_cost = float(estimated_cost)

                return ModelResponse(
                    raw_text=raw_text,
                    tokens_used=total_tokens,
                    estimated_cost=estimated_cost,
                    latency_ms=latency_ms,
                    metadata={
                        "provider_id": self._provider_id,
                        "profile_name": self._profile_name,
                        "response_id": data.get("id"),
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "cache_read_tokens": cache_read_tokens,
                        "cache_write_tokens": cache_write_tokens,
                    },
                )

            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                last_error_message = f"http_{exc.code}: {error_body[:400]}"
                if not self._is_retriable_http_code(exc.code) or attempt >= self._max_retries:
                    raise RuntimeError(
                        f"openai-compatible request failed ({self._provider_id}/{self._profile_name}): {last_error_message}"
                    ) from exc

            except urllib.error.URLError as exc:
                last_error_message = f"url_error: {exc.reason}"
                if attempt >= self._max_retries:
                    raise RuntimeError(
                        f"openai-compatible request failed ({self._provider_id}/{self._profile_name}): {last_error_message}"
                    ) from exc

            except TimeoutError as exc:
                last_error_message = "timeout"
                if attempt >= self._max_retries:
                    raise RuntimeError(
                        f"openai-compatible request timeout ({self._provider_id}/{self._profile_name})"
                    ) from exc
            finally:
                if limiter_acquired:
                    self._provider_limiter.release()

            delay = min(self._retry_max_seconds, self._retry_base_seconds * (2 ** attempt))
            if delay > 0:
                time.sleep(delay)

        raise RuntimeError(
            f"openai-compatible request failed after retries ({self._provider_id}/{self._profile_name}): {last_error_message}"
        )
