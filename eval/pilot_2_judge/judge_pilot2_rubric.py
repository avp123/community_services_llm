"""
Direct-assessment LLM-as-judge pass over the pilot-2 conversations from
2026-08-28 (see data.py), using the 7-dimension rubric (thinking/reasoning
support, actionability, peer-support alignment, autonomy, overall usefulness,
responsiveness, ease of extraction) supplied by the user in place of the
participant-persona judge in judge_pilot2.py.

Unlike judge_pilot2.py, this judge does NOT role-play a provider rating their
own subjective experience -- it evaluates the response on its merits given the
scenario/context/prompt, independent of any simulated participant.

These are single-turn conversations (the provider's first message IS the
scenario paste), so CONVERSATION CONTEXT is empty and PROVIDER PROMPT equals
the scenario text.

Usage:
    python -m eval.pilot_2_judge.judge_pilot2_rubric
"""
import json
import os
import re
import sys
import time
from collections import defaultdict

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from eval.pilot_2_judge.data import CONVERSATIONS

JUDGE_MODEL = "gpt-5-mini"
_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)
_MAX_RETRIES = 6
_BASE_BACKOFF = 2.0

_SELF_ID_PATTERNS = [
    re.compile(r"\bpeercopilot\b", re.IGNORECASE),
    re.compile(r"\bcspnj\b", re.IGNORECASE),
]

DIMENSIONS = [
    "thinking_reasoning_support",
    "useful_actionable_assistance",
    "peer_support_alignment",
    "choice_priorities_autonomy",
    "overall_usefulness",
    "responsiveness_contextual_fit",
    "ease_of_extracting_assistance",
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


JUDGE_PROMPT = """You are evaluating an AI response designed to assist a peer-support provider.

You will be given:

1. **SCENARIO:** The initial scenario describing a service user.
2. **CONVERSATION CONTEXT:** Any additional information learned about the service user before this AI response.
3. **PROVIDER PROMPT:** What the peer-support provider actually asked the AI.
4. **AI RESPONSE:** The AI's response to evaluate.

Your task is to evaluate the quality of the AI response given the provider's actual request and all information available at that point.

Do NOT pretend that you are the peer provider.
Do NOT predict how much a particular provider would personally like the response.
Do NOT assume information about the service user that has not been provided.
Evaluate the response itself.

Rate each dimension independently from 1 to 5.

### 1. THINKING AND REASONING SUPPORT

How well does the AI response help the provider think through the situation?

Consider whether it helps identify important considerations, understand the person's situation and priorities, reason through alternatives or tradeoffs, or identify useful questions when additional information is needed.

1 = Provides little or no useful support for thinking through the situation.
2 = Provides limited reasoning support and misses important considerations.
3 = Provides some useful support but has meaningful gaps.
4 = Provides strong support for thinking through the situation.
5 = Provides exceptionally useful, nuanced, and context-sensitive reasoning support.

### 2. USEFUL AND ACTIONABLE ASSISTANCE

How well does the AI provide useful information, ideas, or next steps that the provider could act on?

Actionable assistance can include concrete options, resources, questions to ask, considerations to explore, brief examples of language, or practical next steps.

Actionability does NOT require telling the service user what to do.

1 = Little useful or actionable assistance.
2 = Some potentially useful content, but largely vague or difficult to use.
3 = Useful assistance with meaningful limitations.
4 = Clear and practically useful assistance.
5 = Highly useful, specific, and readily actionable assistance.

### 3. PEER-SUPPORT ALIGNMENT

How well does the AI response reflect a peer-support approach?

Consider whether the response is collaborative and person-centered; respects the service user's lived experience; avoids unnecessarily clinical, paternalistic, or prescriptive framing; helps the provider work with rather than direct the service user; and leaves appropriate room for the provider's own judgment and relationship with the service user.

Do not equate peer support with simply being warm or empathetic.

1 = Strongly inconsistent with a peer-support approach.
2 = Contains substantial tensions with a peer-support approach.
3 = Generally compatible with peer support but with meaningful limitations.
4 = Strongly reflects a peer-support approach.
5 = Exceptionally well aligned with peer-support principles.

### 4. SERVICE-USER CHOICE, PRIORITIES, AND AUTONOMY

How well does the AI response support the service user's own choices, priorities, and autonomy?

Consider whether it centers what the service user wants, preserves meaningful options, avoids assuming what their goals should be, and supports them in defining progress or making decisions for themselves.

1 = Undermines or disregards the person's autonomy or priorities.
2 = Frequently assumes or directs what the person should do.
3 = Generally autonomy-supportive but makes some assumptions or gives insufficient attention to the person's priorities.
4 = Strongly supports the person's choices and priorities.
5 = Exceptionally careful about centering the person's own goals, choices, and self-determination.

### 5. OVERALL USEFULNESS

Overall, how useful is this AI response as assistance to a peer-support provider for this particular request and situation?

Consider all relevant aspects of the response rather than simply averaging your previous ratings.

1 = Not useful or potentially counterproductive.
2 = Limited usefulness.
3 = Moderately useful.
4 = Very useful.
5 = Exceptionally useful.

### 6. RESPONSIVENESS AND CONTEXTUAL FIT

How well does the AI respond to what the provider actually asked, given the scenario and conversation so far?

Consider whether it incorporates relevant information already learned, addresses the provider's actual request, avoids irrelevant tangents, and appropriately recognizes when important information is still missing.

Do NOT penalize the response for failing to ask clarifying questions when enough information is already available or when the provider explicitly requested a direct factual answer.

1 = Substantially misunderstands or ignores the request or context.
2 = Partially responsive but misses important aspects.
3 = Generally responsive with meaningful gaps.
4 = Highly responsive and well tailored to the context.
5 = Exceptionally responsive, precise, and context-sensitive.

### 7. EASE OF EXTRACTING USEFUL ASSISTANCE

How easy is it for a peer-support provider to quickly identify and use the important information in the AI response?

Consider organization, prioritization, concision, readability, use of headings/bullets/emphasis where appropriate, unnecessary repetition, and whether the most useful information is easy to find.

Imagine that the provider may need to consult the response while also remaining engaged in a conversation with a service user.

Do NOT reward brevity by itself. A response should contain enough information to be useful.

1 = Very difficult to quickly understand or extract useful information from.
2 = Requires substantial effort to identify the useful content.
3 = Reasonably usable but could be considerably easier to scan or understand.
4 = Easy to understand and extract useful information from.
5 = Exceptionally clear, well-prioritized, and easy to use at a glance.

### OUTPUT FORMAT

Return only valid JSON in the following format:

{{
"thinking_reasoning_support": {{
"score": 1,
"reason": "Brief explanation"
}},
"useful_actionable_assistance": {{
"score": 1,
"reason": "Brief explanation"
}},
"peer_support_alignment": {{
"score": 1,
"reason": "Brief explanation"
}},
"choice_priorities_autonomy": {{
"score": 1,
"reason": "Brief explanation"
}},
"overall_usefulness": {{
"score": 1,
"reason": "Brief explanation"
}},
"responsiveness_contextual_fit": {{
"score": 1,
"reason": "Brief explanation"
}},
"ease_of_extracting_assistance": {{
"score": 1,
"reason": "Brief explanation"
}},
"primary_strength": "One sentence identifying the response's greatest strength.",
"primary_weakness": "One sentence identifying the response's greatest weakness."
}}

SCENARIO:
{scenario}

CONVERSATION CONTEXT:
{context}

PROVIDER PROMPT:
{prompt}

AI RESPONSE:
{response}
"""


def build_prompt(convo: dict) -> str:
    return JUDGE_PROMPT.format(
        scenario=_sanitize(convo["scenario"]),
        context="None (single-turn conversation; this is the first message).",
        prompt=_sanitize(convo["scenario"]),
        response=_sanitize(convo["response"]),
    )


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set in environment.", file=sys.stderr)
        sys.exit(1)

    results = []
    for convo in CONVERSATIONS:
        print(f"[judge] scoring {convo['conversation_id']} (Tool {convo['tool']})...")
        result = _call(build_prompt(convo))
        result["conversation_id"] = convo["conversation_id"]
        result["tool"] = convo["tool"]
        result["order_index"] = convo["order_index"]
        results.append(result)

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)

    out_path = os.path.join(out_dir, "pilot2_rubric_judge_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[judge] wrote {out_path}")

    _write_csv(results, os.path.join(out_dir, "pilot2_rubric_scores.csv"))
    _print_tool_averages(results)


