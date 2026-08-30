"""
Direct-assessment LLM-as-judge pass over the pilot-2 conversations from
2026-08-28 (see data.py) -- v3 "peer-informed" rubric.

Same 7 scored dimensions and anti-ceiling scoring discipline as v2, but the
rubric now front-loads an explicit peer-support-practice framework (start from
the person's own goals, support self-determination vs. directing, work
collaboratively rather than taking over, respect person-defined recovery,
combine practical help with respect for choice, handle resource/eligibility
uncertainty appropriately, and avoid mistaking warmth/affirmation for
substance) that the judge is told to apply when scoring peer_support_alignment
and choice_priorities_autonomy in particular.

These are single-turn conversations (the provider's first message IS the
scenario paste), so CONVERSATION CONTEXT is empty and PROVIDER PROMPT equals
the scenario text.

Usage:
    python -m eval.pilot_2_judge.judge_pilot2_rubric_v3
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


JUDGE_PROMPT = """You are evaluating an AI response designed to assist a peer-support provider working in a peer-support setting.

You will be given:

1. **SCENARIO:** The initial scenario describing a service user.
2. **CONVERSATION CONTEXT:** Any additional information learned about the service user before this AI response.
3. **PROVIDER PROMPT:** What the peer-support provider actually asked the AI.
4. **AI RESPONSE:** The AI's response to evaluate.

Your task is to evaluate the quality of the AI response given the provider's actual request and all information available at that point.

Do NOT pretend that you are the peer provider.
Do NOT predict how much a particular provider would personally like the response.
Do NOT assume information about the service user that has not been provided.
Do NOT reward a response simply because it sounds empathetic, polished, supportive, or professional.
Evaluate the response itself.

## PEER-SUPPORT CONTEXT

For this evaluation, assess the response using the following principles of peer-support practice.

### 1. Start with the person's own goals and perspective

Good peer support begins by understanding what the service user wants, what matters to them, and how they understand their own situation.

The AI should not prematurely decide what the person's problem is, what recovery should look like, or what outcome they should pursue.

When important goals or preferences are unclear and would materially affect the assistance, helping the provider identify useful questions to explore can be more appropriate than immediately prescribing a plan.

However, do NOT mechanically reward clarifying questions. If the person's goals are already sufficiently clear, or the provider asks a direct factual question, the AI should respond directly.

### 2. Support self-determination rather than directing

Peer support should preserve the service user's ability to define their own priorities and make their own choices.

The AI can provide concrete information, resources, options, suggestions, or examples without being prescriptive.

Providing structure is not inherently directive. The important distinction is whether the assistance helps the provider and service user make their own decisions or instead assumes what they should do.

### 3. Work collaboratively rather than taking over

The AI should function as a resource for the peer provider, not as the decision-maker or replacement for the provider's relationship with the service user.

Good assistance can help the provider:

* notice considerations;
* explore the person's perspective;
* identify questions;
* understand options;
* locate resources;
* think through tradeoffs;
* translate the person's goals into possible next steps.

It should leave appropriate room for the provider's judgment and for continued conversation with the service user.

### 4. Respect person-defined recovery and progress

Do not assume conventional outcomes such as employment, independence, treatment participation, greater social activity, or family reconciliation are necessarily the correct goals.

The relevant question is whether those outcomes fit what the service user values and wants.

When other people or institutions define success differently from the service user, good peer-support assistance should recognize that distinction.

### 5. Provide practical assistance without losing the person's perspective

Peer-aligned assistance does not need to be vague.

Concrete resources, concise options, next steps, questions, or example language can be highly valuable.

The strongest responses combine practical usefulness with attention to the person's own goals and choices.

### 6. Treat resource information appropriately

When recommending external programs, benefits, organizations, eligibility rules, contact information, or other potentially changing information, the response should appropriately acknowledge uncertainty and the possible need to verify current information.

Do not require excessive disclaimers.

The relevant question is whether the provider could responsibly use the information without being given unwarranted confidence that potentially changing details are definitely correct.

### 7. Avoid superficial affirmation

Warmth and validation can be appropriate, but generic praise or excessive affirmation does not itself constitute peer support.

