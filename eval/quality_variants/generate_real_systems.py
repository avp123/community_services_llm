"""
Generate real PeerCoPilot vs. baseline responses on the same 9 scenarios used
for the synthetic quality-variant calibration set (scenarios.py) — so the
real-system results can be situated against that established quality curve.

System A = PeerCoPilot (eval.peercopilot_judge.arms.run_arm_a: gpt-5-chat,
           full RAG + tools, production system prompt).
System B = generic + web search (eval.peercopilot_judge.arms.run_arm_b:
           gpt-5-chat, one-line prompt, web-search tool only).

Each (scenario, system) cell gets N independent single-turn generations (no
conversation history — every call is a fresh session, matching how these
scenarios are used in the calibration set).

Usage (from repo root, with backend/.env sourced — needs the Azure OpenAI /
RAG / resource-DB env vars since this calls the real PeerCoPilot pipeline):
    python -m eval.quality_variants.generate_real_systems
    python -m eval.quality_variants.generate_real_systems --repeats 3 --workers 18

Writes eval/quality_variants/output/real_system_responses.json
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)
_MAX_RETRIES = 6
_BASE_BACKOFF = 5.0

from eval.peercopilot_judge.arms import run_arm_a, run_arm_b
from eval.quality_variants.scenarios import SCENARIOS

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_PATH = OUTPUT_DIR / "real_system_responses.json"

SYSTEM_RUNNERS = {
    "A": lambda scenario_text: run_arm_a([], scenario_text, organization="cspnj"),
    "B": lambda scenario_text: run_arm_b([], scenario_text),
}
SYSTEM_LABELS = {"A": "PeerCoPilot", "B": "Generic + web search"}


def _run_with_retry(system: str, scenario_text: str) -> str:
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            return SYSTEM_RUNNERS[system](scenario_text)
        except _RETRYABLE as exc:
            last_exc = exc
            sleep_for = _BASE_BACKOFF * (2 ** attempt)
            print(f"[retry] {type(exc).__name__}, sleeping {sleep_for:.0f}s")
            time.sleep(sleep_for)
        except APIStatusError as exc:
            if exc.status_code == 429:
                last_exc = exc
                sleep_for = _BASE_BACKOFF * (2 ** attempt)
                print(f"[retry] 429, sleeping {sleep_for:.0f}s")
                time.sleep(sleep_for)
            else:
                raise
    raise last_exc


def generate_one(scenario: dict, system: str, repeat: int) -> dict:
    started = time.time()
    response_text = _run_with_retry(system, scenario["scenario"])
    elapsed = time.time() - started
    return {
        "scenario_id": scenario["id"],
        "group": scenario["group"],
        "title": scenario["title"],
        "scenario": scenario["scenario"],
        "system": system,
        "system_label": SYSTEM_LABELS[system],
        "repeat": repeat,
        "response": response_text,
        "elapsed_seconds": round(elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3, help="Independent generations per (scenario, system).")
    parser.add_argument(
        "--workers", type=int, default=18,
        help="Concurrent generations. PeerCoPilot's RAG warmup happens once on first call "
        "(cached per-process after that), so keep this modest on the first run.",
    )
    args = parser.parse_args()

    from backend.app.submodules import get_rag_assets
    print("[warmup] loading RAG assets for PeerCoPilot (Arm A)...")
    started_warmup = time.time()
    get_rag_assets()
    print(f"[warmup] done in {time.time() - started_warmup:.1f}s")

    existing = {}
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            for r in json.load(f):
                existing[(r["scenario_id"], r["system"], r["repeat"])] = r

    jobs = [
        (s, system, repeat)
        for s in SCENARIOS
        for system in ("A", "B")
        for repeat in range(1, args.repeats + 1)
        if (s["id"], system, repeat) not in existing
    ]
    skipped = len(SCENARIOS) * 2 * args.repeats - len(jobs)
    print(f"Generating {len(jobs)} responses ({skipped} already present, skipped) with {args.workers} workers...")

    results = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(generate_one, s, sysname, rep): (s["id"], sysname, rep) for s, sysname, rep in jobs}
        done = 0
        for fut in as_completed(futures):
            sid, sysname, rep = futures[fut]
            try:
                result = fut.result()
                results.append(result)
                done += 1
                print(f"[{done}/{len(jobs)}] scenario {sid} system {sysname} repeat {rep} done ({result['elapsed_seconds']}s)")
            except Exception as exc:
                print(f"[ERROR] scenario {sid} system {sysname} repeat {rep} failed: {exc}")

    elapsed = time.time() - started
    for r in results:
        existing[(r["scenario_id"], r["system"], r["repeat"])] = r
    results = sorted(existing.values(), key=lambda r: (r["scenario_id"], r["system"], r["repeat"]))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)

    total_expected = len(SCENARIOS) * 2 * args.repeats
    print(f"\nDone in {elapsed:.1f}s (this run filled {done}/{len(jobs)} gaps; "
          f"{len(results)}/{total_expected} total now present). Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
