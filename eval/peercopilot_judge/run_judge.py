"""
Step 2: run the LLM-as-judge pairwise comparisons over eval/peercopilot_judge/output/raw_responses.json.

Produces (protocol.md section 8):
    output/judge_scores.csv           one row per (scenario, turn, arm-pair, judge_model, rubric, repeat, order)
    output/judge_resources.csv        every resource extraction, as-is (verbose — includes repeat/order duplicates)
    output/judge_resources_deduped.csv  one row per (scenario, arm, resource_name) for your manual verification pass

Usage (from repo root):
    python -m eval.peercopilot_judge.run_judge                        # full run: both rubrics, 3 repeats
    python -m eval.peercopilot_judge.run_judge --repeats 1 --rubrics A --limit 2   # cheap smoke test
    python -m eval.peercopilot_judge.run_judge --workers 6            # more concurrent judge calls

This is the expensive step (judge_model x pairs x orders x rubrics x repeats
chat completions) — use --limit / --repeats to sanity-check spend before a
full run. Rows are written to the CSVs as each judge call completes, so you
can tail the output files mid-run and a crash doesn't lose finished work.
"""
import argparse
import csv
from collections import Counter, defaultdict
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `backend.*` imports

from eval.peercopilot_judge.confounds import compute_confounds
from eval.peercopilot_judge.judge import call_judge, _rubric_keys, JUDGE_MODEL
from eval.peercopilot_judge.scenarios import ARM_LABELS, PAIRINGS

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
RAW_PATH = OUTPUT_DIR / "raw_responses.json"
SCORES_PATH = OUTPUT_DIR / "judge_scores.csv"
RESOURCES_PATH = OUTPUT_DIR / "judge_resources.csv"
RESOURCES_DEDUPED_PATH = OUTPUT_DIR / "judge_resources_deduped.csv"

SCORES_HEADER = [
    "scenario_id", "turn_index", "arm_1", "arm_2", "judge_model", "rubric", "repeat", "order",
    "score1_a", "score1_b", "score1_c", "score1_d",
    "score2_a", "score2_b", "score2_c", "score2_d",
    "preference", "preference_reasoning",
    "word_count_1", "word_count_2",
    "directive_ratio_1", "directive_ratio_2",
    "resource_count_1", "resource_count_2",
]

RESOURCES_HEADER = [
    "scenario_id", "turn_index", "arm", "resource_name", "type", "location_claimed",
    "specific_claim", "verbatim_context",
    "verified_exists", "verified_serves_county", "verified_eligibility", "verified_contact", "notes",
]

DEDUPED_HEADER = [
    "scenario_id", "arm", "resource_name", "type", "location_claimed",
    "specific_claim", "verbatim_context", "seen_count",
    "verified_exists", "verified_serves_county", "verified_eligibility", "verified_contact", "notes",
]


def build_comparison_units(raw: dict):
    """
    Flatten raw_responses.json into a list of comparison units:
    {scenario_id, turn_index, scenario_text, responses: {"A": text, "B": text, "C": text}}
    """
    units = []

    for scenario in raw["medium_scenarios"]:
        arm_a_turns = scenario["arms"]["A"]  # turn structure (user_turn) identical across arms
        history_text = ""
        for turn_index, turn in enumerate(arm_a_turns):
            history_text += f"\n[Provider]: {turn['user_turn']}\n"
            responses = {arm: scenario["arms"][arm][turn_index]["response"] for arm in scenario["arms"]}
            units.append(
                {
                    "scenario_id": scenario["id"],
                    "turn_index": turn_index,
                    "scenario_text": history_text.strip(),
                    "responses": responses,
                }
            )

    for probe in raw["stress_probes"]:
        units.append(
            {
                "scenario_id": probe["id"],
                "turn_index": 0,
                "scenario_text": probe["probe"],
                "responses": probe["arms"],
            }
        )

    return units


class IncrementalCsvWriter:
    """Opens the CSV once, appends+flushes each row as it's produced. Thread-safe."""

    def __init__(self, path: Path, header: list):
        self._lock = threading.Lock()
        self._file = open(path, "w", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=header)
        self._writer.writeheader()
        self._file.flush()
        self.count = 0

    def write(self, row: dict):
        with self._lock:
            self._writer.writerow(row)
            self._file.flush()
            self.count += 1

    def close(self):
        self._file.close()


