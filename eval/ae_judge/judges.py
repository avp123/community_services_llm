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
  binary    pairwise, pick one, both orderings x n samples
  pointwise each response scored 1-5 alone
  graded    pairwise on a 1-5 preference scale, mirroring pilot_2's human instrument
            ("1 = strongly prefer A ... 5 = strongly prefer B"), both orderings

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

from openai import AzureOpenAI

MODEL = "gpt-5-chat"
_client = None


def _get_client():
    """Lazy so the module imports without credentials (build_prompt is testable)."""
    global _client
    if _client is None:
        _client = AzureOpenAI(api_key=os.environ["OPENAI_API_KEY_AZURE"],
                              azure_endpoint=os.environ["OPENAI_AZURE_ENDPOINT"],
                              api_version="2024-12-01-preview")
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

_ASK = {
    "J1_naive": "Which response is more helpful to a peer support specialist?",
    "J2_samhsa_ips": "Which response better equips the peer specialist to work consistently "
                     "with those competencies and principles?",
    "J3_pilot": "Which response is more useful to you, right now?",
}
_ASK_POINT = {
    "J1_naive": "How helpful is this response to a peer support specialist?",
    "J2_samhsa_ips": "How well does this response equip the peer specialist to work "
                     "consistently with those competencies and principles?",
    "J3_pilot": "How useful is this response to you, right now?",
}


def build_prompt(judge, mode, scenario, a, b=None):
    """a/b are response texts; b is None for pointwise."""
    f = FRAMINGS[judge]
    if mode == "pointwise":
        return (f"{f}\n\nSCENARIO:\n{scenario}\n\nRESPONSE:\n{a}\n\n{_ASK_POINT[judge]}\n\n"
                "Rate this response on a 1-5 scale (1 = poor, 5 = excellent). Use the full "
                'range.\nReply with JSON only: {"score": <1-5>, "reason": "<one sentence>"}')
    head = (f"{f}\n\nSCENARIO:\n{scenario}\n\nRESPONSE A:\n{a}\n\nRESPONSE B:\n{b}\n\n"
            f"{_ASK[judge]}")
    if mode == "binary":
        return (head + "\n\nReply with JSON only: "
                '{"winner": "response_a" | "response_b" | "tie", "reason": "<2-3 sentences>"}')
    if mode == "graded":
        return (head + "\n\nAnswer on this 1-5 scale:\n  1 = strongly prefer Response A\n"
                "  2 = somewhat prefer Response A\n  3 = no preference\n"
                "  4 = somewhat prefer Response B\n  5 = strongly prefer Response B\n"
                "Use the full range. Reply with JSON only: "
                '{"score": <1-5>, "reason": "<one sentence>"}')
    raise ValueError(mode)


def call(prompt):
    r = _get_client().chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"})
    return json.loads(r.choices[0].message.content or "{}")
