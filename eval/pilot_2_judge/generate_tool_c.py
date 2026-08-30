"""
Generate Tool C responses to the same 4 pilot-2 scenarios used for arms A/B
(eval/pilot_2_judge/data.py), using the candidate system prompt in
system_prompt_c.py.

Uses the same Azure "gpt-5-chat" deployment the production app uses for arms
A/B (backend/app/utils.py / submodules.py), via OPENAI_API_KEY_AZURE +
OPENAI_AZURE_ENDPOINT from backend/.env -- so Tool C differs from A/B only in
system prompt, not underlying model.

Usage:
    python -m eval.pilot_2_judge.generate_tool_c
"""
import json
import os
import sys

from dotenv import load_dotenv
from openai import AzureOpenAI

from eval.pilot_2_judge.data import CONVERSATIONS
from eval.pilot_2_judge.system_prompt_c import SYSTEM_PROMPT_C

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "backend", ".env"))

GENERATION_MODEL = "gpt-5-chat"
_client = AzureOpenAI(
    api_key=os.environ.get("OPENAI_API_KEY_AZURE"),
    azure_endpoint=os.environ.get("OPENAI_AZURE_ENDPOINT"),
    api_version="2024-12-01-preview",
)


def generate_response(scenario: str) -> str:
    completion = _client.chat.completions.create(
        model=GENERATION_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_C},
            {"role": "user", "content": scenario},
        ],
    )
    return completion.choices[0].message.content


def main():
    if not os.environ.get("OPENAI_API_KEY_AZURE") or not os.environ.get("OPENAI_AZURE_ENDPOINT"):
        print("OPENAI_API_KEY_AZURE / OPENAI_AZURE_ENDPOINT not set (check backend/.env).", file=sys.stderr)
        sys.exit(1)

    results = []
    for convo in CONVERSATIONS:
        print(f"[generate] Tool C response for {convo['conversation_id']} (turn {convo['order_index']})...")
        response = generate_response(convo["scenario"])
        results.append({
            "conversation_id": convo["conversation_id"] + "_C",
            "source_conversation_id": convo["conversation_id"],
            "order_index": convo["order_index"],
            "tool": "C",
            "scenario": convo["scenario"],
            "response": response,
            "generation_model": GENERATION_MODEL,
        })

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "tool_c_responses.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[generate] wrote {out_path}")


if __name__ == "__main__":
    main()