def judge_one_call(unit, rubric, arm_1, arm_2, order, repeat, scores_writer, resources_writer, reasoning_effort=None):
    response_1 = unit["responses"].get(arm_1)
    response_2 = unit["responses"].get(arm_2)
    if response_1 is None or response_2 is None:
        return None, None, None

    r1, r2 = (response_1, response_2) if order == "forward" else (response_2, response_1)
    label_1, label_2 = (arm_1, arm_2) if order == "forward" else (arm_2, arm_1)
    keys = _rubric_keys(rubric)

    conf_1 = compute_confounds(r1)
    conf_2 = compute_confounds(r2)

    result = call_judge(rubric, unit["scenario_text"], r1, r2, reasoning_effort=reasoning_effort)
    s1 = result.get("response_1", {})
    s2 = result.get("response_2", {})

    row = {
        "scenario_id": unit["scenario_id"],
        "turn_index": unit["turn_index"],
        "arm_1": label_1,
        "arm_2": label_2,
        "judge_model": JUDGE_MODEL,
        "rubric": rubric,
        "repeat": repeat,
        "order": order,
        "score1_a": s1.get(keys[0]), "score1_b": s1.get(keys[1]),
        "score1_c": s1.get(keys[2]), "score1_d": s1.get(keys[3]),
        "score2_a": s2.get(keys[0]), "score2_b": s2.get(keys[1]),
        "score2_c": s2.get(keys[2]), "score2_d": s2.get(keys[3]),
        "preference": result.get("preference", ""),
        "preference_reasoning": result.get("preference_reasoning", ""),
        "word_count_1": conf_1["word_count"], "word_count_2": conf_2["word_count"],
        "directive_ratio_1": conf_1["directive_ratio"], "directive_ratio_2": conf_2["directive_ratio"],
        "resource_count_1": len(s1.get("resources", []) or []),
        "resource_count_2": len(s2.get("resources", []) or []),
    }
    scores_writer.write(row)

    for side_label, side_scores in ((label_1, s1), (label_2, s2)):
        for res in side_scores.get("resources", []) or []:
            resources_writer.write(
                {
                    "scenario_id": unit["scenario_id"],
                    "turn_index": unit["turn_index"],
                    "arm": side_label,
                    "resource_name": res.get("name", ""),
                    "type": res.get("type", ""),
                    "location_claimed": res.get("location_claimed", ""),
                    "specific_claim": res.get("specific_claim", ""),
                    "verbatim_context": res.get("verbatim_context", ""),
                    "verified_exists": "", "verified_serves_county": "",
                    "verified_eligibility": "", "verified_contact": "", "notes": "",
                }
            )

    return row.get("preference"), label_1, label_2


