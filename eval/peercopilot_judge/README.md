# PeerCoPilot LLM-as-judge diagnostic run

Implements `protocol.md` in this folder. Not evidence — a debugging/effect-size pass
before the Friday pilot.

## Setup

Needs `OPENAI_API_KEY` set (same as the main backend — `backend/.env` is picked up if
you run from a shell that's sourced it, or export it directly). Run everything from the
**repo root**.

## Files

- `protocol.md` — the study protocol (scenarios, rubrics, output schema).
- `scenarios.py` — M1-M3 medium scenarios and S1-S6 stress probes, encoded from the protocol.
- `arms.py` — response generation for the three arms:
  - **A** = PeerCoPilot (`backend.app.submodules.construct_response(version="new")`, full RAG + tools)
  - **B** = generic LLM + web search tool only (minimal system prompt, per protocol section 1)
  - **C** = generic LLM, no tools (same minimal system prompt)
- `judge.py` — pairwise LLM-as-judge (Rubric A: peer values, Rubric B: generic helpfulness).
  Judge model is `gpt-5-chat` (same family used for the responses).
- `confounds.py` — word count / directive-vs-optional-language ratio, computed directly
  (never asked of the judge).
- `run_experiment.py` — Step 1: generate all arm responses, write `output/raw_responses.json`.
- `run_judge.py` — Step 2: run pairwise judging over `raw_responses.json`, write
  `output/judge_scores.csv` and `output/judge_resources.csv`.

## Running

```bash
# Step 1 — generate responses (3 medium scenarios x 4 turns + 6 stress probes, x3 arms)
python -m eval.peercopilot_judge.run_experiment

# Step 2 — smoke test the judge first (cheap: 1 repeat, one rubric, first 2 units)
python -m eval.peercopilot_judge.run_judge --repeats 1 --rubrics A --limit 2

# Step 2 — full run (protocol default: both rubrics, 3 repeats, both orders, all 3 pairings)
python -m eval.peercopilot_judge.run_judge
```

## Cost note

The full judge run is the expensive step: 18 comparison units (12 medium-scenario turns +
6 stress probes) x 3 pairings (A-B, B-C, A-C) x 2 orders x 2 rubrics x N repeats judge calls.
At the protocol's default of 3 repeats that's ~648 `gpt-5-chat` judge calls, on top of the
response-generation calls in Step 1. Use `--limit` / `--repeats` on `run_judge.py` to control
spend before committing to a full run.

## What's not yet automated

- **Dimension 5 (resource verification)** is extraction only — `judge_resources.csv` needs a
  human pass to fill in `verified_exists` / `verified_serves_county` / `verified_eligibility` /
  `verified_contact` per protocol section 4.
- **2-3 judge models**: protocol section 7 recommends multiple judge models; this harness
  currently wires up one (`gpt-5-chat`). Swapping `JUDGE_MODEL` in `judge.py` or adding a
  second call per unit is a small follow-up once the single-judge run looks sane.
- **Pre-registration**: protocol section "Before you start" — write down and timestamp your
  prediction for the human study before running Step 1. Not something this code can do for you.
