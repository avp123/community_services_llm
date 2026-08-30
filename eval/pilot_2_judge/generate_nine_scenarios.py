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

Usage (from repo root, in the feedback conda env, with backend/.env exported):
    python -m eval.pilot_2_judge.generate_nine_scenarios
"""
import json
import os
import sys

from eval.peercopilot_judge.arms import run_arm_a, run_arm_b
from eval.pilot_2_judge.nine_scenarios import NINE_SCENARIOS


def main():
    if not os.environ.get("OPENAI_API_KEY_AZURE") or not os.environ.get("OPENAI_AZURE_ENDPOINT"):
        print("OPENAI_API_KEY_AZURE / OPENAI_AZURE_ENDPOINT not set (source backend/.env).", file=sys.stderr)
        sys.exit(1)

    results = []
    for item in NINE_SCENARIOS:
        scenario_id = item["id"]
        scenario = item["scenario"]
        organization = item["organization"]

        print(f"[generate] {scenario_id} -- Version A...")
        response_a = run_arm_a([], scenario, organization)

        print(f"[generate] {scenario_id} -- Version B...")
        response_b = run_arm_b([], scenario)

        for tool, response in (("A", response_a), ("B", response_b)):
            results.append({
                "scenario_id": scenario_id,
                "tool": tool,
                "scenario": scenario,
                "response": response,
            })

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "nine_scenarios_responses.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[generate] wrote {out_path} ({len(results)} responses)")


if __name__ == "__main__":
    main()