def dedupe_resources(resources_path: Path, deduped_path: Path):
    """Collapse judge_resources.csv to one row per (scenario_id, arm, resource_name),
    keeping the first-seen claim/context and a seen_count of how many extractions matched."""
    seen = {}
    order = []
    with open(resources_path) as f:
        for row in csv.DictReader(f):
            key = (row["scenario_id"], row["arm"], row["resource_name"].strip().lower())
            if key not in seen:
                seen[key] = {**row, "seen_count": 1}
                order.append(key)
            else:
                seen[key]["seen_count"] += 1

    with open(deduped_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DEDUPED_HEADER)
        writer.writeheader()
        for key in order:
            row = seen[key]
            writer.writerow({k: row.get(k, "") for k in DEDUPED_HEADER})

    return len(order)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3, help="Repeats per (pair, order, rubric). Protocol suggests 3-4.")
    parser.add_argument("--rubrics", type=str, default="A,B", help="Comma-separated rubric names to run, e.g. 'A' or 'A,B'.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N comparison units (for smoke-testing cost).")
    parser.add_argument(
        "--workers", type=int, default=100,
        help="Concurrent judge calls in flight. Measured clean (no rate-limit errors) up to "
        "150 concurrent on this account; 100 keeps headroom while still finishing a full "
        "648-call run in ~2 minutes at --reasoning-effort minimal.",
    )
    parser.add_argument(
        "--reasoning-effort", type=str, default="minimal", choices=["minimal", "low", "medium", "high"],
        help="gpt-5-mini reasoning effort. Measured: 'minimal' ~19s/call, ~1950 completion "
        "tokens; unset/default ~55s/call, ~5500 completion tokens (roughly 'medium'). "
        "Lower effort = faster and cheaper, at some unverified cost to judgment quality.",
    )
    parser.add_argument(
        "--include", type=str, default=None,
        help="Comma-separated scenario/probe filter, e.g. 'M1:0,S2,S6' (M1 turn 0 only, "
        "plus all of S2 and S6). Omit to include every comparison unit.",
    )
    args = parser.parse_args()

    rubrics = [r.strip() for r in args.rubrics.split(",") if r.strip()]

    if not RAW_PATH.exists():
        raise SystemExit(f"{RAW_PATH} not found — run run_experiment.py first.")

    with open(RAW_PATH) as f:
        raw = json.load(f)

    units = build_comparison_units(raw)

    if args.include:
        filters = []
        for token in args.include.split(","):
            token = token.strip()
            if not token:
                continue
            if ":" in token:
                sid, turn = token.split(":", 1)
                filters.append((sid.strip(), int(turn.strip())))
            else:
                filters.append((token, None))
        units = [
            u for u in units
            if any(sid == u["scenario_id"] and (turn is None or turn == u["turn_index"]) for sid, turn in filters)
        ]

    if args.limit is not None:
        units = units[: args.limit]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scores_writer = IncrementalCsvWriter(SCORES_PATH, SCORES_HEADER)
    resources_writer = IncrementalCsvWriter(RESOURCES_PATH, RESOURCES_HEADER)

    jobs = []
    for unit in units:
        for rubric in rubrics:
            for arm_1, arm_2 in PAIRINGS:
                for order in ("forward", "reversed"):
                    for repeat in range(1, args.repeats + 1):
                        jobs.append((unit, rubric, arm_1, arm_2, order, repeat))

    total = len(jobs)
    print(f"Running {total} judge calls across {len(units)} comparison units, {len(rubrics)} rubric(s), "
          f"{args.repeats} repeat(s), {args.workers} workers...")

    done = 0
    started = time.time()
    lock = threading.Lock()

    def _run(job):
        unit, rubric, arm_1, arm_2, order, repeat = job
        judge_one_call(
            unit, rubric, arm_1, arm_2, order, repeat, scores_writer, resources_writer,
            reasoning_effort=args.reasoning_effort,
        )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_run, job) for job in jobs]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                print(f"[ERROR] judge call failed: {exc}")
                continue
            with lock:
                done += 1
                if done % 5 == 0 or done == total:
                    elapsed = time.time() - started
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (total - done) / rate if rate > 0 else float("inf")
                    print(f"[progress] {done}/{total} judge calls done ({elapsed:.0f}s elapsed, "
                          f"~{eta:.0f}s remaining) — scores.csv={scores_writer.count} rows, "
                          f"resources.csv={resources_writer.count} rows")

    scores_writer.close()
    resources_writer.close()

    n_deduped = dedupe_resources(RESOURCES_PATH, RESOURCES_DEDUPED_PATH)

    print(f"\nWrote {SCORES_PATH} ({scores_writer.count} rows)")
    print(f"Wrote {RESOURCES_PATH} ({resources_writer.count} rows, raw/duplicated)")
    print(f"Wrote {RESOURCES_DEDUPED_PATH} ({n_deduped} rows, deduped — this is the one to hand-check)")
    print(f"\nArm labels for reference: {ARM_LABELS}")
    print("\nPreference tally, computed from the written CSV (rubric, pair) -> {arm: count}:")
    for rubric, arm_pair, counts in tally_preferences_from_csv(SCORES_PATH):
        print(f"  rubric {rubric} {arm_pair[0]} vs {arm_pair[1]}: {counts}")


def tally_preferences_from_csv(scores_path: Path):
    """
    Re-derive the win-tally straight from the finished CSV (not from in-flight
    thread state) so it can't be wrong due to a concurrency bug — group by
    unordered arm pair regardless of which order the judge saw them in.
    """
    tallies = defaultdict(Counter)
    with open(scores_path) as f:
        for row in csv.DictReader(f):
            pair = tuple(sorted((row["arm_1"], row["arm_2"])))
            if row["preference"] == "1":
                winner = row["arm_1"]
            elif row["preference"] == "2":
                winner = row["arm_2"]
            else:
                winner = "tie"
            tallies[(row["rubric"], pair)][winner] += 1

    for (rubric, pair), counts in sorted(tallies.items()):
        yield rubric, pair, dict(counts)


if __name__ == "__main__":
    main()
