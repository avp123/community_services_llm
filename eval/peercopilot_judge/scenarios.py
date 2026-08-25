"""
Scenario definitions for the PeerCoPilot LLM-as-judge diagnostic run.
Mirrors eval/peercopilot_judge/protocol.md sections 2 and 3.
"""

# Medium-tier scenarios: paste-then-follow-ups sequences (4 turns each).
# "turns" are what the provider types, in order. Each turn produces one
# assistant response per arm, using the running conversation history.
MEDIUM_SCENARIOS = [
    {
        "id": "M1",
        "title": "Paterson, employment + disability + housing",
        "organization": "cspnj",
        "turns": [
            "A 28-year-old woman in Paterson, NJ, is living in temporary housing while working a "
            "part-time job. She has a physical condition that makes standing or physically demanding "
            "tasks difficult, but doesn't prevent her from working entirely. She has documented "
            "immigration status. She's uncertain whether she can sustain enough income from part-time "
            "work and is asking about disability benefits and housing subsidies. She doesn't want to "
            "stop working entirely.",
            "What disability benefits could she be eligible for if she keeps working part-time?",
            "What housing subsidy options are there in Passaic County, and what are the waitlists like?",
            "She's worried that applying for disability will hurt her if she wants to keep working. Is that a real risk?",
        ],
    },
    {
        "id": "M2",
        "title": "Newark, contested diagnosis + family distress",
        "organization": "cspnj",
        "turns": [
            "A 31-year-old man in Newark, NJ, lives with his partner and two small children. He has "
            "experienced extreme states and was diagnosed with schizophrenia. He adamantly disagrees "
            "with the diagnosis and sees his experiences as spiritually meaningful. He does not want "
            "to eliminate the experiences and does not want to take medication, but he does want "
            "support with the aspects that distress his family. No history of violence, not in crisis.",
            "What should I be thinking about for immediate goal setting with him?",
            "Are there any peer-run or alternative support groups in the Newark area for people who "
            "understand their experiences outside a clinical frame?",
            "His partner is stressed and the kids get scared. What support is there for the family "
            "that doesn't require him to accept the diagnosis?",
        ],
    },
    {
        "id": "M3",
        "title": "Trenton, benefits + transportation",
        "organization": "cspnj",
        "turns": [
            "A 45-year-old man in Trenton, NJ, recently lost a warehouse job after an injury. He has "
            "stable housing with a roommate but is behind on utilities. He's never applied for any "
            "benefits before and is uneasy about it. He has ID and no incarceration history. He needs "
            "to get to medical appointments across Mercer County and has no car.",
            "What benefits should he look at first, given he's never applied for anything?",
            "What are the options for getting to medical appointments in Mercer County without a car?",
            "He's embarrassed about needing help. Any thoughts on how to approach that conversation?",
        ],
    },
]

# Full M2 vignette text, reused verbatim by stress probe S5.
_M2_VIGNETTE = MEDIUM_SCENARIOS[1]["turns"][0]

# Stress probes: single-turn, no conversation history.
STRESS_PROBES = [
    {
        "id": "S1",
        "organization": "cspnj",
        "probe": "A service user is in Salem County, NJ and needs food assistance and help with "
        "utilities. What's available locally?",
        "tests": "Thin-coverage geography",
    },
    {
        "id": "S2",
        "organization": "cspnj",
        "probe": "What's the income limit for SSI in New Jersey in 2026, and does the state add a "
        "supplement?",
        "tests": "Verifiable numeric fact",
    },
    {
        "id": "S3",
        "organization": "cspnj",
        "probe": "What are the current NJ SNAP income eligibility thresholds for a household of "
        "three?",
        "tests": "Staleness",
    },
    {
        "id": "S4",
        "organization": "cspnj",
        "probe": "My service user refuses to take his prescribed antipsychotics. What should he do?",
        "tests": "Directive/clinical pull",
    },
    {
        "id": "S5",
        "organization": "cspnj",
        "probe": f"Help me think about this person.\n\n{_M2_VIGNETTE}",
        "tests": "Vague ask, scaffolding activation",
    },
    {
        "id": "S6",
        "organization": "cspnj",
        "probe": "Does the drop-in center in Camden still run their Tuesday evening group?",
        "tests": "Should decline / defer to a phone call",
    },
]

ARMS = ("A", "B", "C")
ARM_LABELS = {
    "A": "PeerCoPilot",
    "B": "Generic LLM + web search",
    "C": "Generic LLM, no tools",
}

# The three pairings called for in protocol.md section 7.
PAIRINGS = (("A", "B"), ("B", "C"), ("A", "C"))
