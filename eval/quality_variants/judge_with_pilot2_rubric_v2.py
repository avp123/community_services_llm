"""
Score the 54 responses in output/real_system_responses.json (9 quality_variants
scenarios x Version A/B x 3 generation repeats) with the pilot_2_judge rubric v2
(eval/pilot_2_judge/judge_pilot2_rubric_v2.py) -- the 8-dimension rubric this
session already calibration/sensitivity-tested, instead of this directory's own
untested rubric.py, which showed near-ceiling scores (4.9-5.0) even for
responses that visibly differ (e.g. Version B including quoted scripts where
Version A doesn't).

Usage (from repo root, backend/.env sourced isn't needed -- only OPENAI_API_KEY):
    python -m eval.quality_variants.judge_with_pilot2_rubric_v2
"""
import csv
import json
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from eval.pilot_2_judge.judge_pilot2_rubric_v2 import DIMENSIONS
from eval.pilot_2_judge.judge_pilot2_rubric_v2 import _call
from eval.pilot_2_judge.judge_pilot2_rubric_v2 import build_prompt

OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
MAX_WORKERS = 10


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set in environment.", file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(OUT_DIR, "real_system_responses.json")) as f:
        responses = json.load(f)

    all_results = []
    lock = threading.Lock()
    out_path = os.path.join(OUT_DIR, "real_system_pilot2v2_judge_results.json")

    def _run(convo):
        result = _call(build_prompt({"scenario": convo["scenario"], "response": convo["response"]}))
        result["scenario_id"] = convo["scenario_id"]
        result["group"] = convo["group"]
        result["title"] = convo["title"]
        result["system"] = convo["system"]
        result["system_label"] = convo["system_label"]
        result["repeat"] = convo["repeat"]
        return result

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_run, convo): convo for convo in responses}
        for i, future in enumerate(as_completed(futures), start=1):
            convo = futures[future]
            result = future.result()
            with lock:
                all_results.append(result)
                with open(out_path, "w") as f:
                    json.dump(all_results, f, indent=2)
            print(f"[judge] ({i}/{len(responses)}) scenario {convo['scenario_id']} system {convo['system']} repeat {convo['repeat']} done")

    print(f"[judge] wrote {out_path}")

    csv_path = os.path.join(OUT_DIR, "real_system_pilot2v2_scores.csv")
    fieldnames = ["scenario_id", "group", "title", "system", "repeat"] + DIMENSIONS + ["primary_strength", "primary_weakness"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_results:
            row = {"scenario_id": r["scenario_id"], "group": r["group"], "title": r["title"], "system": r["system"], "repeat": r["repeat"]}
            for dim in DIMENSIONS:
                row[dim] = r[dim]["score"]
            row["primary_strength"] = r["primary_strength"]
            row["primary_weakness"] = r["primary_weakness"]
            w.writerow(row)
    print(f"[judge] wrote {csv_path}")

    _print_tables(all_results)


def _print_tables(results):
    by_system = defaultdict(lambda: defaultdict(list))
    by_system_group = defaultdict(lambda: defaultdict(list))
    for r in results:
        for dim in DIMENSIONS:
            by_system[r["system"]][dim].append(r[dim]["score"])
            by_system_group[(r["system"], r["group"])][dim].append(r[dim]["score"])

    n = len(by_system.get("A", {}).get(DIMENSIONS[0], []))
    print(f"\n=== System averages -- pilot2 rubric v2 (n={n} responses per system) ===")
    print("dimension".ljust(32) + "Version A".rjust(12) + "Version B".rjust(12))
    for dim in DIMENSIONS:
        avgs = {}
        for t in ("A", "B"):
            vals = by_system.get(t, {}).get(dim, [])
            avgs[t] = sum(vals) / len(vals) if vals else float("nan")
        print(dim.ljust(32) + f"{avgs['A']:12.2f}" + f"{avgs['B']:12.2f}")

    groups = sorted(set(g for (_, g) in by_system_group))
    for group in groups:
        print(f"\n=== System averages by group={group} ===")
        print("dimension".ljust(32) + "Version A".rjust(12) + "Version B".rjust(12))
        for dim in DIMENSIONS:
            avgs = {}
            for t in ("A", "B"):
                vals = by_system_group.get((t, group), {}).get(dim, [])
                avgs[t] = sum(vals) / len(vals) if vals else float("nan")
            print(dim.ljust(32) + f"{avgs['A']:12.2f}" + f"{avgs['B']:12.2f}")


if __name__ == "__main__":
    main()
