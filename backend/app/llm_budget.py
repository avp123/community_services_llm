"""Global monthly Azure OpenAI chat token budget (UTC calendar month).

Tune AZURE_CHAT_MONTHLY_TOKEN_BUDGET in code to match your target spend; Azure
rates vary by deployment and model.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

# Roughly ~$100 at common blended chat rates; adjust manually as pricing changes.
AZURE_CHAT_MONTHLY_TOKEN_BUDGET = 10_000_000


def utc_billing_month_first_day() -> date:
    """First calendar day of the current month in UTC (matches DB billing_month)."""
    now = datetime.now(timezone.utc).date()
    return date(now.year, now.month, 1)


def accumulate_usage(usage_accumulator: Optional[dict], response: Any) -> None:
    """Add response.usage.total_tokens into usage_accumulator['total'] if present."""
    if not usage_accumulator or response is None:
        return
    u = getattr(response, "usage", None)
    if u is None:
        return
    n = getattr(u, "total_tokens", None)
    if n is not None:
        usage_accumulator["total"] = int(usage_accumulator.get("total", 0)) + int(n)


def accumulate_usage_from_stream_event(usage_accumulator: Optional[dict], event: Any) -> None:
    """Accumulate usage from a streaming chunk (often only the final chunk has usage)."""
    if not usage_accumulator or event is None:
        return
    u = getattr(event, "usage", None)
    if u is None:
        return
    n = getattr(u, "total_tokens", None)
    if n is not None:
        usage_accumulator["total"] = int(usage_accumulator.get("total", 0)) + int(n)


def azure_chat_stream_options(stream: bool) -> dict:
    """Extra kwargs for chat.completions.create when stream=True (usage on last chunk)."""
    if stream:
        return {"stream": True, "stream_options": {"include_usage": True}}
    return {"stream": False}
