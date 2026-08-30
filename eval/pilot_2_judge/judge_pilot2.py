"""
LLM-as-judge pass over the pilot-2 conversations from 2026-08-28 (see data.py).

Simulates the participant post-condition questionnaire from the pilot instrument:
per-response Likert + qualitative items, then a single end-of-session A-vs-B
comparison (quantitative comparison scale + forced-choice preference + open
comparison questions), matching the reported BAAB tool order for this session.

Judge model: gpt-5-mini via the direct OpenAI API (OPENAI_API_KEY), not the
Azure deployment the app itself uses -- cheap-ish and keeps the judge decoupled
from the arms under test, same choice as eval/peercopilot_judge/judge.py.

Usage:
    python -m eval.pilot_2_judge.judge_pilot2
"""
import json
import os
import re
import sys
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from eval.pilot_2_judge.data import CONVERSATIONS

JUDGE_MODEL = "gpt-5-mini"
_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)
_MAX_RETRIES = 6
_BASE_BACKOFF = 2.0

# Self-identifying strings stripped before judging, so labels A/B stay blind
# to which arm actually produced which response (same rationale as peercopilot_judge).
_SELF_ID_PATTERNS = [
    re.compile(r"\bpeercopilot\b", re.IGNORECASE),
    re.compile(r"\bcspnj\b", re.IGNORECASE),
]


def _sanitize(text: str) -> str:
    out = text
    for pat in _SELF_ID_PATTERNS:
        out = pat.sub("the assistant", out)
    return out


def _call(prompt: str) -> dict:
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            completion = _client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            raw = completion.choices[0].message.content or "{}"
            return json.loads(raw)
        except _RETRYABLE as exc:
            last_exc = exc
        except APIStatusError as exc:
            if exc.status_code != 429:
                raise
            last_exc = exc
        sleep_for = _BASE_BACKOFF * (2 ** attempt)
        print(f"[judge] retrying in {sleep_for:.0f}s (attempt {attempt + 1}/{_MAX_RETRIES}): {last_exc}")
        time.sleep(sleep_for)
    raise last_exc


PER_RESPONSE_PERSONA = """You are role-playing a peer support provider in New Jersey who
just used an AI assistant while working through a scenario about someone they support. A
peer support provider is someone with lived experience of behavioral health challenges who
supports others in a non-clinical, mutual, non-determination-respecting capacity.

You have just read the scenario below and the single AI response given to you for it.
Immediately after this condition, rate the following statements on a 1-5 Likert scale
(1 = strongly disagree, 5 = strongly agree). Answer as this provider would, judging the
response strictly on its own merits for this scenario -- do not favor it for being longer,
more detailed, or naming more resources unless that length is actually what made it useful.

Likert items (score 1-5 each):
1. helped_think_through - "The AI helped me think through this situation."
2. useful_actionable - "The AI gave me useful information, ideas, or next steps that I could act on."
3. fits_my_approach - "The AI's assistance fits how I would approach this situation as a peer provider."
4. supported_autonomy - "The AI supported the service user's choices, priorities, and autonomy."
5. overall_useful - "Overall, the AI was useful for this task."
6. confident_after - "After using the AI, I feel confident about how I would approach this situation."
7. minimal_effort - "It took minimal effort to get useful assistance from the AI."

Qualitative items (1-3 sentences each, in the provider's voice):
- helpful_aspect: "What, if anything, was particularly helpful about the AI's assistance for this scenario?"
- wanted_different: "What, if anything, would you have wanted the AI to do differently?"

SCENARIO:
{scenario}

AI RESPONSE:
{response}

Output JSON only, with this exact shape:
{{
  "helped_think_through": N, "useful_actionable": N, "fits_my_approach": N,
  "supported_autonomy": N, "overall_useful": N, "confident_after": N, "minimal_effort": N,
  "helpful_aspect": "...", "wanted_different": "..."
}}
"""


