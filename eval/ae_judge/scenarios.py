"""
The 9 scenarios in debugging/data/scenario_1.md .. scenario_9.md.

scenario_3 and scenario_4 are literal duplicates (both the Paterson
disability/benefits scenario) -- kept as separate IDs since they're separate
files, but note this when interpreting per-scenario judge results.
"""
import os

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "debugging",
    "data",
)


def _load(name: str) -> str:
    with open(os.path.join(_DATA_DIR, name), encoding="utf-8") as f:
        return f.read().strip()


SCENARIOS = {f"scenario_{i}": _load(f"scenario_{i}.md") for i in range(1, 10)}
