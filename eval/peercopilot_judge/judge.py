"""
LLM-as-judge implementation (protocol.md sections 4, 5, 7).

Pairwise comparison: the judge sees two responses to the same scenario/turn
and scores each on the four rubric dimensions, extracts named resources
(dimension 5 — extraction only, never scored), and states a preference.
"""
import json
import os
import re
import time
from typing import Dict, List, Optional

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

# Judge runs against the direct OpenAI API (not the Azure deployment used for
# the arms themselves), using OPENAI_API_KEY, so it can use gpt-5-mini —
# cheaper than the gpt-5-chat used for the three arms, while still GPT-5
# generation (the user ruled out gpt-4o-mini as not good enough).
_judge_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
JUDGE_MODEL = "gpt-5-mini"

RUBRIC_A = """RUBRIC A — Peer values (score dimensions 1-4 only; dimension 5 is extraction, not scoring).

1. Alignment to Peer Values — mutuality, self-determination, the person's own stated goals.
   1 = prescriptive/clinical, treats provider as case manager.
   2 = mostly directive with occasional deference.
   3 = mixed; options framed around clinical appropriateness rather than the person's wants.
   4 = largely grounded in the person's stated goals; occasional prescriptive slips.
   5 = consistently non-directive; defers to the person's own definition of success.

2. Deference — respects the boundaries of the peer role and the provider's judgment.
   1 = diagnoses or makes decisions belonging to the service user/clinician.
   2 = occasional clinical overreach without flagging it.
   3 = roughly in scope but doesn't signal uncertainty where it should.
   4 = stays in scope; flags what's outside peer support's remit.
   5 = clearly bounded; names what it can't know; suggests escalation/referral appropriately.

3. Contextually Grounded — engages the specifics of this person vs. generic content.
   1 = generic advice, ignores stated constraints.
   2 = nominal reference to the vignette; boilerplate substance.
   3 = uses some specifics but misses key constraints.
   4 = engages most stated constraints (geography, work status, family, preferences).
   5 = every suggestion visibly conditioned on this person's situation, including its tensions.

4. Follow-Ups — helps the provider know what to ask next.
   1 = no follow-up guidance.
   2 = generic "learn more about their situation."
   3 = some useful but mostly obvious questions.
   4 = specific, non-obvious questions tied to this person's situation.
   5 = identifies the actual information gaps that would change the plan, and why each matters.

5. Resource Relevance — EXTRACT, DO NOT SCORE. Do not assess whether resources are real,
   current, or correct — you cannot verify that. Extract them for human verification.
   For each named organization, program, benefit, or eligibility claim, output an object:
   {"name": "", "type": "organization|program|benefit|eligibility_claim|contact_info",
    "location_claimed": "", "specific_claim": "", "verbatim_context": ""}
"""

RUBRIC_B = """RUBRIC B — Generic helpfulness (the flip test). Same 1-5 scale, no peer framing.

1. Helpfulness — how useful is this response to someone trying to help this person?
2. Completeness — does it cover the relevant considerations thoroughly?
3. Actionability — are the next steps concrete and clear?
4. Clarity — is it well-organized and easy to follow?

Still extract named resources per dimension 5 above (extraction only, not scored).
"""

RUBRIC_A_KEYS = ("alignment", "deference", "grounded", "followups")
RUBRIC_B_KEYS = ("helpfulness", "completeness", "actionability", "clarity")

# Self-identifying strings to strip before judging, so the judge stays blind
# to which arm produced which response.
_SELF_ID_PATTERNS = [
    re.compile(r"\bpeercopilot\b", re.IGNORECASE),
    re.compile(r"\bcspnj\b", re.IGNORECASE),
]


def sanitize_for_judge(text: str) -> str:
    sanitized = text
    for pattern in _SELF_ID_PATTERNS:
        sanitized = pattern.sub("the assistant", sanitized)
    return sanitized


def _rubric_keys(rubric_name: str):
    return RUBRIC_A_KEYS if rubric_name == "A" else RUBRIC_B_KEYS


_LENGTH_BIAS_WARNING = """Do not favor a response merely because it is longer, more detailed, or
names more resources. Score length, thoroughness, and resource count as irrelevant unless the
rubric dimension explicitly calls for them (e.g. Completeness in Rubric B). A short, correct,
well-targeted response should outscore a long, padded, or generic one."""


def build_judge_prompt(rubric_name: str, scenario_text: str, response_1: str, response_2: str) -> str:
    rubric_text = RUBRIC_A if rubric_name == "A" else RUBRIC_B
    keys = _rubric_keys(rubric_name)
    score_fields = ", ".join(f'"{k}": N' for k in keys)
    return f"""You are evaluating two responses produced for a peer support provider in New Jersey.
A peer support provider is someone with lived experience of behavioral health
challenges who supports others in a non-clinical, mutual, non-directive capacity.

You will score each response on four dimensions (1-5 integers) and extract named resources.

{_LENGTH_BIAS_WARNING}

{rubric_text}

SCENARIO:
{scenario_text}

RESPONSE 1:
{response_1}

RESPONSE 2:
{response_2}

Output JSON only, with this exact shape:
{{
  "response_1": {{{score_fields}, "resources": [...], "reasoning": "..."}},
  "response_2": {{{score_fields}, "resources": [...], "reasoning": "..."}},
  "preference": "1 | 2 | tie",
  "preference_reasoning": "..."
}}
"""


_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)
_MAX_RETRIES = 6
_BASE_BACKOFF_SECONDS = 2.0


def call_judge(
    rubric_name: str,
    scenario_text: str,
    response_1: str,
    response_2: str,
    reasoning_effort: Optional[str] = None,
) -> Dict:
    """One judge call. Retries with exponential backoff on rate limits / transient
    errors, so pushing concurrency up degrades gracefully instead of failing outright.

    reasoning_effort: None uses the API default; pass "minimal"/"low"/"medium"/"high"
    to trade judgment depth for cost/latency (measured: "minimal" roughly halves both
    versus the default for gpt-5-mini)."""
    prompt = build_judge_prompt(
        rubric_name,
        scenario_text,
        sanitize_for_judge(response_1),
        sanitize_for_judge(response_2),
    )

    kwargs = dict(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            completion = _judge_client.chat.completions.create(**kwargs)
            raw = completion.choices[0].message.content or "{}"
            return json.loads(raw)
        except _RETRYABLE as exc:
            last_exc = exc
            sleep_for = _BASE_BACKOFF_SECONDS * (2 ** attempt)
            print(f"[judge] {type(exc).__name__}, retrying in {sleep_for:.0f}s (attempt {attempt + 1}/{_MAX_RETRIES})")
            time.sleep(sleep_for)
        except APIStatusError as exc:
            # 429s sometimes surface here depending on SDK version; treat like the above.
            if exc.status_code == 429:
                last_exc = exc
                sleep_for = _BASE_BACKOFF_SECONDS * (2 ** attempt)
                print(f"[judge] 429 rate limited, retrying in {sleep_for:.0f}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                time.sleep(sleep_for)
            else:
                raise

    raise last_exc
