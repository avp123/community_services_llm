"""
Confound measures computed directly from response text (protocol.md section 6).
These are never asked of the judge model.
"""
import re

_DIRECTIVE_PATTERNS = [
    r"\bhe should\b", r"\bshe should\b", r"\bthey should\b",
    r"\byou should\b", r"\byou need to\b", r"\bhave him\b", r"\bhave her\b",
    r"\bhave them\b", r"\bmust\b", r"\bneeds to\b", r"\brequire[sd]?\b",
]

_OPTIONAL_PATTERNS = [
    r"\bone option\b", r"\banother option\b", r"\bhe might consider\b",
    r"\bshe might consider\b", r"\bthey might consider\b",
    r"\bwhat does he want\b", r"\bwhat does she want\b", r"\bwhat does they want\b",
    r"\bcould consider\b", r"\bmay want to\b", r"\bmight want to\b",
    r"\bit's up to\b", r"\bhis choice\b", r"\bher choice\b", r"\btheir choice\b",
]

_DIRECTIVE_RE = re.compile("|".join(_DIRECTIVE_PATTERNS), re.IGNORECASE)
_OPTIONAL_RE = re.compile("|".join(_OPTIONAL_PATTERNS), re.IGNORECASE)


def word_count(text: str) -> int:
    return len(text.split())


def directive_ratio(text: str):
    """
    Returns (directive_count, optional_count, ratio).
    ratio = directive_count / optional_count, or None if optional_count is 0
    (report the raw counts alongside the ratio — a None ratio is itself informative).
    """
    directive_count = len(_DIRECTIVE_RE.findall(text))
    optional_count = len(_OPTIONAL_RE.findall(text))
    ratio = (directive_count / optional_count) if optional_count else None
    return directive_count, optional_count, ratio


def compute_confounds(text: str) -> dict:
    d_count, o_count, ratio = directive_ratio(text)
    return {
        "word_count": word_count(text),
        "directive_count": d_count,
        "optional_count": o_count,
        "directive_ratio": ratio,
    }
