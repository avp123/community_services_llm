"""
Score Tool C's generated responses (output/tool_c_responses.json, see
generate_tool_c.py) with the same v3 "peer-informed" rubric used for A/B
(judge_pilot2_rubric_v3.py), then print a 3-way A/B/C comparison table by
reusing the already-scored A/B results in output/pilot2_rubric_v3_scores.csv.

Usage:
    python -m eval.pilot_2_judge.judge_tool_c
"""
import csv
import json
import os
import sys
from collections import defaultdict

from eval.pilot_2_judge.judge_pilot2_rubric_v3 import DIMENSIONS, _call, build_prompt

OUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set in environment.", file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(OUT_DIR, "tool_c_responses.json")) as f:
        tool_c = json.load(f)

    results = []
    for convo in tool_c:
        print(f"[judge] scoring {convo['conversation_id']} (Tool C)...")
        result = _call(build_prompt(convo))
        result["conversation_id"] = convo["conversation_id"]
        result["tool"] = "C"
        result["order_index"] = convo["order_index"]
        results.append(result)

    out_path = os.path.join(OUT_DIR, "pilot2_rubric_v3_tool_c_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[judge] wrote {out_path}")

    csv_path = os.path.join(OUT_DIR, "pilot2_rubric_v3_tool_c_scores.csv")
    fieldnames = ["conversation_id", "order_index", "tool"] + DIMENSIONS + [
        "primary_strength", "primary_weakness",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            row = {"conversation_id": r["conversation_id"], "order_index": r["order_index"], "tool": r["tool"]}
            for dim in DIMENSIONS:
                row[dim] = r[dim]["score"]
            row["primary_strength"] = r["primary_strength"]
            row["primary_weakness"] = r["primary_weakness"]
            w.writerow(row)
    print(f"[judge] wrote {csv_path}")

    _print_three_way_table(results)


def _print_three_way_table(c_results):
    by_tool = defaultdict(lambda: defaultdict(list))

    for r in c_results:
        for dim in DIMENSIONS:
            by_tool["C"][dim].append(r[dim]["score"])

    ab_csv = os.path.join(OUT_DIR, "pilot2_rubric_v3_scores.csv")
    with open(ab_csv) as f:
        for row in csv.DictReader(f):
            for dim in DIMENSIONS:
                by_tool[row["tool"]][dim].append(int(row[dim]))

    print("\n=== Tool averages (rubric v3 judge, n=2 responses per tool) ===")
    header = "dimension".ljust(32) + "Tool A".rjust(10) + "Tool B".rjust(10) + "Tool C".rjust(10)
    print(header)
    for dim in DIMENSIONS:
        vals = {t: by_tool.get(t, {}).get(dim, []) for t in ("A", "B", "C")}
        avgs = {t: (sum(v) / len(v) if v else float("nan")) for t, v in vals.items()}
        print(dim.ljust(32) + f"{avgs['A']:10.2f}" + f"{avgs['B']:10.2f}" + f"{avgs['C']:10.2f}")


if __name__ == "__main__":
    main()
