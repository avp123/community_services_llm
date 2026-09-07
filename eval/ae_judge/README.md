# ae_judge

Treatment-vs-control evaluation for the PeerCoPilot system prompt, plus the three
judges used to score it.

**Treatment** = prompt F3, frozen 2026-09-06 as production Version A
(`backend/app/submodules.py::get_default_peer_copilot_system_prompt`, byte-identical to
`debugging/data/version_f3.md`). **Control** = vanilla baseline B.

Full findings, including how the treatment prompt was derived from the CSPNJ pilot
transcripts, are in `FINDINGS.md`.

## Layout

| file | what it is |
|---|---|
| `judges.py` | J1/J2/J3 framings and the three elicitation modes. Self-contained. |
| `pairs.py` | Assembles every evaluated pair into `output/pairs.{json,md}`. |
| `run_judges.py` | Runs judges over pairs, writes `output/judge_results.json`. |
| `axis_pairs.py` | Generates the four single-axis contrast pairs. |
| `generate_responses.py` | Generates responses through the real pipeline (RAG + tools). |
| `scenarios.py`, `versions.py` | Scenario and prompt loading. |
| `prompts/` | The treatment, baseline and four axis-variant prompts, labelled, with a manifest. Copies — `debugging/data/` remains the source of truth. |
| `_archive/` | Superseded scripts and outputs from the development of the above. Nothing here is needed to reproduce current results. |

## The judges

- **J1 naive** — no rubric, "which is more helpful to a peer support specialist?" The
  default eval most papers use. Included as a foil.
- **J2 samhsa_ips** — primed with SAMHSA peer-worker core competencies and Intentional
  Peer Support principles. The principled, citable choice.
- **J3 pilot** — mined from the CSPNJ pilot transcripts. What these providers said they
  actually want from a tool.

Three modes: `binary` (pick one, both orderings x n samples), `pointwise` (each response
scored 1-5 alone), `graded` (1-5 preference, both orderings, mirroring pilot_2's human
instrument).

## The pairs

**Axis pairs (4).** One new scenario each, answered by F3 and by F3 with exactly ONE
property inverted; every other line of the prompt is byte-identical.

| axis | arm A (treatment) | arm B (variant) |
|---|---|---|
| direction | ordered recommendation | unordered options |
| locality | named NJ agencies + numbers | generic categories |
| role | practical logistics | purely supportive |
| language | borrowable sentences | named techniques |

**Scenario pairs (8).** F3 vs vanilla B on the study scenarios.

## Reproducing

```bash
conda run -n feedback bash -c 'set -a; source backend/.env; set +a; \
    python -m eval.ae_judge.generate_responses'      # responses (Azure + RAG + Brave)
conda run -n feedback python -m eval.ae_judge.axis_pairs    # axis contrast pairs
conda run -n feedback python -m eval.ae_judge.pairs         # assemble pairs.json/md
conda run -n feedback bash -c 'set -a; source backend/.env; set +a; \
    python -m eval.ae_judge.run_judges --family all'        # score them
```

## Read the results with these caveats

Measured properties of all three judges (`FINDINGS.md` has the numbers):

1. **They never tie.** 810/810 forced choices, including on two responses drawn from the
   *same* prompt. A single pair's verdict carries almost no information; only the pattern
   across pairs is interpretable.
2. **Position bias**: first-position preference on same-prompt pairs was J1 64%, J2 47%,
   J3 64%. Always run both orderings.
3. **Mode disagreement**: J1 and J2 reverse sign between binary and graded on the same
   responses. J3 is the only judge consistent across all three modes.
4. **Pointwise compresses**: J1 used only {4,5} and J2 only {3,4} across 18 responses.
5. **J3 shares a value model with the treatment prompt** (same author, same source), so
   its margin is not independent confirmation. J1 and J2 are independent by construction.
