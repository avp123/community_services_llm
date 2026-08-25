"""
Generate the 36-response quality-variant calibration set: 9 scenarios x 4
response types, using gpt-5-mini directly (no PeerCoPilot, no tools, no RAG —
just the raw model against each prompt template in prompts.py).

Usage (from repo root):
    python -m eval.quality_variants.generate
    python -m eval.quality_variants.generate --workers 36 --reasoning-effort low

Writes:
    eval/quality_variants/output/responses.json   structured, one row per (scenario, type)
    eval/quality_variants/output/responses.md     human-readable dump, grouped by scenario
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from openai import OpenAI

from eval.quality_variants.prompts import build_prompt, TYPE_LABELS
from eval.quality_variants.scenarios import SCENARIOS

MODEL = "gpt-5-mini"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
JSON_PATH = OUTPUT_DIR / "responses.json"
MD_PATH = OUTPUT_DIR / "responses.md"

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def generate_one(scenario: dict, response_type: int, reasoning_effort: str = None) -> dict:
    prompt = build_prompt(response_type, scenario["scenario"], scenario["group"])
    kwargs = dict(model=MODEL, messages=[{"role": "user", "content": prompt}])
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort

    started = time.time()
    completion = _client.chat.completions.create(**kwargs)
    elapsed = time.time() - started
    text = (completion.choices[0].message.content or "").strip()

    return {
        "scenario_id": scenario["id"],
        "group": scenario["group"],
        "title": scenario["title"],
        "scenario": scenario["scenario"],
        "response_type": response_type,
        "type_label": TYPE_LABELS[response_type],
        "response": text,
        "elapsed_seconds": round(elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=36, help="All 36 are independent; default runs them all at once.")
    parser.add_argument(
        "--reasoning-effort", type=str, default=None, choices=["minimal", "low", "medium", "high"],
        help="Omit for the API default (higher quality, slower) — this is a small, one-off calibration "
        "set (36 calls total), so cost/latency isn't the binding constraint here.",
    )
    parser.add_argument(
        "--groups", type=str, default=None,
        help="Comma-separated groups to (re)generate, e.g. 'planning,peer_values'. Omit for all groups.",
    )
    parser.add_argument(
        "--types", type=str, default=None,
        help="Comma-separated response types to (re)generate, e.g. '4'. Omit for all types (1,2,3,4).",
    )
    args = parser.parse_args()

    groups_filter = set(args.groups.split(",")) if args.groups else None
    types_filter = set(int(t) for t in args.types.split(",")) if args.types else None

    jobs = [
        (s, t)
        for s in SCENARIOS
        for t in (1, 2, 3, 4)
        if (groups_filter is None or s["group"] in groups_filter)
        and (types_filter is None or t in types_filter)
    ]
    print(f"Generating {len(jobs)} responses" +
          (f" (groups={sorted(groups_filter)}, types={sorted(types_filter)})" if groups_filter or types_filter else
           f" ({len(SCENARIOS)} scenarios x 4 types)") +
          f" with {args.workers} workers...")

    results = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(generate_one, s, t, args.reasoning_effort): (s["id"], t) for s, t in jobs
        }
        done = 0
        for fut in as_completed(futures):
            sid, t = futures[fut]
            try:
                result = fut.result()
                results.append(result)
                done += 1
                print(f"[{done}/{len(jobs)}] scenario {sid} type {t} done ({result['elapsed_seconds']}s)")
            except Exception as exc:
                print(f"[ERROR] scenario {sid} type {t} failed: {exc}")

    elapsed = time.time() - started

    # Merge into any existing responses.json so a filtered re-run only touches
    # the targeted (scenario, type) rows, leaving the rest untouched.
    existing = {}
    if JSON_PATH.exists():
        with open(JSON_PATH) as f:
            for r in json.load(f):
                existing[(r["scenario_id"], r["response_type"])] = r
    for r in results:
        existing[(r["scenario_id"], r["response_type"])] = r
    results = sorted(existing.values(), key=lambda r: (r["scenario_id"], r["response_type"]))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(JSON_PATH, "w") as f:
        json.dump(results, f, indent=2)

    with open(MD_PATH, "w") as f:
        f.write("# Quality-variant calibration set\n\n")
        f.write(f"Model: `{MODEL}` (direct OpenAI, no PeerCoPilot, no tools)  \n")
        f.write(f"Generated: {len(results)}/{len(jobs)} responses in {elapsed:.1f}s\n\n")
        for s in SCENARIOS:
            f.write(f"---\n\n## Scenario {s['id']} — {s['title']} ({s['group']})\n\n")
            f.write(f"> {s['scenario']}\n\n")
            for r in [r for r in results if r["scenario_id"] == s["id"]]:
                f.write(f"### Type {r['response_type']} — {r['type_label']}\n\n")
                f.write(r["response"] + "\n\n")

    print(f"\nDone in {elapsed:.1f}s. Wrote {JSON_PATH} and {MD_PATH}")


if __name__ == "__main__":
    main()
