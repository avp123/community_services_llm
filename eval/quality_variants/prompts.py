"""
Four response-type prompt templates. Types 1-3 are fixed, group-independent
quality variants (ideal / directive-imposing / warm-but-vague). Type 4 is
group-specific, targeting a different gap per scenario group (see
scenarios.py): weak resource info, unfocused planning, or subtly imposed
interpretation.
"""

TYPE_1_IDEAL = """You are helping a peer-support provider respond to the scenario below.

Write a high-quality response that the peer provider could use to help the service user.

The response should:

* directly address what the person wants help with,
* be useful and concrete,
* respect the person's autonomy and preferences,
* avoid being unnecessarily directive or clinical,
* provide accurate information when relevant,
* help clarify goals or next steps when relevant,
* reflect the values and philosophy of peer support.

Do not explain or evaluate your response.
Only provide the response itself.

SCENARIO:

{scenario}"""

TYPE_2_DIRECTIVE = """You are helping a peer-support provider respond to the scenario below.

Write a response that is highly practical, confident, and solution-oriented.

Prioritize giving the person clear recommendations about what they should do.
Identify what you think the best course of action is and give concrete next steps.
Where there are several possible approaches, choose the approach you think is best rather than spending substantial time exploring the person's preferences.

The response should still be reasonable and well-intentioned.
Do not make it obviously bad, reckless, rude, or absurd.

Do not explain or evaluate your response.
Only provide the response itself.

SCENARIO:

{scenario}"""

TYPE_3_WARM_VAGUE = """You are helping a peer-support provider respond to the scenario below.

Write a response that is warm, validating, nonjudgmental, and highly respectful of the person's autonomy.

Avoid telling the person what to do.
Emphasize that their preferences and choices matter.

However, provide relatively little concrete information, problem-solving, planning, or actionable next steps.
The response should sound supportive and appropriate but ultimately be somewhat vague and limited in practical usefulness.

Do not make the response obviously bad or unnatural.

Do not explain or evaluate your response.
Only provide the response itself.

SCENARIO:

{scenario}"""

TYPE_4_BY_GROUP = {
    "resource": """You are helping a peer-support provider respond to the scenario below.

Write a response that is supportive and well reasoned, but weak on specific resource information —
it should not name concrete programs, agencies, or next steps for finding resources, even though
the scenario calls for that kind of practical information.

The response should still sound reasonable and well-intentioned, not obviously bad.

Do not explain or evaluate your response.
Only provide the response itself.

SCENARIO:

{scenario}""",
    "planning": """You are helping a peer-support provider respond to the scenario below.

Write a response that is well-intentioned and polished, but fails specifically at planning and
actionability. To do this:

- Offer many plausible options or ideas for the person to consider.
- Do NOT ask the person which of these matters most to them.
- Do NOT compare the options against each other or weigh tradeoffs.
- Do NOT put the options in any order or sequence.
- Do NOT identify a single first step to start with.
- Do NOT tailor the suggestions to the person's stated readiness, constraints, or circumstances.

Do not repair this weakness with autonomy-preserving caveats, collaborative language, or later
qualifications (e.g. "of course, it's up to you which one fits best"). The response should remain
plausible, warm, and well-intentioned in tone, but the lack of prioritization, sequencing, and
tailoring must materially affect the substance of the response — a peer provider using this
response would still not know where to start.

Do not explain or evaluate your response.
Only provide the response itself.

SCENARIO:

{scenario}""",
    "peer_values": """You are helping a peer-support provider respond to the scenario below.

Write a response that is polished, confident, and conventionally helpful in tone, but that
contains a genuine, substantive autonomy violation. To do this, use at least one of the following:

- Decide, on the response's own authority, what "progress" or "doing well" should mean for this
  person, rather than asking or centering what they've said they want.
- Privilege what the person's family, provider, or another third party wants for them over what
  the person themselves has stated they want.
- Frame one particular outcome or direction as obviously the right or preferable one, presented as
  settled rather than as the person's own choice to make.

Do not repair this weakness with autonomy-preserving caveats, collaborative language, or later
qualifications (e.g. "but ultimately it's your choice," "only if that feels right to you"). The
response should remain plausible and well-intentioned in tone — not rude, harsh, or overtly
clinical — but the imposed interpretation or privileging of someone else's goals over the person's
own must materially affect the substance of the response, not just its style.

Do not explain or evaluate your response.
Only provide the response itself.

SCENARIO:

{scenario}""",
}

TYPE_LABELS = {
    1: "ideal",
    2: "directive",
    3: "warm_vague",
    4: "group_specific_gap",
}


def build_prompt(response_type: int, scenario_text: str, group: str) -> str:
    if response_type == 1:
        template = TYPE_1_IDEAL
    elif response_type == 2:
        template = TYPE_2_DIRECTIVE
    elif response_type == 3:
        template = TYPE_3_WARM_VAGUE
    elif response_type == 4:
        template = TYPE_4_BY_GROUP[group]
    else:
        raise ValueError(f"Unknown response_type: {response_type}")
    return template.format(scenario=scenario_text)
