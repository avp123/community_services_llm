"""
Score the 18 responses in output/nine_scenarios_responses.json (9 scenarios x
Version A/B, see generate_nine_scenarios.py) with rubric v2
(judge_pilot2_rubric_v2.py).

Calls are parallelized (up to 10 at a time) and results are written to disk
incrementally as they complete, so a partial run still leaves usable output.

Usage:
    python -m eval.pilot_2_judge.judge_nine_scenarios
"""
import csv
import json
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from eval.pilot_2_judge.judge_pilot2_rubric_v2 import DIMENSIONS
from eval.pilot_2_judge.judge_pilot2_rubric_v2 import _call as _call_v2
from eval.pilot_2_judge.judge_pilot2_rubric_v2 import build_prompt as build_prompt_v2

OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
MAX_WORKERS = 10

RUBRICS = {
    "v2_general": (build_prompt_v2, _call_v2),
}


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set in environment.", file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(OUT_DIR, "nine_scenarios_responses.json")) as f:
        responses = json.load(f)

    jobs = [
        (convo, rubric_name, build_prompt, call)
        for convo in responses
        for rubric_name, (build_prompt, call) in RUBRICS.items()
    ]

    all_results = []
    lock = threading.Lock()
    out_path = os.path.join(OUT_DIR, "nine_scenarios_judge_results.json")

    def _run(job):
        convo, rubric_name, build_prompt, call = job
        result = call(build_prompt(convo))
        result["scenario_id"] = convo["scenario_id"]
        result["tool"] = convo["tool"]
        result["rubric"] = rubric_name
        return result

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_run, job): job for job in jobs}
        for i, future in enumerate(as_completed(futures), start=1):
            job = futures[future]
            convo = job[0]
            result = future.result()
            with lock:
                all_results.append(result)
                with open(out_path, "w") as f:
                    json.dump(all_results, f, indent=2)
            print(f"[judge] ({i}/{len(jobs)}) {convo['scenario_id']} Version {convo['tool']} -- {job[1]} done")

    print(f"[judge] wrote {out_path}")

    csv_path = os.path.join(OUT_DIR, "nine_scenarios_scores.csv")
    fieldnames = ["scenario_id", "tool", "rubric"] + DIMENSIONS + ["primary_strength", "primary_weakness"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_results:
            row = {"scenario_id": r["scenario_id"], "tool": r["tool"], "rubric": r["rubric"]}
            for dim in DIMENSIONS:
                row[dim] = r[dim]["score"]
            row["primary_strength"] = r["primary_strength"]
            row["primary_weakness"] = r["primary_weakness"]
            w.writerow(row)
    print(f"[judge] wrote {csv_path}")

    _print_tables(all_results)


def _print_tables(results):
    for rubric_name in RUBRICS:
        by_tool = defaultdict(lambda: defaultdict(list))
        for r in results:
            if r["rubric"] != rubric_name:
                continue
            for dim in DIMENSIONS:
                by_tool[r["tool"]][dim].append(r[dim]["score"])

        n = len(by_tool.get("A", {}).get(DIMENSIONS[0], []))
        print(f"\n=== Version averages -- {rubric_name} (n={n} scenarios per version) ===")
        print("dimension".ljust(32) + "Version A".rjust(12) + "Version B".rjust(12))
        for dim in DIMENSIONS:
            avgs = {}
            for t in ("A", "B"):
                vals = by_tool.get(t, {}).get(dim, [])
                avgs[t] = sum(vals) / len(vals) if vals else float("nan")
            print(dim.ljust(32) + f"{avgs['A']:12.2f}" + f"{avgs['B']:12.2f}")


if __name__ == "__main__":
    main()
