from __future__ import annotations

import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar

from rich.console import Console

console = Console()

T = TypeVar("T")

_RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "resource_exhausted",
    "too many requests",
    "overloaded",
)

_RETRY_DELAY_RE = re.compile(r"retry[_-]?delay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)", re.IGNORECASE)

_DAILY_QUOTA_MARKERS = (
    "perday",
    "per day",
    "requestsperday",
    "daily limit",
    "daily quota",
)


class ProviderError(RuntimeError):
    pass


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


def _is_daily_quota_error(exc: Exception) -> bool:
    text = str(exc).lower().replace("_", "").replace("-", "")
    return any(marker.replace(" ", "") in text for marker in _DAILY_QUOTA_MARKERS)


def _extract_retry_delay(exc: Exception) -> float | None:
    match = _RETRY_DELAY_RE.search(str(exc))
    return float(match.group(1)) if match else None


def call_with_rate_limit_retry(
    fn: Callable[[], T], max_retries: int = 5, base_delay: float = 2.0
) -> T:
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if _is_daily_quota_error(exc):
                raise ProviderError(
                    "Daily API quota exhausted for this provider/model. Retrying won't help "
                    "until the quota resets — switch providers/models (--provider/--model) or "
                    "upgrade your plan, then re-run 'seedloom run' (already-seeded tables are "
                    "skipped automatically)."
                ) from exc
            if not _is_rate_limit_error(exc) or attempt == max_retries:
                raise
            delay = _extract_retry_delay(exc) or (base_delay * (2**attempt))
            delay += random.uniform(0, 1)
            console.print(
                f"[yellow]Rate limited, retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{max_retries})...[/yellow]"
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


class Provider(ABC):
    @abstractmethod
    def generate(
        self,
        system: str,
        user_prompt: str,
        schema: dict[str, Any],
        tool_name: str = "generate_rows",
    ) -> list[dict[str, Any]]:
        raise NotImplementedError