COMPARISON_PERSONA = """You are role-playing the same peer support provider in New Jersey,
now at the end of a session in which you used two AI tools across four scenarios, in this
order: Tool B, Tool A, Tool A, Tool B. For each scenario below you already rated the single
response you got; now compare the tools overall based on everything you saw.

Do not favor either tool for being longer, more detailed, or naming more resources unless
that is genuinely what made it more useful. Treat "Tool A" and "Tool B" as arbitrary labels --
you are comparing the two response styles/behaviors shown, not any known product.

First, a forced choice:
- preference: "A" | "B" | "no_preference" -- "If you could use only Tool A or Tool B for your
  work, which would you prefer?"

Then, for each of the following, answer on a 1-5 scale where
1 = Strongly prefer A, 2 = Somewhat prefer A, 3 = No preference / about the same,
4 = Somewhat prefer B, 5 = Strongly prefer B:
- pref_think_through: "Helping me think through difficult situations"
- pref_actionable: "Providing concrete, actionable assistance"
- pref_resources: "Finding useful information or resources"
- pref_peer_values: "Fitting with peer-support values"
- pref_autonomy: "Supporting service-user autonomy"
- pref_easy: "Being easy to work with"
- pref_overall: "Overall usefulness"

Then, open qualitative comparison questions (1-4 sentences each, in the provider's voice):
- differences_noticed: "What differences, if any, did you notice between Tool A and Tool B?"
- unique_help: "Was there anything one tool helped you do that the other didn't?"
- used_differently: "Did you find yourself using the two tools differently? If so, how?"
- disagreed_or_changed: "Were there times you disagreed with, ignored, or wanted to change
  something either tool suggested?"
- depended_on_situation: "Did your preference between the tools depend on the type of
  situation you were working through?"
- what_to_change: "If you could change either tool to make it more useful in your actual
  work, what would you change?"
- thinking_vs_concrete: "Some AI assistance may be useful because it helps you think through
  a situation, while other assistance may give you something concrete that you could
  immediately say or do. Did you notice either of those forms of support in these tools, and
  was one more useful to you?"

SESSION TRANSCRIPT (in order: B, A, A, B):

{transcript}

Output JSON only, with this exact shape:
{{
  "preference": "A|B|no_preference",
  "pref_think_through": N, "pref_actionable": N, "pref_resources": N,
  "pref_peer_values": N, "pref_autonomy": N, "pref_easy": N, "pref_overall": N,
  "differences_noticed": "...", "unique_help": "...", "used_differently": "...",
  "disagreed_or_changed": "...", "depended_on_situation": "...", "what_to_change": "...",
  "thinking_vs_concrete": "..."
}}
"""


def build_per_response_prompt(convo: dict) -> str:
    return PER_RESPONSE_PERSONA.format(
        scenario=_sanitize(convo["scenario"]),
        response=_sanitize(convo["response"]),
    )


def build_comparison_prompt(conversations: list) -> str:
    blocks = []
    for c in conversations:
        blocks.append(
            f"--- Turn {c['order_index']} (Tool {c['tool']}) ---\n"
            f"Scenario: {_sanitize(c['scenario'])}\n"
            f"Response: {_sanitize(c['response'])}\n"
        )
    return COMPARISON_PERSONA.format(transcript="\n".join(blocks))


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set in environment.", file=sys.stderr)
        sys.exit(1)

    per_response_results = []
    for convo in CONVERSATIONS:
        print(f"[judge] scoring {convo['conversation_id']} (Tool {convo['tool']})...")
        prompt = build_per_response_prompt(convo)
        result = _call(prompt)
        result["conversation_id"] = convo["conversation_id"]
        result["tool"] = convo["tool"]
        result["order_index"] = convo["order_index"]
        per_response_results.append(result)

    print("[judge] running end-of-session A-vs-B comparison...")
    comparison_prompt = build_comparison_prompt(CONVERSATIONS)
    comparison_result = _call(comparison_prompt)

    output = {
        "per_response": per_response_results,
        "comparison": comparison_result,
    }

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pilot2_judge_results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[judge] wrote {out_path}")

    _write_csv(per_response_results, os.path.join(out_dir, "pilot2_per_response.csv"))


def _write_csv(rows: list, path: str):
    import csv

    fieldnames = [
        "conversation_id", "order_index", "tool",
        "helped_think_through", "useful_actionable", "fits_my_approach",
        "supported_autonomy", "overall_useful", "confident_after", "minimal_effort",
        "helpful_aspect", "wanted_different",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    print(f"[judge] wrote {path}")


if __name__ == "__main__":
    main()
