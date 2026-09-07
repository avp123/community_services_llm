"""
Generate Version A/B/C/D/E responses for all 9 scenarios via the real
production pipeline (backend.app.submodules.construct_response, full RAG +
tools, gpt-5-chat), so the judge is validated on/scores real system output
rather than hand-written examples.

Parallelized (ThreadPoolExecutor) and written to disk incrementally so a
partial run leaves usable output and a rerun skips cells already present.

Usage (from repo root, in the `feedback` conda env, with backend/.env
exported):
    conda run -n feedback bash -c 'set -a; source backend/.env; set +a; \
        python -m eval.ae_judge.generate_responses'
"""
import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from backend.app.submodules import construct_response
from eval.ae_judge.scenarios import SCENARIOS
from eval.ae_judge.versions import ORGANIZATION, VERSION_PROMPTS

_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)
_MAX_RETRIES = 6
_BASE_BACKOFF = 5.0

OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
OUT_PATH = os.path.join(OUT_DIR, "responses.json")

_lock = threading.Lock()


def _collect_sse_stream(generator) -> str:
    parts = []
    for raw in generator:
        if not raw.startswith("data:"):
            continue
        token = raw[len("data: "):].rstrip("\n")
        if token.strip() == "[DONE]":
            continue
        parts.append(token.replace("<br/>", "\n"))
    return "".join(parts).strip()


def _run_version(version: str, situation: str) -> str:
    if version == "B":
        gen = construct_response(
            situation=situation,
            all_messages=[],
            model="gpt-5-chat",
            organization=ORGANIZATION,
            version="vanilla",
        )
    else:
        gen = construct_response(
            situation=situation,
            all_messages=[],
            model="gpt-5-chat",
            organization=ORGANIZATION,
            version="new",
            system_prompt_base=VERSION_PROMPTS[version],
        )
    return _collect_sse_stream(gen)


def _run_with_retry(version: str, situation: str) -> str:
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            return _run_version(version, situation)
        except _RETRYABLE as exc:
            last_exc = exc
        except APIStatusError as exc:
            if exc.status_code != 429:
                raise
            last_exc = exc
        sleep_for = _BASE_BACKOFF * (2 ** attempt)
        print(f"[generate] retrying {version} in {sleep_for:.0f}s (attempt {attempt + 1}): {last_exc}")
        import time
        time.sleep(sleep_for)
    raise last_exc


def _load_existing() -> dict:
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    results = _load_existing()

    jobs = []
    for scenario_id, situation in SCENARIOS.items():
        results.setdefault(scenario_id, {})
        for version in VERSION_PROMPTS:
            if version in results[scenario_id]:
                continue
            jobs.append((scenario_id, version, situation))

    print(f"[generate] {len(jobs)} cells to generate ({len(SCENARIOS)} scenarios x {len(VERSION_PROMPTS)} versions)")

    def _worker(job):
        scenario_id, version, situation = job
        text = _run_with_retry(version, situation)
        return scenario_id, version, text

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_worker, job): job for job in jobs}
        for future in as_completed(futures):
            scenario_id, version, situation = futures[future]
            try:
                scenario_id, version, text = future.result()
            except Exception as exc:
                print(f"[generate] FAILED {scenario_id}/{version}: {exc}")
                continue
            with _lock:
                results.setdefault(scenario_id, {})[version] = text
                with open(OUT_PATH, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2)
            completed += 1
            print(f"[generate] ({completed}/{len(jobs)}) done {scenario_id}/{version} ({len(text)} chars)")

    print(f"[generate] wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
