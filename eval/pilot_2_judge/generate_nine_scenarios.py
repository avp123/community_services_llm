"""
Generate Version A / Version B responses for all 9 scenarios in
nine_scenarios.py (M1-M3 first turn + S1-S6 stress probes).

- Version A: real PeerCoPilot (backend.app.submodules.construct_response,
  version="new") via eval.peercopilot_judge.arms.run_arm_a -- full RAG + tools,
  exactly as run in production, now using the updated default system prompt
  in backend/app/submodules.py (get_default_peer_copilot_system_prompt). Requires
  the full backend stack (psycopg, sentence-transformers, faiss, spacy, ...);
  run this from an environment that has backend/requirements.txt installed
  (the "feedback" conda env has it) and with backend/.env's DB/API vars
  exported into the shell.
- Version B: generic LLM + web search, via eval.peercopilot_judge.arms.run_arm_b
  (the vanilla baseline system prompt).

Calls are parallelized (ThreadPoolExecutor, matching
eval/quality_variants/generate_real_systems.py) and results are written to
disk incrementally as they complete, so a partial run still leaves usable
output and a rerun skips cells already present.

Usage (from repo root, in the feedback conda env, with backend/.env exported):
    python -m eval.pilot_2_judge.generate_nine_scenarios
    python -m eval.pilot_2_judge.generate_nine_scenarios --workers 18
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from eval.peercopilot_judge.arms import run_arm_a, run_arm_b
from eval.pilot_2_judge.nine_scenarios import NINE_SCENARIOS

_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)
_MAX_RETRIES = 6
_BASE_BACKOFF = 5.0

OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
OUT_PATH = os.path.join(OUT_DIR, "nine_scenarios_responses.json")

RUNNERS = {
    "A": lambda scenario, organization: run_arm_a([], scenario, organization),
    "B": lambda scenario, organization: run_arm_b([], scenario),
}


def _run_with_retry(tool: str, scenario: str, organization: str) -> str:
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            return RUNNERS[tool](scenario, organization)
        except _RETRYABLE as exc:
            last_exc = exc
        except APIStatusError as exc:
            if exc.status_code != 429:
                raise
            last_exc = exc
        sleep_for = _BASE_BACKOFF * (2 ** attempt)
        print(f"[retry] {type(last_exc).__name__}, sleeping {sleep_for:.0f}s")
        time.sleep(sleep_for)
    raise last_exc


def generate_one(item: dict, tool: str) -> dict:
    started = time.time()
    response = _run_with_retry(tool, item["scenario"], item["organization"])
    return {
        "scenario_id": item["id"],
        "tool": tool,
        "scenario": item["scenario"],
        "response": response,
        "elapsed_seconds": round(time.time() - started, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8, help="Concurrent generations.")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY_AZURE") or not os.environ.get("OPENAI_AZURE_ENDPOINT"):
        print("OPENAI_API_KEY_AZURE / OPENAI_AZURE_ENDPOINT not set (source backend/.env).", file=sys.stderr)
        sys.exit(1)

    from backend.app.submodules import get_rag_assets
    print("[warmup] loading RAG assets for PeerCoPilot (Arm A)...")
    started_warmup = time.time()
    get_rag_assets()
    print(f"[warmup] done in {time.time() - started_warmup:.1f}s")

    existing = {}
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            for r in json.load(f):
                existing[(r["scenario_id"], r["tool"])] = r

    jobs = [
        (item, tool)
        for item in NINE_SCENARIOS
        for tool in ("A", "B")
        if (item["id"], tool) not in existing
    ]
    skipped = len(NINE_SCENARIOS) * 2 - len(jobs)
    print(f"Generating {len(jobs)} responses ({skipped} already present, skipped) with {args.workers} workers...")

    lock = threading.Lock()
    started = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(generate_one, item, tool): (item["id"], tool) for item, tool in jobs}
        for fut in as_completed(futures):
            scenario_id, tool = futures[fut]
            try:
                result = fut.result()
                with lock:
                    existing[(scenario_id, tool)] = result
                    done += 1
                    ordered = sorted(existing.values(), key=lambda r: (r["scenario_id"], r["tool"]))
                    with open(OUT_PATH, "w") as f:
                        json.dump(ordered, f, indent=2)
                print(f"[{done}/{len(jobs)}] scenario {scenario_id} tool {tool} done ({result['elapsed_seconds']}s)")
            except Exception as exc:
                print(f"[ERROR] scenario {scenario_id} tool {tool} failed: {exc}")

    elapsed = time.time() - started
    total_expected = len(NINE_SCENARIOS) * 2
    print(f"\nDone in {elapsed:.1f}s (this run filled {done}/{len(jobs)} gaps; "
          f"{len(existing)}/{total_expected} total now present). Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
