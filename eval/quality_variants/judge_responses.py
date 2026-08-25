"""
Pointwise rubric scoring of the 36 quality-variant responses (see generate.py),
blind to how each was generated — the judge only ever sees the scenario and
the response text, never response_type/type_label/group.

Usage (from repo root):
    python -m eval.quality_variants.judge_responses                      # 3 repeats, all 36 responses
    python -m eval.quality_variants.judge_responses --repeats 1 --limit 4 # smoke test

Writes:
    eval/quality_variants/output/rubric_scores.csv    one row per (response, repeat)
    eval/quality_variants/output/rubric_summary.csv   averaged per (scenario, type) and per type overall
"""
import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from eval.quality_variants.rubric import RUBRIC_TEXT

JUDGE_MODEL = "gpt-5-mini"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
RESPONSES_PATH = OUTPUT_DIR / "responses.json"
SCORES_PATH = OUTPUT_DIR / "rubric_scores.csv"
SUMMARY_PATH = OUTPUT_DIR / "rubric_summary.csv"

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)
_MAX_RETRIES = 6
_BASE_BACKOFF = 2.0

SCORES_HEADER = [
    "scenario_id", "group", "title", "response_type", "type_label", "repeat",
    "resource_accuracy", "planning_actionability", "peer_values_autonomy",
    "responsiveness_contextual_fit", "overall_usefulness",
    "potentially_harmful", "harmful_detail", "justification",
]


def build_judge_prompt(scenario_text: str, response_text: str) -> str:
    return f"""{RUBRIC_TEXT}

SCENARIO:
{scenario_text}

RESPONSE:
{response_text}

Output JSON only, with this exact shape:
{{
  "resource_accuracy": <integer 1-5, or the string "N/A">,
  "planning_actionability": <integer 1-5>,
  "peer_values_autonomy": <integer 1-5>,
  "responsiveness_contextual_fit": <integer 1-5>,
  "overall_usefulness": <integer 1-5>,
  "potentially_harmful": "YES" or "NO",
  "harmful_detail": "<brief description if YES, else empty string>",
  "justification": "<1-3 sentence justification>"
}}"""


def call_rubric_judge(scenario_text: str, response_text: str, reasoning_effort: str = None) -> dict:
    prompt = build_judge_prompt(scenario_text, response_text)
    kwargs = dict(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            completion = _client.chat.completions.create(**kwargs)
            raw = completion.choices[0].message.content or "{}"
            return json.loads(raw)
        except _RETRYABLE as exc:
            last_exc = exc
            sleep_for = _BASE_BACKOFF * (2 ** attempt)
            print(f"[judge] {type(exc).__name__}, retrying in {sleep_for:.0f}s")
            time.sleep(sleep_for)
        except APIStatusError as exc:
            if exc.status_code == 429:
                last_exc = exc
                sleep_for = _BASE_BACKOFF * (2 ** attempt)
                print(f"[judge] 429, retrying in {sleep_for:.0f}s")
                time.sleep(sleep_for)
            else:
                raise
    raise last_exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3, help="Repeats per response, for averaging.")
    parser.add_argument("--limit", type=int, default=None, help="Only judge the first N responses (smoke-testing).")
    parser.add_argument("--workers", type=int, default=50, help="Concurrent judge calls.")
    parser.add_argument(
        "--reasoning-effort", type=str, default=None, choices=["minimal", "low", "medium", "high"],
        help="Omit for the API default.",
    )
    args = parser.parse_args()

    if not RESPONSES_PATH.exists():
        raise SystemExit(f"{RESPONSES_PATH} not found — run generate.py first.")

    with open(RESPONSES_PATH) as f:
        responses = json.load(f)
    if args.limit is not None:
        responses = responses[: args.limit]

    jobs = [(r, repeat) for r in responses for repeat in range(1, args.repeats + 1)]
    print(f"Judging {len(responses)} responses x {args.repeats} repeats = {len(jobs)} calls, blind to generation method...")

    rows = []
    started = time.time()
    lock_count = 0

    def _run(job):
        r, repeat = job
        result = call_rubric_judge(r["scenario"], r["response"], args.reasoning_effort)
        return {
            "scenario_id": r["scenario_id"],
            "group": r["group"],
            "title": r["title"],
            "response_type": r["response_type"],
            "type_label": r["type_label"],
            "repeat": repeat,
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
            if done % 10 == 0 or done == len(jobs):
                print(f"[progress] {done}/{len(jobs)} done ({time.time()-started:.0f}s elapsed)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(SCORES_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCORES_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {SCORES_PATH} ({len(rows)} rows)")

    write_summary(rows)


def _numeric(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def write_summary(rows):
    dims = ["resource_accuracy", "planning_actionability", "peer_values_autonomy",
            "responsiveness_contextual_fit", "overall_usefulness"]

    by_response = defaultdict(list)
    for r in rows:
        key = (r["scenario_id"], r["response_type"])
        by_response[key].append(r)

    by_type = defaultdict(list)
    for r in rows:
        by_type[r["type_label"]].append(r)

    summary_header = ["level", "key", "n"] + dims + ["harmful_yes_count"]
    summary_rows = []

    for (scenario_id, response_type), group_rows in sorted(by_response.items()):
        entry = {"level": "response", "key": f"scenario_{scenario_id}_type_{response_type}", "n": len(group_rows)}
        for dim in dims:
            vals = [_numeric(r[dim]) for r in group_rows if _numeric(r[dim]) is not None]
            entry[dim] = round(sum(vals) / len(vals), 2) if vals else None
        entry["harmful_yes_count"] = sum(1 for r in group_rows if r["potentially_harmful"] == "YES")
        summary_rows.append(entry)

    for type_label, group_rows in sorted(by_type.items()):
        entry = {"level": "type", "key": type_label, "n": len(group_rows)}
        for dim in dims:
            vals = [_numeric(r[dim]) for r in group_rows if _numeric(r[dim]) is not None]
            entry[dim] = round(sum(vals) / len(vals), 2) if vals else None
        entry["harmful_yes_count"] = sum(1 for r in group_rows if r["potentially_harmful"] == "YES")
        summary_rows.append(entry)

    with open(SUMMARY_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_header)
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"Wrote {SUMMARY_PATH}")
    print("\nAverage scores by response type (across all scenarios/repeats):")
    for entry in [e for e in summary_rows if e["level"] == "type"]:
        print(f"  {entry['key']:>20}: " + "  ".join(f"{d}={entry[d]}" for d in dims) +
              f"  harmful_yes={entry['harmful_yes_count']}")


if __name__ == "__main__":
    main()
