"""
Blind rubric scoring of the real PeerCoPilot vs. baseline responses generated
by generate_real_systems.py — same frozen rubric, same judge machinery
(call_rubric_judge) as judge_responses.py, but scoring real_system_responses.json
into its own output files so the synthetic-calibration results stay untouched.

The judge never sees `system`/`system_label` — only scenario + response text,
exactly like the calibration-set judging.

Usage (from repo root):
    python -m eval.quality_variants.judge_real_systems                       # 3 repeats, everything
    python -m eval.quality_variants.judge_real_systems --repeats 1 --limit 4 # smoke test

Writes:
    eval/quality_variants/output/real_system_scores.csv    one row per (response, repeat)
    eval/quality_variants/output/real_system_summary.csv   averaged per (scenario, system) and per system/group
"""
import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from eval.quality_variants.judge_responses import call_rubric_judge

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
RESPONSES_PATH = OUTPUT_DIR / "real_system_responses.json"
SCORES_PATH = OUTPUT_DIR / "real_system_scores.csv"
SUMMARY_PATH = OUTPUT_DIR / "real_system_summary.csv"

SCORES_HEADER = [
    "scenario_id", "group", "title", "system", "system_label", "gen_repeat", "judge_repeat",
    "resource_accuracy", "planning_actionability", "peer_values_autonomy",
    "responsiveness_contextual_fit", "overall_usefulness",
    "potentially_harmful", "harmful_detail", "justification",
]

DIMS = ["resource_accuracy", "planning_actionability", "peer_values_autonomy",
        "responsiveness_contextual_fit", "overall_usefulness"]


def _numeric(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3, help="Judge repeats per response, for averaging.")
    parser.add_argument("--limit", type=int, default=None, help="Only judge the first N generated responses.")
    parser.add_argument("--workers", type=int, default=50, help="Concurrent judge calls.")
    parser.add_argument(
        "--reasoning-effort", type=str, default=None, choices=["minimal", "low", "medium", "high"],
        help="Omit for the API default.",
    )
    args = parser.parse_args()

    if not RESPONSES_PATH.exists():
        raise SystemExit(f"{RESPONSES_PATH} not found — run generate_real_systems.py first.")

    with open(RESPONSES_PATH) as f:
        responses = json.load(f)
    if args.limit is not None:
        responses = responses[: args.limit]

    jobs = [(r, jr) for r in responses for jr in range(1, args.repeats + 1)]
    print(f"Judging {len(responses)} real-system responses x {args.repeats} judge repeats = "
          f"{len(jobs)} calls, blind to system...")

    rows = []
    started = time.time()

    def _run(job):
        r, judge_repeat = job
        result = call_rubric_judge(r["scenario"], r["response"], args.reasoning_effort)
        return {
            "scenario_id": r["scenario_id"],
            "group": r["group"],
            "title": r["title"],
            "system": r["system"],
            "system_label": r["system_label"],
            "gen_repeat": r["repeat"],
            "judge_repeat": judge_repeat,
            "resource_accuracy": result.get("resource_accuracy"),
            "planning_actionability": result.get("planning_actionability"),
            "peer_values_autonomy": result.get("peer_values_autonomy"),
            "responsiveness_contextual_fit": result.get("responsiveness_contextual_fit"),
            "overall_usefulness": result.get("overall_usefulness"),
            "potentially_harmful": result.get("potentially_harmful"),
            "harmful_detail": result.get("harmful_detail", ""),
            "justification": result.get("justification", ""),
        }

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_run, job) for job in jobs]
        done = 0
        for fut in as_completed(futures):
            try:
                rows.append(fut.result())
            except Exception as exc:
                print(f"[ERROR] judge call failed: {exc}")
                continue
            done += 1
            if done % 20 == 0 or done == len(jobs):
                print(f"[progress] {done}/{len(jobs)} done ({time.time()-started:.0f}s elapsed)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(SCORES_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCORES_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {SCORES_PATH} ({len(rows)} rows)")

    write_summary(rows)


def write_summary(rows):
    by_system = defaultdict(list)
    by_system_group = defaultdict(list)
    for r in rows:
        by_system[r["system_label"]].append(r)
        by_system_group[(r["system_label"], r["group"])].append(r)

    summary_header = ["level", "system", "group", "n"] + DIMS + ["harmful_yes_count"]
    summary_rows = []

    for system_label, group_rows in sorted(by_system.items()):
        entry = {"level": "system_overall", "system": system_label, "group": "", "n": len(group_rows)}
        for dim in DIMS:
            vals = [_numeric(r[dim]) for r in group_rows if _numeric(r[dim]) is not None]
            entry[dim] = round(sum(vals) / len(vals), 2) if vals else None
        entry["harmful_yes_count"] = sum(1 for r in group_rows if r["potentially_harmful"] == "YES")
        summary_rows.append(entry)

    for (system_label, group), group_rows in sorted(by_system_group.items()):
        entry = {"level": "system_x_group", "system": system_label, "group": group, "n": len(group_rows)}
        for dim in DIMS:
            vals = [_numeric(r[dim]) for r in group_rows if _numeric(r[dim]) is not None]
            entry[dim] = round(sum(vals) / len(vals), 2) if vals else None
        entry["harmful_yes_count"] = sum(1 for r in group_rows if r["potentially_harmful"] == "YES")
        summary_rows.append(entry)

    with open(SUMMARY_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_header)
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"Wrote {SUMMARY_PATH}")
    print("\nOverall averages by system:")
    for entry in [e for e in summary_rows if e["level"] == "system_overall"]:
        print(f"  {entry['system']:>22}: " + "  ".join(f"{d}={entry[d]}" for d in DIMS) +
              f"  harmful_yes={entry['harmful_yes_count']}")
    print("\nBy system x task-type group:")
    for entry in [e for e in summary_rows if e["level"] == "system_x_group"]:
        print(f"  {entry['system']:>22} / {entry['group']:>12}: " + "  ".join(f"{d}={entry[d]}" for d in DIMS))


if __name__ == "__main__":
    main()
