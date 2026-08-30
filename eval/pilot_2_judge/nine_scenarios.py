"""
The 9 single-turn scenarios used for the A/B/C x rubric-v2/v3 comparison:
the first-turn "paste" from each of protocol.md's 3 Medium scenarios (M1-M3)
plus all 6 stress probes (S1-S6). Pulled directly from
eval/peercopilot_judge/scenarios.py so the text stays byte-identical to the
protocol.

Only the first turn of M1-M3 is used (no multi-turn follow-ups) so every
scenario here is a single provider message with no prior conversation
history -- matching the shape of the earlier 4-conversation pilot comparison.
"""
from eval.peercopilot_judge.scenarios import MEDIUM_SCENARIOS, STRESS_PROBES

NINE_SCENARIOS = [
    {"id": m["id"], "organization": m["organization"], "scenario": m["turns"][0]}
    for m in MEDIUM_SCENARIOS
] + [
    {"id": s["id"], "organization": s["organization"], "scenario": s["probe"]}
    for s in STRESS_PROBES
]

assert len(NINE_SCENARIOS) == 9
