"""
The three judges, in the three elicitation modes. Self-contained: all judge text
lives here, nothing imported from a rubric module.

JUDGES
  J1 naive        No rubric. "Which is more helpful to a peer support specialist?"
                  The default eval most papers use. Included as a foil.
  J2 samhsa_ips   Primed with SAMHSA peer-worker core competencies + Intentional
                  Peer Support principles. The principled, citable choice.
  J3 pilot        Mined from the CSPNJ pilot transcripts (pilot_1/2/3.txt +
                  annotation_packet.md). What these providers actually said they want.

MODES
  binary    pairwise, pick one per dimension, both orderings x n samples
  pointwise Likert: each response rated 1-5 (strongly disagree .. strongly agree)
            against each dimension statement, alone
  graded    pairwise on a 1-5 preference scale per dimension, mirroring pilot_2's human
            instrument ("1 = strongly prefer A ... 5 = strongly prefer B"), both orderings

DIMENSIONS
  All three modes now score the same five dimensions (DIMENSIONS below) rather than a
  single overall judgment. Four of them are deliberately the four contrast axes in
  prompts/, so an axis pair can be read against the dimension it manipulates; the fifth
  is overall usefulness. Wording is the provider-facing instrument, so it is phrased in
  the first person ("The AI ...") regardless of which framing is running.

Known judge properties, measured (see FINDINGS.md):
  * none of them ever returns "tie" -- 810/810 forced choices, including on pairs
    drawn from the same prompt. Per-pair verdicts are near-meaningless; only the
    pattern across pairs is interpretable.
  * first-position bias in the null test: J1 64%, J2 47%, J3 64%. Always run both
    orderings; a single-ordering result is off by ~14 points for J1 and J3.
  * J1 and J2 reverse sign between binary and graded modes on the same responses.
"""
import json
import os
import time

from openai import (APIConnectionError, APIStatusError, APITimeoutError, AzureOpenAI,
                    RateLimitError)

# Azure DEPLOYMENT names, not model names -- the deployment called "gpt-5-chat" on this
# resource actually serves gpt-5.2-2025-12-11 (verified 2026-09-09 via response.model).
# Check with: response.model, or `az cognitiveservices account deployment list`.
MODEL = "gpt-5-chat"
DEPLOYMENTS = {"gpt5": "gpt-5-chat", "4omini": "gpt-4o-mini"}
_client = None


def _get_client():
    """Lazy so the module imports without credentials (build_prompt is testable)."""
    global _client
    if _client is None:
        # Explicit timeout: the SDK default is 600s, so a dropped connection parks a
        # worker for ten minutes with no error. 90s + the retry below means a transient
        # network failure self-heals instead of stalling the whole sweep.
        _client = AzureOpenAI(api_key=os.environ["OPENAI_API_KEY_AZURE"],
                              azure_endpoint=os.environ["OPENAI_AZURE_ENDPOINT"],
                              api_version="2024-12-01-preview",
                              timeout=90.0, max_retries=0)
    return _client

# --------------------------------------------------------------------- framings
J1_FRAMING = "You are evaluating AI responses written for a peer support specialist."

J2_FRAMING = """You are evaluating AI responses written for a peer support specialist, \
against the recognised standards of the peer support field.

SAMHSA core competencies for peer workers: engages peers in collaborative and caring \
relationships; provides support; shares lived experience of recovery; personalizes peer \
support; supports recovery planning; links to resources, services and supports; provides \
information about skills related to health, wellness and recovery; helps peers manage \
crises; values communication; supports collaboration and teamwork; promotes leadership \
and advocacy; promotes growth and development.

Intentional Peer Support (IPS) principles: the relationship is mutual, not \
helper-to-helped; move from "what's wrong with you" to "what happened to you"; the four \
tasks are connection, worldview, mutuality, and moving towards rather than away from \
fear; peer support is not a clinical service -- it does not diagnose, assess or \
case-manage, and self-determination is central."""

J3_FRAMING = """You are a working peer support provider at CSPNJ. You are a trained peer \
specialist with your own lived experience, and you already know how to build rapport, \
listen, validate and respect autonomy -- that is your craft, not something an AI needs to \
teach you. You are often reading this with a service user sitting in front of you and you \
judge by that harder case.

What your colleagues said actually matters:
- Take-away density: how much of this can you lift and use in the next five minutes -- a
  number to call, a question you could ask out loud verbatim, a sentence the person could
  say to a prescriber or family member, a step with the specifics attached?
- Named, relevant, checkable resources: real agencies with contact details that fit THIS
  person. You verify every referral before passing it on, so a referral that doesn't apply
  costs you a call and is worse than none.
- Register: not labelled techniques aimed at you ("Validate + reflect"), not academic
  taxonomies, not flattery. Concrete words someone could actually say are wanted; generic
  template lines under a technique heading are not.
- Shape: a short orienting frame, then linked concrete moves, readable at a glance.
- Padding, not length: does every section earn its place?
- Does it tell you something you didn't already know?"""