def _write_csv(rows: list, path: str):
    import csv

    fieldnames = ["conversation_id", "order_index", "tool"] + DIMENSIONS + [
        "primary_strength", "primary_weakness",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            row = {"conversation_id": r["conversation_id"], "order_index": r["order_index"], "tool": r["tool"]}
            for dim in DIMENSIONS:
                row[dim] = r[dim]["score"]
            row["primary_strength"] = r["primary_strength"]
            row["primary_weakness"] = r["primary_weakness"]
            w.writerow(row)
    print(f"[judge] wrote {path}")


def _print_tool_averages(rows: list):
    by_tool = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for dim in DIMENSIONS:
            by_tool[r["tool"]][dim].append(r[dim]["score"])

    print("\n=== Tool averages (rubric judge, n=2 responses per tool) ===")
    header = "dimension".ljust(32) + "Tool A".rjust(10) + "Tool B".rjust(10)
    print(header)
    for dim in DIMENSIONS:
        a_vals = by_tool.get("A", {}).get(dim, [])
        b_vals = by_tool.get("B", {}).get(dim, [])
        a_avg = sum(a_vals) / len(a_vals) if a_vals else float("nan")
        b_avg = sum(b_vals) / len(b_vals) if b_vals else float("nan")
        print(dim.ljust(32) + f"{a_avg:10.2f}" + f"{b_avg:10.2f}")


if __name__ == "__main__":
    main()
