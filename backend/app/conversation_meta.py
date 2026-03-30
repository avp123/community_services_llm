"""Derive short chat titles from scrubbed user text (PHI-safe for model input)."""

from __future__ import annotations

import re

from backend.app.utils import call_chatgpt_api

_TITLE_MAX_CHARS = 80
_FALLBACK_CHARS = 60


def _fallback_title(scrubbed: str) -> str:
    text = re.sub(r"\s+", " ", scrubbed.strip())
    if not text:
        return "Chat"
    if len(text) <= _FALLBACK_CHARS:
        return text
    cut = text[: _FALLBACK_CHARS]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


def derive_chat_title_from_scrubbed_text(scrubbed: str) -> str:
    """
    Produce a short list label from already-scrubbed first user message text.
    Uses a small model; falls back to truncated text on failure.
    """
    scrubbed = (scrubbed or "").strip()
    if not scrubbed:
        return "Chat"
    snippet = scrubbed[:2000]
    try:
        system = (
            "You write only a very short chat title for a sidebar list. "
            "Rules: maximum 8 words, no quotation marks, no colons, "
            "no trailing punctuation, describe the topic only. "
            "Output nothing but the title, one line."
        )
        out = call_chatgpt_api(system, snippet, stream=False)
        title = (out or "").strip().strip('"').strip("'")
        title = re.sub(r"^[\s\-–—]+|[\s\-–—]+$", "", title)
        title = re.sub(r"[\"':]+$", "", title)
        if not title:
            return _fallback_title(scrubbed)
        if len(title) > _TITLE_MAX_CHARS:
            title = title[: _TITLE_MAX_CHARS - 1] + "…"
        return title
    except Exception as e:
        print(f"[conversation_meta] title LLM failed: {e}")
        return _fallback_title(scrubbed)
