"""
Repeatability test: score the same response 5x independently to measure
judge score variance per dimension, and record token usage/cost. Calls are
parallelized (up to 10 at a time) and results are written to disk
incrementally as they complete.
"""
import json
import os
import statistics
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from eval.pilot_2_judge.judge_pilot2_rubric_v2 import build_prompt, DIMENSIONS, _client, JUDGE_MODEL

MAX_WORKERS = 10
OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
with open(os.path.join(OUT_DIR, "nine_scenarios_responses.json")) as f:
    responses = json.load(f)

by_key = {(r["scenario_id"], r["tool"]): r for r in responses}

TEST_CASES = [("M1", "A"), ("S3", "A"), ("S2", "B")]
N_REPEATS = 5

jobs = [(key, rep) for key in TEST_CASES for rep in range(N_REPEATS)]

results = defaultdict(lambda: defaultdict(list))
usage_totals = []
raw_log = defaultdict(list)  # key -> list of {rep, scores, usage}
lock = threading.Lock()
out_path = os.path.join(OUT_DIR, "reliability_results.json")


def _run(job):
    key, rep = job
    convo = by_key[key]
    prompt = build_prompt(convo)
    completion = _client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    raw = completion.choices[0].message.content or "{}"
    parsed = json.loads(raw)
    usage = {
        "prompt_tokens": completion.usage.prompt_tokens,
        "completion_tokens": completion.usage.completion_tokens,
        "total_tokens": completion.usage.total_tokens,
    }
    return key, rep, parsed, usage


with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
    futures = {pool.submit(_run, job): job for job in jobs}
    for i, future in enumerate(as_completed(futures), start=1):
        key, rep, parsed, usage = future.result()
        with lock:
            for dim in DIMENSIONS:
                results[key][dim].append(parsed[dim]["score"])
            usage_totals.append(usage)
            raw_log["|".join(key)].append({"rep": rep, "scores": parsed, "usage": usage})
            with open(out_path, "w") as f:
                json.dump(raw_log, f, indent=2)
        print(f"[reliability] ({i}/{len(jobs)}) {key} rep {rep + 1}/{N_REPEATS} done")

print(f"[reliability] wrote {out_path}")

print("\n=== Per-dimension score spread across 5 repeated judge calls (same response) ===")
for key in TEST_CASES:
    print(f"\n{key}:")
    for dim in DIMENSIONS:
        vals = results[key][dim]
        spread = max(vals) - min(vals)
        sd = statistics.pstdev(vals)
        print(f"  {dim:32s} scores={vals}  range={spread}  stdev={sd:.2f}")

print("\n=== Token usage per judge call ===")
avg_prompt = statistics.mean(u["prompt_tokens"] for u in usage_totals)
avg_completion = statistics.mean(u["completion_tokens"] for u in usage_totals)
avg_total = statistics.mean(u["total_tokens"] for u in usage_totals)
print(f"avg prompt_tokens: {avg_prompt:.0f}")
print(f"avg completion_tokens: {avg_completion:.0f}")
print(f"avg total_tokens: {avg_total:.0f}")
print(f"n calls: {len(usage_totals)}")
