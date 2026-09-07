"""
Four single-axis contrast pairs, for testing where judges and practitioners diverge.

Each tuple is (new scenario, treatment F3, F3 with exactly ONE property inverted).
Everything else in the prompt is byte-identical, so any difference in the two
responses is attributable to that axis.

  1 DIRECTION  F3 recommends an ordered next step | variant lays out unordered options
               Predicted: judges prefer options, practitioners prefer the recommendation.
               (J1/J2 penalised "prescriptive"; the pilot ranked options-only last.)
  2 LOCALITY   F3 names NJ agencies with numbers  | variant gives generic categories
               Predicted: judges prefer generic, practitioners prefer specific.
               (J1/J2 called NJ specifics "may not be broadly applicable"; the pilot
               called the agency numbers the single thing she most wants.)
  3 ROLE       F3 includes practical logistics    | variant stays purely supportive
               Least certain -- J2 called logistics "edging toward case-management",
               but pilots wanted the practical help while guarding the relationship.
               The most informative of the four.
  4 LANGUAGE   F3 gives borrowable sentences      | variant names techniques
               Predicted: judges tolerate labels, practitioners reject them
               ("those are the things that we learn from the textbook").

Usage:
    conda run -n feedback bash -c 'set -a; source backend/.env; set +a; \
        python -m eval.ae_judge.axis_pairs'
"""
import json
import os
import pathlib
from concurrent.futures import ThreadPoolExecutor

from backend.app.submodules import construct_response
from eval.ae_judge.versions import ORGANIZATION

_D = pathlib.Path(__file__).resolve().parents[2] / "debugging" / "data"
_OUT = pathlib.Path(__file__).parent / "output"

AXES = {
    "direction": ("axis_direction", "version_f3_v1_options.md",
                  "recommends an ordered next step", "lays out unordered options"),
    "locality": ("axis_locality", "version_f3_v2_generic.md",
                 "names NJ agencies with numbers", "gives generic categories"),
    "role": ("axis_role", "version_f3_v3_supportive.md",
             "includes practical logistics", "stays purely supportive"),
    "language": ("axis_language", "version_f3_v4_techniques.md",
                 "gives borrowable sentences", "names techniques"),
}


def _load(name):
    return (_D / name).read_text().strip().format(organization=ORGANIZATION)


def _gen(scenario_text, prompt_text):
    gen = construct_response(situation=scenario_text, all_messages=[], model="gpt-5-chat",
                             organization=ORGANIZATION, version="new",
                             system_prompt_base=prompt_text)
    parts = []
    for raw in gen:
        if raw.startswith("data:"):
            t = raw[5:].rstrip("\n")
            if t.strip() != "[DONE]":
                parts.append(t.replace("<br/>", "\n"))
    return "".join(parts).strip()


def main():
    f3 = _load("version_f3.md")
    jobs = []
    for axis, (scen_file, var_file, _, _) in AXES.items():
        scen = (_D / f"{scen_file}.md").read_text().strip()
        jobs.append((axis, "A_treatment", scen, f3))
        jobs.append((axis, "B_variant", scen, _load(var_file)))

    # Warm the embedding model in the main thread (it races across threads).
    _gen(jobs[0][2], jobs[0][3])
    print(f"[axes] generating {len(jobs)} responses")

    out = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for (axis, arm, scen, _), text in zip(jobs, pool.map(lambda j: _gen(j[2], j[3]), jobs)):
            out.setdefault(axis, {"scenario": scen})[arm] = text
            print(f"[axes] {axis}/{arm} ({len(text.split())} words)")

    _OUT.mkdir(exist_ok=True)
    (_OUT / "axis_pairs.json").write_text(json.dumps(out, indent=2))

    md = ["# Four single-axis contrast pairs\n",
          "Arm A = treatment (F3, production Version A). Arm B = F3 with exactly one\n"
          "property inverted; every other line of the prompt is identical.\n"]
    for axis, (_, var_file, pole_a, pole_b) in AXES.items():
        b = out[axis]
        md += [f"\n\n{'='*90}\n## Axis: {axis.upper()}\n",
               f"**A (treatment)** {pole_a}  |  **B (variant)** {pole_b}",
               f"  \n*variant prompt:* `debugging/data/{var_file}`\n",
               f"\n**Scenario:** {b['scenario']}\n",
               f"\n### A — TREATMENT ({len(b['A_treatment'].split())} words)\n\n{b['A_treatment']}\n",
               f"\n### B — VARIANT ({len(b['B_variant'].split())} words)\n\n{b['B_variant']}\n"]
    p = _OUT / "axis_pairs.md"
    p.write_text("\n".join(md))
    print(f"\nwrote {p} ({p.stat().st_size // 1024} KB) and axis_pairs.json")


if __name__ == "__main__":
    main()