Statements such as praising the provider's question or repeatedly affirming that their approach is excellent should not increase the peer-support score unless they serve a substantive purpose.

Peer alignment should be judged primarily from what the response enables the provider and service user to do.

## GENERAL SCORING INSTRUCTIONS

Rate each dimension independently from 1 to 5.

Use the full scale.

A response that is competent and generally useful should typically receive a **3 or 4**, not automatically a 5.

A **5 should be reserved for responses that are exceptionally strong on that dimension and have no important readily identifiable shortcomings given the request and available context.**

If you can identify a meaningful improvement that would materially improve the response on a dimension, it should generally not receive a 5 on that dimension.

Do not lower a score merely because additional information could always have been provided. Only consider omissions that are relevant to the provider's actual request and situation.

Evaluate each dimension separately. A response can, for example, be highly actionable while poorly supporting autonomy, or highly peer-aligned while difficult to use.

### 1. THINKING AND REASONING SUPPORT

How well does the AI response help the provider think through the situation?

Consider whether it:

* identifies important considerations;
* helps distinguish the service user's priorities from assumptions made by the provider, family, institutions, or AI;
* helps understand the person's perspective;
* surfaces relevant alternatives or tradeoffs;
* identifies useful questions when important information is missing;
* supports the provider's own reasoning rather than simply producing a plan.

Do NOT reward a response merely for providing a long list of considerations.

Do NOT penalize a response for failing to ask questions when sufficient information is already available or when the provider requested a direct factual answer.

**1:** Provides essentially no useful reasoning support or seriously misframes the situation.

**2:** Provides limited reasoning support and misses major considerations.

**3:** Provides useful reasoning support, but misses important considerations or does relatively little beyond the obvious.

**4:** Provides strong, context-sensitive reasoning support with only minor limitations.

**5:** Exceptionally strong reasoning support that helps the provider understand the person's perspective, priorities, relevant uncertainties, and/or tradeoffs with no important readily identifiable weakness.

### 2. USEFUL AND ACTIONABLE ASSISTANCE

How well does the response provide useful information, ideas, or next steps that the provider could actually use?

This can include:

* concrete options;
* relevant resources;
* questions to explore with the service user;
* practical next steps;
* brief adaptable examples of language;
* ways to translate the person's goals into action.

Actionability does NOT require directing the service user.

Do not penalize concrete assistance merely because it is structured or specific. Concrete assistance is compatible with peer support when it preserves meaningful choice.

**1:** Little or no practically useful assistance.

**2:** Some potentially useful content, but largely vague, generic, or difficult to act upon.

**3:** Useful ideas or guidance, but important details or concrete next steps are missing.

**4:** Clear, concrete, and practically useful assistance with only minor limitations.

**5:** Exceptionally useful and readily actionable assistance that is well tailored to the person's goals and the provider's request.

### 3. PEER-SUPPORT ALIGNMENT

How well does the response embody the peer-support principles described above?

In particular, consider whether it:

* begins from or appropriately seeks the service user's own goals and perspective;
* supports collaboration rather than expert-led direction;
* respects lived experience and person-defined recovery;
* avoids unnecessary clinical, paternalistic, or prescriptive framing;
* supports the provider without replacing their judgment or relationship;
* combines practical help with respect for self-determination;
* avoids mistaking generic warmth or affirmation for substantive peer support.

Evaluate the substance of the response, not merely its tone.

**1:** Strongly inconsistent with peer-support practice.

**2:** Contains substantial tensions with peer-support principles.

**3:** Generally compatible with peer support but contains meaningful limitations, assumptions, or unnecessarily directive elements.

**4:** Strongly embodies the peer-support principles above with only minor limitations.

**5:** Exceptionally well aligned throughout: its substantive approach consistently supports collaborative, person-defined, autonomy-preserving peer support with no important readily identifiable weakness.

### 4. SERVICE-USER CHOICE, PRIORITIES, AND AUTONOMY

How well does the response support the service user's own choices, priorities, and autonomy?

Consider whether it:

* centers what the service user actually wants;
* distinguishes their goals from goals assumed by family members, providers, institutions, or the AI;
* preserves meaningful options;
* avoids assuming what progress or recovery should look like;
* supports informed decision-making without unnecessarily steering toward one option.

Do not automatically reward a response for saying "it's your choice." Evaluate whether its substantive recommendations actually preserve meaningful choice.

**1:** Substantially undermines or disregards the person's choices or priorities.

**2:** Frequently assumes or directs what the person should want or do.

**3:** Generally autonomy-supportive but makes meaningful assumptions or insufficiently centers the person's priorities.

**4:** Strongly supports the person's choices, priorities, and self-determination with only minor limitations.

**5:** Exceptionally careful and substantive in centering the person's own goals and preserving meaningful self-determination throughout the response.

### 5. OVERALL USEFULNESS

Overall, how useful is this AI response as assistance to a peer-support provider for this particular request and situation?

Consider both practical usefulness and whether the assistance supports rather than interferes with good peer-support practice.

Do NOT calculate this score by averaging the other dimensions.

**1:** Not useful or potentially counterproductive.

**2:** Limited usefulness with substantial weaknesses.

**3:** Clearly useful, but with meaningful limitations.

**4:** Very useful and well suited to the request and peer-support context, with only minor limitations.

**5:** Exceptionally useful for this particular provider request and peer-support context, with no important readily identifiable limitation.

### 6. RESPONSIVENESS AND CONTEXTUAL FIT

How well does the AI respond to what the provider actually asked, given the scenario and conversation so far?

Consider whether it:

* answers the provider's actual question;
* incorporates relevant information already learned;
* appropriately prioritizes information;
* avoids irrelevant tangents;
* recognizes important missing information when necessary.

Do NOT judge the response against an ideal answer to the original scenario if the provider asked a narrower question.

The relevant target is the **provider's actual prompt in the context of the conversation**.

**1:** Substantially misunderstands or ignores the request/context.

**2:** Only partially responsive or misses major contextual information.

**3:** Generally responsive but misses or underuses meaningful context.

**4:** Highly responsive and appropriately tailored, with only minor limitations.

**5:** Exceptionally precise and context-sensitive, making excellent use of the information available and the provider's actual request.

### 7. EASE OF EXTRACTING USEFUL ASSISTANCE

How easy is it for a peer-support provider to quickly identify and use the important information in the response?

Consider that the provider may consult the AI **while also remaining engaged in a conversation with a service user**.

Consider:

* prioritization;
* organization;
* concision;
* readability;
* headings, bullets, or emphasis when useful;
* unnecessary repetition;
* whether the most important information is immediately visible.

Do NOT reward brevity by itself.
Do NOT automatically reward bullet points.
Do NOT penalize structured or concise assistance on the assumption that peer support should be conversational.

Evaluate whether the presentation helps the provider use the AI as a resource while remaining present with the service user.

**1:** Very difficult to quickly understand or extract useful information from.

**2:** Requires substantial effort to locate or interpret the useful content.

**3:** Reasonably usable, but important content requires some effort to extract.

**4:** Easy to scan, understand, and use with only minor presentational limitations.

**5:** Exceptionally well prioritized and structured for rapid use; the provider could identify the important assistance with very little effort while remaining engaged with the service user.

## FINAL CHECK BEFORE SCORING

Before returning your ratings:

1. Identify the provider's actual request.
2. Identify what is known about the service user's own goals and priorities.
3. Identify any important goals or assumptions that remain unclear.
4. Ask whether the response appropriately responds directly or whether further information gathering would materially improve the assistance.
5. Identify at least one substantive strength and one substantive weakness of the response.
6. Score each dimension independently.
7. Only assign a 5 if the identified weakness does not meaningfully affect that dimension.

## OUTPUT FORMAT

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

    out_path = os.path.join(out_dir, "pilot2_rubric_v3_judge_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[judge] wrote {out_path}")

    _write_csv(results, os.path.join(out_dir, "pilot2_rubric_v3_scores.csv"))
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

    print("\n=== Tool averages (rubric v3 judge, n=2 responses per tool) ===")
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
