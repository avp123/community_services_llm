"""
Direct-assessment LLM-as-judge pass over the pilot-2 conversations from
2026-08-28 (see data.py) -- v2 rubric.

Same 7 dimensions as judge_pilot2_rubric.py, but with a stricter/more explicit
version of the rubric (use-the-full-scale instructions, "identify a weakness
before scoring a 5" discipline, explicit non-rewards for empathy/bullets/brevity
alone) supplied by the user to reduce the ceiling effect seen in the first
rubric pass (most scores landed at 4-5).

These are single-turn conversations (the provider's first message IS the
scenario paste), so CONVERSATION CONTEXT is empty and PROVIDER PROMPT equals
the scenario text.

Usage:
    python -m eval.pilot_2_judge.judge_pilot2_rubric_v2
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
    "complementary_value",
    "important_things_to_notice",
    "responsiveness_relevance",
    "peer_role_alignment",
    "service_user_goals_autonomy",
    "reliability_verifiability",
    "ease_of_extracting_assistance",
    "overall_usefulness",
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
Do NOT reward a response simply because it sounds empathetic, polished, professional, or comprehensive.
Evaluate the substantive value of the response for a peer-support provider.

A peer-support provider already brings lived experience, peer-support skills, judgment, knowledge of the person, and the relationship with the service user. The AI should generally complement those strengths rather than unnecessarily taking over the provider's peer-support role.

## GENERAL SCORING INSTRUCTIONS

Rate each dimension independently from 1 to 5.

Use the full scale.

A response that is competent and generally useful should typically receive a **3 or 4**, not automatically a 5.

A **5 should be reserved for responses that are exceptionally strong on that dimension and have no important readily identifiable shortcomings given the provider's request and available context.**

If you can identify a meaningful improvement that would materially improve the response on a dimension, it should generally not receive a 5 on that dimension.

Do not lower a score merely because additional information could always have been provided. Only consider omissions that are relevant to the provider's actual request and situation.

Do not reward comprehensiveness for its own sake. Additional information can make a response worse when it distracts from what is most relevant.

Evaluate each dimension separately. A response can, for example, provide excellent complementary information while poorly respecting service-user autonomy, or be highly peer-aligned while containing unreliable factual claims.

Score substantive differences rather than minor differences in wording, style, length, or organization. Responses that provide substantively equivalent assistance should generally receive similar scores on the relevant dimensions.

### 1. COMPLEMENTARY VALUE

How well does the AI add useful value beyond what the provider already supplied or would ordinarily be expected to bring through their peer-support role?

Consider whether it contributes:

* relevant information or facts;
* specific resources, programs, services, contacts, or practical details;
* useful options or alternatives;
* connections between pieces of information;
* specialized or difficult-to-recall knowledge;
* information that materially expands what the provider has to work with.

The AI does not need to provide resources when resources are not relevant to the request. Complementary value can also come from a useful fact, distinction, connection, or option.

Do NOT reward:

* merely restating or summarizing the scenario;
* generic peer-support advice the provider would reasonably already know;
* unnecessary scripts or conversation coaching;
* long lists of possibilities that add little practical value;
* praise or validation that does not add substantive assistance.

If the provider explicitly asks what to say, how to approach a conversation, or how to perform some aspect of peer support, interpersonal guidance or example language may provide meaningful complementary value.

**1:** Adds essentially no useful information or value beyond the provider's input, or mainly restates the situation.

**2:** Adds limited useful value; much of the response is generic, obvious, repetitive, or outside the provider's actual need.

**3:** Adds some genuinely useful information, resources, options, or connections, but the contribution is limited or mixed with substantial generic material.

**4:** Adds strong, relevant complementary value that meaningfully expands what the provider has to work with, with only minor limitations.

**5:** Adds exceptionally high-value information, resources, options, or connections that are tightly relevant to the request and substantially improve what the provider has available, with no important readily identifiable weakness.

### 2. IMPORTANT THINGS TO NOTICE


How well does the response help the provider notice the few considerations, uncertainties, distinctions, tradeoffs, or missing facts that are especially important in this particular situation?

Evaluate the quality and selectivity of the considerations the response actually surfaces, not how many considerations from an ideal or comprehensive answer it covers. Do not lower this score merely because you can identify additional relevant considerations. An omission should lower this score only when the omitted consideration is so consequential that missing it materially limits the provider's understanding of the specific situation. A response that identifies a few especially important considerations can score 4 or 5 without covering every relevant issue.

Consider whether it:

* identifies consequential considerations the provider may not readily notice;
* distinguishes issues that could otherwise be conflated;
* surfaces important uncertainty;
* identifies assumptions that matter;
* recognizes missing information that could materially change what would be useful;
* points out relevant alternatives or tradeoffs.

Do NOT reward a response merely for generating many considerations.

Do NOT assume that every plausible concern associated with a diagnosis, demographic, or situation deserves attention.

Penalize responses that introduce speculative problems, risks, or concerns merely because they are commonly associated with the topic rather than because something in the available context makes them important.

Do NOT penalize a response for failing to ask questions when the provider supplied sufficient information or explicitly asked for a direct factual answer.

**1:** Provides essentially no useful thinking support or seriously misidentifies what matters.

**2:** Notices a few potentially relevant issues but misses major considerations or focuses substantially on low-value or speculative concerns.

**3:** Surfaces some useful considerations or uncertainties, but misses an important issue, includes unnecessary material, or does relatively little beyond the obvious.

**4:** Identifies the most important considerations, distinctions, or uncertainties for this particular situation with only minor limitations.

**5:** Exceptionally selective and insightful: surfaces the few considerations, uncertainties, or connections that most materially improve the provider's understanding of this particular situation, without distracting speculation or unnecessary breadth.

### 3. RESPONSIVENESS AND RELEVANCE

How well does the AI respond to what the provider actually asked, given the scenario and conversation so far?

This dimension is about **focus and fit to the request, not completeness or amount of assistance**. Evaluate whether the content the AI provides is directed toward the provider's actual question and appropriately prioritizes what matters for that question.

A response can be highly responsive even if it is brief, incomplete, or could have provided additional useful information. **Do not lower this score merely because the response could have included more details, resources, eligibility information, next steps, follow-up questions, or other useful assistance.** Those limitations may affect other dimensions, but they affect Responsiveness and Relevance only when the omission means that an important part of what the provider actually asked was not addressed.

Consider whether the response:

* directly addresses the provider's actual question or task;
* uses relevant information from the scenario and conversation when it matters to the request;
* prioritizes its content according to what the provider actually asked;
* avoids irrelevant or weakly related tangents;
* avoids introducing unrelated problems, goals, risks, services, or considerations merely because they are commonly associated with the situation;
* asks for additional information only when it is genuinely needed to respond usefully;
* does not unnecessarily redirect or broaden the provider's request.

Do NOT judge the response against an ideal or comprehensive answer to the scenario. Judge it against **the provider's actual request**.

Do NOT lower this score because useful information is absent unless that omission leaves the provider's actual question or an important part of it unanswered.

Do NOT treat a response as less responsive merely because another response would be more informative, actionable, detailed, or comprehensive.

**1:** Substantially misunderstands, ignores, redirects, or fails to address the provider's actual request.

**2:** Addresses only part of the request or devotes substantial attention to irrelevant, weakly related, or unjustifiably broadened material.

**3:** Generally addresses the request, but contains meaningful tangents, misprioritizes information, overlooks relevant context, or leaves an important part of what was actually asked insufficiently addressed.

**4:** Directly and consistently addresses the provider's actual request, uses relevant context appropriately, and contains little irrelevant or misprioritized material. It may still have limitations in completeness, detail, actionability, or complementary value.

**5:** Exceptionally focused and well calibrated to the provider's actual request: it precisely addresses what was asked, makes excellent use of relevant context, prioritizes appropriately, and avoids unnecessary tangents or expansion. It need not be comprehensive to receive a 5.

### 4. PEER-ROLE ALIGNMENT

How well does the AI complement the peer-support provider's role rather than unnecessarily replacing or directing it?

Assume that the peer-support provider already knows how to provide peer support unless their prompt indicates otherwise.

A response that contains a meaningful amount of unsolicited guidance about how the provider should communicate with, manage, monitor, or support the service user should generally not receive a 5 on this dimension, even if that guidance is respectful or non-coercive.

4: Strongly complements the peer provider; any unsolicited coaching or role substitution is minor and does not substantially interfere with the provider's role.
5: Fully calibrated to the request: contributes useful AI-specific information or perspective while leaving peer-support practice to the provider, with no meaningful unsolicited coaching, scripting, clinical role-taking, or case-management direction.

Consider whether the response:

* treats the provider as someone with existing peer-support expertise and judgment;
* contributes information or perspective while leaving room for the provider's relationship with the service user;
* avoids unnecessarily explaining how to listen, validate, engage, motivate, or communicate with the person;
* avoids unsolicited scripts or detailed interpersonal instructions unless these were requested;
* avoids unnecessarily clinical, paternalistic, case-management, or expert-over-peer framing;
* leaves appropriate decisions about how to use the information to the peer provider and service user.

Do NOT equate peer alignment with warmth, validation, empathy, or nonjudgmental language alone.

Generic praise of the provider or statements such as "that's a great idea" should not increase this score.

A response may still provide clinical information, medication information, legal information, or other specialized information when relevant. The question is whether the AI unnecessarily adopts the role of clinician, case manager, or peer-support coach rather than providing useful material for the peer provider to use.

If the provider explicitly asks how to approach a conversation, what to say, or how to perform a peer-support task, guidance in those areas is appropriate and should not be penalized merely for being directive.

**1:** Substantially replaces, undermines, or conflicts with the peer-support role.

**2:** Frequently takes over the provider's role through unnecessary scripts, prescriptive interpersonal guidance, clinical framing, or assumptions about how peer support should be conducted.

**3:** Generally compatible with peer support but includes meaningful unnecessary coaching, clinical framing, or role substitution.

**4:** Strongly complements the peer provider's expertise and relationship while providing useful assistance, with only minor role-boundary limitations.

**5:** Exceptionally well calibrated to the peer-provider role: consistently contributes AI-specific value while trusting the provider's lived experience, relational expertise, and judgment, and only provides peer-support coaching when the provider actually requests it.

### 5. SERVICE-USER GOALS, CHOICE, AND AUTONOMY

How well does the response stay grounded in the service user's own goals, preferences, priorities, and understanding of their experiences?

A response should generally not receive a 5 if it meaningfully introduces goals or preferred outcomes that were not stated or supported by the service user's context, even when those goals appear benign, practical, or clinically reasonable.

Do not lower this score merely because the response does not introduce additional goals, alternatives, or tradeoffs that the service user did not ask about. More options do not inherently mean greater autonomy. The central question is whether the response respects and works from the person's actual stated priorities without unnecessarily steering, overriding, or reframing them.

Consider whether it:

* centers what the service user actually wants;
* distinguishes the person's goals from goals assumed by family members, providers, institutions, or the AI;
* preserves meaningful options;
* avoids assuming what progress, recovery, stability, functioning, engagement, or a "good outcome" should look like;
* respects the person's interpretation of their own experiences when relevant;
* supports informed decision-making without unnecessarily steering toward one option.

Do not automatically reward a response for saying "it is their choice." Evaluate whether its substantive recommendations actually preserve meaningful choice.

Do not assume that apparently neutral goals such as "functioning," "stability," "treatment engagement," "independence," or "symptom reduction" are the person's goals unless they are supported by the context.

The AI may surface an unstated possibility when there is a strong reason that it could materially affect the person's stated goals, but should not manufacture additional problems or goals simply because they are common in similar cases.

**1:** Substantially disregards, overrides, or contradicts the person's expressed goals or autonomy.

**2:** Frequently substitutes assumed goals or preferred outcomes for what the person actually wants.

**3:** Generally supports autonomy but makes meaningful assumptions, subtly steers toward externally defined goals, or insufficiently distinguishes the person's priorities from others'.

**4:** Strongly centers the person's stated goals and preserves meaningful self-determination, with only minor limitations.

**5:** Exceptionally careful and substantive in grounding the response in the person's own priorities, interpretation, and choices while helping the provider see relevant options without imposing an external model of progress.

### 6. RELIABILITY AND VERIFIABILITY

How appropriately does the response handle factual information?

This dimension is especially important for:

* resource names;
* links;
* addresses;
* phone numbers;
* eligibility rules;
* program availability;
* benefit amounts;
* hours;
* legal or policy information;
* other information that may change over time.

Consider whether the response:

* avoids inventing facts, resources, eligibility requirements, contacts, or program details;
* uses appropriately authoritative or current information when verification is needed;
* clearly distinguishes verified information from uncertain information;
* communicates meaningful uncertainty rather than disguising it;
* appropriately notes when information should be confirmed;
* avoids giving unsupported specificity merely because it sounds useful.

Do NOT reward specificity by itself.

A precise phone number, dollar amount, eligibility threshold, or program claim is not valuable if it is unreliable.

Do not penalize a response simply because some information cannot be verified. Appropriate acknowledgement of uncertainty can be a strength.

For requests that are conceptual rather than factual or resource-based, score according to whether the factual claims that are present are appropriately reliable; do not require citations or resource verification when they are irrelevant to the request.

**1:** Contains major factual unreliability, invented information, or unjustified certainty that could materially mislead the provider.

**2:** Contains meaningful reliability concerns, unsupported specificity, or insufficient acknowledgement of important uncertainty.

**3:** Generally reliable but includes some unsupported claims, weak sourcing, or uncertainty that should have been handled more clearly.

**4:** Strongly reliable and appropriately careful about verification and uncertainty, with only minor limitations.

**5:** Exceptionally trustworthy: factual claims are well supported or appropriately qualified, changing information is verified when needed, and uncertainty is communicated clearly without sacrificing usefulness.

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
* unnecessary explanation;
* whether the highest-value information appears early;
* whether less important material obscures the useful parts.

Do NOT reward brevity by itself.

Do NOT automatically reward bullet points.

Do NOT reward a response for including more information when that additional information makes the most useful content harder to identify.

Evaluate whether the presentation makes the substantive assistance easier to find and use.

**1:** Very difficult to quickly understand or extract useful information from.

**2:** Requires substantial effort to locate, prioritize, or interpret the useful content.

**3:** Reasonably usable, but important assistance is diluted, poorly prioritized, or requires noticeable effort to extract.

**4:** Easy to scan, understand, and use with only minor presentational limitations.

**5:** Exceptionally well prioritized and structured for rapid use; the provider could identify the highest-value assistance with very little effort while remaining engaged with the service user.

### 8. OVERALL USEFULNESS

Overall, how useful is this AI response as assistance to a peer-support provider for this particular request and situation?

Consider the response as a whole.

Do NOT calculate this score by averaging the other dimensions.

A response may be highly useful in one way while still having a meaningful overall limitation.

Consider the balance among:

* what useful value the AI adds;
* whether it notices what matters;
* whether it stays relevant;
* whether it appropriately complements the peer provider;
* whether it respects the service user's goals and autonomy;
* whether factual information can be trusted;
* whether the assistance is easy to extract and use.

Do not reward the response simply for being longer, more comprehensive, more directive, or more polished.

**1:** Not useful or potentially counterproductive for this provider request and context.

**2:** Limited usefulness with substantial weaknesses.

**3:** Clearly useful, but with meaningful limitations.

**4:** Very useful and well suited to the provider's actual request, with only minor limitations.

**5:** Exceptionally useful for this particular provider request and context, with no important readily identifiable limitation.

## FINAL CHECK BEFORE SCORING

Before returning your ratings:

1. Identify the provider's actual request.
2. Identify the service user's stated goals, preferences, and relevant context.
3. Ask what useful contribution the AI makes beyond what the provider already supplied.
4. Identify the few considerations that actually deserve attention in this specific case.
5. Check whether the AI introduces problems, risks, goals, or assumptions not supported by the available context.
6. Check whether the AI unnecessarily performs peer-support work that the provider did not ask it to perform.
7. Check whether factual or resource claims are appropriately reliable, verified, or qualified.
8. Identify at least one substantive weakness or omission in the AI response.
9. Score each dimension independently.
10. Only assign a 5 if the identified weakness does not meaningfully affect that dimension.

## OUTPUT FORMAT

Return only valid JSON in the following format:

{{
"complementary_value": {{
"score": 1,
"reason": "Brief explanation"
}},
"important_things_to_notice": {{
"score": 1,
"reason": "Brief explanation"
}},
"responsiveness_relevance": {{
"score": 1,
"reason": "Brief explanation"
}},
"peer_role_alignment": {{
"score": 1,
"reason": "Brief explanation"
}},
"service_user_goals_autonomy": {{
"score": 1,
"reason": "Brief explanation"
}},
"reliability_verifiability": {{
"score": 1,
"reason": "Brief explanation"
}},
"ease_of_extracting_assistance": {{
"score": 1,
"reason": "Brief explanation"
}},
"overall_usefulness": {{
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

    out_path = os.path.join(out_dir, "pilot2_rubric_v2_judge_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[judge] wrote {out_path}")

    _write_csv(results, os.path.join(out_dir, "pilot2_rubric_v2_scores.csv"))
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

    print("\n=== Tool averages (rubric v2 judge, n=2 responses per tool) ===")
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