FRAMINGS = {"J1_naive": J1_FRAMING, "J2_samhsa_ips": J2_FRAMING, "J3_pilot": J3_FRAMING}

# The shared instrument. key -> (Likert statement, pairwise label).
# The first four are the four contrast axes in prompts/; the fifth is overall.
DIMENSIONS = {
    "information_value": (
        "The AI added useful information, resources, or perspectives I might not "
        "otherwise have had.",
        "Adding useful information, resources, or perspectives I might not otherwise have"),
    "practical_usability": (
        "The AI gave me guidance that I could readily use.",
        "Providing useful and readily usable guidance"),
    "role_complementarity": (
        "The AI complemented my role as a peer provider rather than trying to do the "
        "peer-support work for me.",
        "Complementing my role as a peer provider"),
    "autonomy": (
        "The AI supported the service user's choices, priorities, and autonomy.",
        "Supporting service-user autonomy"),
    "overall": (
        "Overall, the AI was useful for this task.",
        "Overall usefulness"),
}
DIMS = list(DIMENSIONS)

# Judge-specific lead-in. The dimensions themselves are identical across judges -- the
# framing above is what differs, so the same instrument is read through three lenses.
_LEAD = {
    "J1_naive": "Judge the response(s) as they would serve a peer support specialist.",
    "J2_samhsa_ips": "Judge the response(s) by how well they equip the peer specialist to "
                     "work consistently with those competencies and principles.",
    "J3_pilot": "Judge the response(s) as the provider who has to use this, right now.",
}

_ANTI_CEILING = (
    "Use the full range and differentiate between the dimensions. Do not give the same "
    "value to every dimension unless they genuinely are the same; a response is usually "
    "stronger on some of these than others."
)


def _block(mode):
    """The dimension list, worded for the mode."""
    idx = 0 if mode == "pointwise" else 1
    return "\n".join(f"  {k}: {DIMENSIONS[k][idx]}" for k in DIMS)


def _schema(mode):
    inner = ('{"score": <1-5>, "reason": "<one sentence>"}' if mode != "binary" else
             '{"winner": "response_a" | "response_b" | "tie", "reason": "<one sentence>"}')
    body = ",\n".join(f'  "{k}": {inner}' for k in DIMS)
    return "Reply with JSON only, one entry per dimension:\n{\n" + body + "\n}"


def build_prompt(judge, mode, scenario, a, b=None):
    """a/b are response texts; b is None for pointwise. Scores all five DIMENSIONS."""
    f = FRAMINGS[judge]
    if mode == "pointwise":
        return (f"{f}\n\nSCENARIO:\n{scenario}\n\nRESPONSE:\n{a}\n\n{_LEAD[judge]}\n\n"
                "Rate your agreement with each of these statements about the response, on "
                "a 1-5 scale:\n  1 = strongly disagree\n  2 = disagree\n  3 = neither agree "
                "nor disagree\n  4 = agree\n  5 = strongly agree\n\n"
                f"{_block(mode)}\n\n{_ANTI_CEILING}\n\n{_schema(mode)}")
    head = (f"{f}\n\nSCENARIO:\n{scenario}\n\nRESPONSE A:\n{a}\n\nRESPONSE B:\n{b}\n\n"
            f"{_LEAD[judge]}\n\nCompare the two responses on each of these dimensions:\n\n"
            f"{_block(mode)}")
    if mode == "binary":
        return (head + "\n\nFor each dimension, say which response is better. Choose 'tie' "
                "only if they are genuinely indistinguishable on that dimension.\n\n"
                f"{_schema(mode)}")
    if mode == "graded":
        return (head + "\n\nFor each dimension, answer on this 1-5 scale:\n"
                "  1 = strongly prefer Response A\n  2 = somewhat prefer Response A\n"
                "  3 = no preference\n  4 = somewhat prefer Response B\n"
                "  5 = strongly prefer Response B\n\n"
                f"{_ANTI_CEILING}\n\n{_schema(mode)}")
    raise ValueError(mode)


_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)
_MAX_RETRIES = 5
_BASE_BACKOFF = 4.0


def call(prompt, model=None):
    """One judge call. Retries on 429/transient errors -- a full sweep is ~700 calls
    and a dropped cell is invisible in the aggregate, so failing loudly is worse than
    waiting. Returns {} if the reply is not parseable JSON."""
    last = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = _get_client().chat.completions.create(
                model=model or MODEL, messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"})
            try:
                return json.loads(r.choices[0].message.content or "{}")
            except json.JSONDecodeError:
                return {}
        except _RETRYABLE as e:
            last = e
        except APIStatusError as e:
            if e.status_code != 429:
                raise
            last = e
        time.sleep(_BASE_BACKOFF * (2 ** attempt))
    raise last
