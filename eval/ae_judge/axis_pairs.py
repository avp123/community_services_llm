"""
Four single-axis contrast pairs, for testing where judges and practitioners diverge.

Each tuple is (scenario, treatment F3, F3 with exactly ONE property inverted).
Everything else in the prompt is meant to be identical, so any difference in the
two responses is attributable to that axis.

  1 AUTONOMY              F3 gives ordered moves        | variant gives unordered options
                          and says what to do first     | and refuses to rank them
  2 INFORMATION_VALUE     F3 names NJ agencies/numbers  | variant gives categories only
  3 PRACTICAL_USABILITY   F3 gives borrowable sentences | variant gives approaches only
  4 ROLE_COMPLEMENTARITY  F3 helps across the board     | variant does info/search only
                                                        | and leaves relational work alone

Prompts and scenarios are read from `prompts/` (the axis set was rewritten there on
2026-09-09; `debugging/data/` still holds the superseded direction/locality/role/
language set, archived as `_archive/axis_pairs_old_axes.*`).

Resumable: cells already present in output/axis_pairs.json are skipped, so the
arm-A responses carried over from the 2026-09-06 run are not regenerated. Delete
the file (or an individual arm) to force a fresh generation.

Usage:
    conda run -n feedback bash -c 'set -a; source backend/.env; set +a; \
        python -m eval.ae_judge.axis_pairs'
"""
import json
import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor

from backend.app.submodules import construct_response, get_rag_assets
from eval.ae_judge.versions import ORGANIZATION

_P = pathlib.Path(__file__).parent / "prompts"
_OUT = pathlib.Path(__file__).parent / "output"

# axis -> (variant prompt file, arm-A pole, arm-B pole)
AXES = {
    "autonomy": ("variant_autonomy.md",
                 "ordered moves, says what to do first",
                 "unordered options, declines to rank"),
    "information_value": ("variant_information_value.md",
                          "names NJ agencies with numbers",
                          "gives service categories only"),
    "practical_usability": ("variant_practical_usability.md",
                            "gives borrowable sentences",
                            "gives approaches, no wording"),
    "role_complementarity": ("variant_role_complementarity.md",
                             "helps across the board",
                             "info/search only, leaves relational work to provider"),
}

_lock = threading.Lock()


def _load(name):
    return (_P / name).read_text().strip().format(organization=ORGANIZATION)


def _gen(scenario_text, prompt_text):
    """One response through the real production pipeline. Returns (text, usage)."""
    # Must be pre-seeded: accumulate_usage() guards with `if not usage_accumulator`,
    # so an empty dict is falsy and every usage record is silently dropped.
    usage = {"total": 0}
    tool_calls = []
    gen = construct_response(situation=scenario_text, all_messages=[], model="gpt-5-chat",
                             organization=ORGANIZATION, version="new",
                             system_prompt_base=prompt_text,
                             tool_call_names_out=tool_calls,
                             usage_accumulator=usage)
    parts = []
    for raw in gen:
        if raw.startswith("data:"):
            t = raw[5:].rstrip("\n")
            if t.strip() != "[DONE]":
                parts.append(t.replace("<br/>", "\n"))
    return "".join(parts).strip(), {"total_tokens": usage.get("total", 0),
                                    "tool_calls": tool_calls}


def _write(out):
    _OUT.mkdir(exist_ok=True)
    (_OUT / "axis_pairs.json").write_text(json.dumps(out, indent=2))


def main():
    _OUT.mkdir(exist_ok=True)
    path = _OUT / "axis_pairs.json"
    out = json.loads(path.read_text()) if path.exists() else {}

    jobs = []
    for axis, (var_file, _, _) in AXES.items():
        scen = (_P / f"scenario_axis_{axis}.md").read_text().strip()
        cell = out.setdefault(axis, {})
        cell["scenario"] = scen
        if "A_treatment" not in cell:
            jobs.append((axis, "A_treatment", scen, _load("treatment.md")))
        if "B_variant" not in cell:
            jobs.append((axis, "B_variant", scen, _load(var_file)))

    print(f"[axes] {len(jobs)} to generate, "
          f"{sum(1 for a in AXES for k in ('A_treatment', 'B_variant') if k in out[a])} reused")
    if not jobs:
        print("[axes] nothing to do")
    else:
        # Warm the RAG/embedding assets in the main thread (they race across threads).
        get_rag_assets()

        def _worker(job):
            axis, arm, scen, prompt = job
            text, usage = _gen(scen, prompt)
            return axis, arm, text, usage

        with ThreadPoolExecutor(max_workers=4) as pool:
            for axis, arm, text, usage in pool.map(_worker, jobs):
                with _lock:
                    out[axis][arm] = text
                    out[axis].setdefault("_usage", {})[arm] = usage
                    _write(out)
                print(f"[axes] {axis}/{arm}: {len(text.split())} words, "
                      f"{usage['total_tokens']} tokens, {len(usage['tool_calls'])} tool calls")

    _write(out)

    md = ["# Four single-axis contrast pairs\n",
          "Arm A = treatment (F3, production Version A). Arm B = F3 with one property\n"
          "inverted. Arm A is carried over from the 2026-09-06 run where the scenario and\n"
          "the F3 prompt are byte-identical; arm B was generated 2026-09-09.\n"]
    for axis, (var_file, pole_a, pole_b) in AXES.items():
        b = out[axis]
        md += [f"\n\n{'='*90}\n## Axis: {axis.upper()}\n",
               f"**A (treatment)** {pole_a}  |  **B (variant)** {pole_b}",
               f"  \n*variant prompt:* `eval/ae_judge/prompts/{var_file}`\n",
               f"\n**Scenario:** {b['scenario']}\n",
               f"\n### A — TREATMENT ({len(b['A_treatment'].split())} words)\n\n{b['A_treatment']}\n",
               f"\n### B — VARIANT ({len(b['B_variant'].split())} words)\n\n{b['B_variant']}\n"]
    p = _OUT / "axis_pairs.md"
    p.write_text("\n".join(md))
    print(f"\nwrote {p} ({p.stat().st_size // 1024} KB) and axis_pairs.json")


if __name__ == "__main__":
    main()
