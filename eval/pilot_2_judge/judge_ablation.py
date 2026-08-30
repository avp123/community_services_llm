"""
Score the 20 responses in output/ablation_results.json (5 prompt-section
ablations x 4 scenarios: M1, M2, S4, S5) with rubric v2, and compare each
ablation's per-dimension averages against the full-prompt Version A baseline
for the same 4 scenarios (pulled from nine_scenarios_judge_results.json).

Usage:
    python -m eval.pilot_2_judge.judge_ablation
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
from eval.pilot_2_judge.nine_scenarios import NINE_SCENARIOS

OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
MAX_WORKERS = 10

BY_ID = {s["id"]: s for s in NINE_SCENARIOS}
SCENARIO_IDS = ["M1", "M2", "S4", "S5"]


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set in environment.", file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(OUT_DIR, "ablation_results.json")) as f:
        ablations = json.load(f)

    jobs = []
    for key, entry in ablations.items():
        scenario_text = BY_ID[entry["scenario_id"]]["scenario"]
        jobs.append((key, entry["scenario_id"], entry["omitted_section"], scenario_text, entry["response"]))

    all_results = []
    lock = threading.Lock()
    out_path = os.path.join(OUT_DIR, "ablation_judge_results.json")

    def _run(job):
        key, sid, omitted, scenario_text, response = job
        result = _call(build_prompt({"scenario": scenario_text, "response": response}))
        result["key"] = key
        result["scenario_id"] = sid
        result["omitted_section"] = omitted
        return result

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_run, job): job for job in jobs}
        for i, future in enumerate(as_completed(futures), start=1):
            job = futures[future]
            result = future.result()
            with lock:
                all_results.append(result)
                with open(out_path, "w") as f:
                    json.dump(all_results, f, indent=2)
            print(f"[judge] ({i}/{len(jobs)}) {job[1]} / omit={job[2]} done")

    print(f"[judge] wrote {out_path}")

    csv_path = os.path.join(OUT_DIR, "ablation_scores.csv")
    fieldnames = ["scenario_id", "omitted_section"] + DIMENSIONS + ["primary_strength", "primary_weakness"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_results:
            row = {"scenario_id": r["scenario_id"], "omitted_section": r["omitted_section"]}
            for dim in DIMENSIONS:
                row[dim] = r[dim]["score"]
            row["primary_strength"] = r["primary_strength"]
            row["primary_weakness"] = r["primary_weakness"]
            w.writerow(row)
    print(f"[judge] wrote {csv_path}")

    _print_table(all_results)


def _print_table(results):
    # Baseline: full-prompt Version A scores for the same 4 scenarios, from the
    # existing 9-scenario judge run.
    baseline_path = os.path.join(OUT_DIR, "nine_scenarios_judge_results.json")
    baseline_by_dim = defaultdict(list)
    if os.path.exists(baseline_path):
        with open(baseline_path) as f:
            baseline = json.load(f)
        for r in baseline:
            if r["tool"] == "A" and r["scenario_id"] in SCENARIO_IDS and r.get("rubric") == "v2_general":
                for dim in DIMENSIONS:
                    baseline_by_dim[dim].append(r[dim]["score"])

    by_section = defaultdict(lambda: defaultdict(list))
    for r in results:
        for dim in DIMENSIONS:
            by_section[r["omitted_section"]][dim].append(r[dim]["score"])

    sections = list(by_section.keys())
    print("\n=== Ablation judge averages vs full-prompt Version A baseline (n=4 scenarios) ===")
    header = "dimension".ljust(32) + "full-A".rjust(10) + "".join(s[:16].rjust(18) for s in sections)
    print(header)
    for dim in DIMENSIONS:
        base_vals = baseline_by_dim.get(dim, [])
        base_avg = sum(base_vals) / len(base_vals) if base_vals else float("nan")
        row = dim.ljust(32) + f"{base_avg:10.2f}"
        for s in sections:
            vals = by_section[s][dim]
            avg = sum(vals) / len(vals) if vals else float("nan")
            row += f"{avg:18.2f}"
        print(row)


if __name__ == "__main__":
    main()
