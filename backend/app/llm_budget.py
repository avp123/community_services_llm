"""Monthly Azure OpenAI chat token budgets (UTC calendar month)."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any, Optional

# Roughly ~$100 at common blended chat rates; adjust manually as pricing changes.
AZURE_CHAT_MONTHLY_TOKEN_BUDGET = 10_000_000

# The external FoodTalk integration has its own ceiling so it cannot consume
# the budget intended for authenticated PeerCoPilot users. Override this with
# EXTERNAL_SNAP_MONTHLY_TOKEN_BUDGET in the deployment environment.
EXTERNAL_SNAP_MONTHLY_TOKEN_BUDGET = int(
    os.getenv("EXTERNAL_SNAP_MONTHLY_TOKEN_BUDGET", "1_000_000")
)


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
