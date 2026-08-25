"""
Step 1: generate responses from all three arms for every scenario/turn.

Each medium scenario is run as an independent conversation per arm — "no
cross-contamination" per protocol.md section 2: arm A's conversation history
never sees arm B's or C's responses, and vice versa.

Usage (from repo root):
    python -m eval.peercopilot_judge.run_experiment
    python -m eval.peercopilot_judge.run_experiment --medium-limit 1 --turn-limit 1 --stress-limit 1
    python -m eval.peercopilot_judge.run_experiment --workers 4

Writes eval/peercopilot_judge/output/raw_responses.json incrementally (one
(scenario, arm) unit at a time), so you can inspect progress mid-run and a
crash doesn't lose completed work.
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `backend.*` imports

from eval.peercopilot_judge.arms import ARM_RUNNERS
from eval.peercopilot_judge.scenarios import ARMS, MEDIUM_SCENARIOS, STRESS_PROBES

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_PATH = OUTPUT_DIR / "raw_responses.json"

_write_lock = threading.Lock()


def _warm_up_rag():
    """
    Arm A's first call pays for loading the embedding model + FAISS indices
    (backend/app/submodules.py:get_rag_assets, cached globally after that).
    Pay that cost up front, with visible timing, instead of hiding it inside
    the first scored comparison.
    """
    from backend.app.submodules import get_rag_assets

    print("[warmup] loading RAG assets (embedding model + resource indices)...")
    started = time.time()
    get_rag_assets()
    print(f"[warmup] done in {time.time() - started:.1f}s — reused for every Arm A call from here on.")


def run_medium_scenario_arm(scenario: dict, arm: str) -> dict:
    """Run all turns of one scenario through one arm, as a single conversation."""
    runner = ARM_RUNNERS[arm]
    history = []
    turn_outputs = []
    for i, turn_text in enumerate(scenario["turns"], 1):
        started = time.time()
        response_text = runner(history, turn_text, scenario["organization"])
        elapsed = time.time() - started
        print(f"[{scenario['id']}] arm {arm} turn {i}/{len(scenario['turns'])} done ({elapsed:.1f}s)")
        turn_outputs.append({"user_turn": turn_text, "response": response_text})
        history.append({"role": "user", "content": turn_text})
        history.append({"role": "assistant", "content": response_text})
    return {"scenario_id": scenario["id"], "arm": arm, "turns": turn_outputs}


def run_stress_probe_arm(probe: dict, arm: str) -> dict:
    runner = ARM_RUNNERS[arm]
    started = time.time()
    response_text = runner([], probe["probe"], probe["organization"])
    print(f"[{probe['id']}] arm {arm} done ({time.time() - started:.1f}s)")
    return {"probe_id": probe["id"], "arm": arm, "response": response_text}


class IncrementalWriter:
    """Accumulates results and rewrites the JSON file after every completed unit."""

    def __init__(self, medium_scenarios, stress_probes, started_at):
        self.started_at = started_at
        self.medium = {s["id"]: {"title": s["title"], "arms": {}} for s in medium_scenarios}
        self.stress = {p["id"]: {"probe": p["probe"], "tests": p["tests"], "arms": {}} for p in stress_probes}
        self.done = 0
        self.total = len(medium_scenarios) * len(ARMS) + len(stress_probes) * len(ARMS)

    def record_medium(self, scenario_id: str, arm: str, turn_outputs: list):
        with _write_lock:
            self.medium[scenario_id]["arms"][arm] = turn_outputs
            self.done += 1
            self._flush()

    def record_stress(self, probe_id: str, arm: str, response_text: str):
        with _write_lock:
            self.stress[probe_id]["arms"][arm] = response_text
            self.done += 1
            self._flush()

    def _flush(self):
        payload = {
            "started_at": self.started_at,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "progress": f"{self.done}/{self.total}",
            "medium_scenarios": [
                {"id": sid, "title": v["title"], "arms": v["arms"]} for sid, v in self.medium.items()
            ],
            "stress_probes": [
                {"id": pid, "probe": v["probe"], "tests": v["tests"], "arms": v["arms"]}
                for pid, v in self.stress.items()
            ],
        }
        with open(OUTPUT_PATH, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"[progress] {self.done}/{self.total} (arm) units complete — checkpoint written")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--medium-limit", type=int, default=None, help="Only run the first N medium scenarios.")
    parser.add_argument("--stress-limit", type=int, default=None, help="Only run the first N stress probes.")
    parser.add_argument("--turn-limit", type=int, default=None, help="Only run the first N turns of each medium scenario.")
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Concurrent (scenario/probe, arm) units in flight. Each unit's own turns still run "
        "sequentially (they share conversation history). Default 4 — raise/lower to match your rate limits.",
    )
    args = parser.parse_args()

    medium_scenarios = MEDIUM_SCENARIOS[: args.medium_limit] if args.medium_limit else MEDIUM_SCENARIOS
    stress_probes = STRESS_PROBES[: args.stress_limit] if args.stress_limit else STRESS_PROBES
    if args.turn_limit:
        medium_scenarios = [{**s, "turns": s["turns"][: args.turn_limit]} for s in medium_scenarios]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    needs_arm_a = any(True for _ in medium_scenarios) or any(True for _ in stress_probes)
    if needs_arm_a:
        _warm_up_rag()

    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    writer = IncrementalWriter(medium_scenarios, stress_probes, started_at)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for scenario in medium_scenarios:
            for arm in ARMS:
                fut = pool.submit(run_medium_scenario_arm, scenario, arm)
                futures[fut] = ("medium", scenario["id"], arm)
        for probe in stress_probes:
            for arm in ARMS:
                fut = pool.submit(run_stress_probe_arm, probe, arm)
                futures[fut] = ("stress", probe["id"], arm)

        for fut in as_completed(futures):
            kind, unit_id, arm = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:
                print(f"[ERROR] {kind} {unit_id} arm {arm} failed: {exc}")
                continue
            if kind == "medium":
                writer.record_medium(unit_id, arm, result["turns"])
            else:
                writer.record_stress(unit_id, arm, result["response"])

    print(f"\nWrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
