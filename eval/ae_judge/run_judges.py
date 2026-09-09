"""
Run J1/J2/J3 over pairs, in all three elicitation modes.

All three modes score the same five dimensions (judges.DIMENSIONS): information_value,
practical_usability, role_complementarity, autonomy, overall. The first four are the
four contrast axes, so an axis pair can be read against the dimension it manipulates.

  binary     per dimension, both orderings x --samples, majority per ordering;
             disagreement between orderings = tie
  pointwise  Likert 1-5 agreement per dimension, each arm rated independently
  graded     1-5 preference per dimension, both orderings, swapped reverse-coded
             (6 - score) so 1 = A much better, 3 = no preference, 5 = B much better

Usage:
    conda run -n feedback bash -c 'set -a; source backend/.env; set +a; \
        python -m eval.ae_judge.run_judges --family axis'
    ... --pairs axis_autonomy,s8_unhappy_treatment
    ... --family all
"""
import argparse
import json
import os
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from eval.ae_judge.judges import DEPLOYMENTS, DIMS, FRAMINGS, build_prompt, call
from eval.ae_judge.pairs import load

_OUT = os.path.join(os.path.dirname(__file__), "output")
RES = os.path.join(_OUT, "judge_results.json")
JUDGES = list(FRAMINGS)
# Bumped when the judge output schema changes; cells written under an older schema are
# regenerated rather than silently mixed with new ones.
SCHEMA = "dims-v1"
_lock = threading.Lock()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="axis", choices=["axis", "scenario", "all"])
    ap.add_argument("--pairs", default=None, help="comma-separated pair names")
    ap.add_argument("--samples", type=int, default=3, help="binary samples per ordering")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--model", default="gpt5", choices=list(DEPLOYMENTS),
                    help="judge model tag; results are stored per model")
    args = ap.parse_args()
    tag, deployment = args.model, DEPLOYMENTS[args.model]

    pairs = load()
    names = ([n for n in args.pairs.split(",")] if args.pairs else
             [n for n, p in pairs.items() if args.family == "all" or p["family"] == args.family])

    results = json.loads(open(RES).read()) if os.path.exists(RES) else {}
    jobs = []
    for n in names:
        for j in JUDGES:
            for mode in ("binary", "pointwise", "graded"):
                cell = results.get(f"{n}|{j}|{mode}|{tag}")
                if not cell or cell.get("schema") != SCHEMA:
                    jobs.append((n, j, mode))
    ncalls = sum({"binary": args.samples * 2, "pointwise": 2, "graded": 2}[m] for _, _, m in jobs)
    print(f"[judges] model={tag} ({deployment}), {len(names)} pairs, "
          f"{len(jobs)} cells, {ncalls} calls")

    def _score(d, dim, default=3):
        """Pull one dimension's 1-5 score out of a judge reply, tolerating junk."""
        try:
            return int(d.get(dim, {}).get("score", default))
        except (TypeError, ValueError, AttributeError):
            return default

    def _winner(d, dim):
        try:
            return d.get(dim, {}).get("winner")
        except AttributeError:
            return None

    def _reason(d, dim):
        try:
            return d.get(dim, {}).get("reason", "")
        except AttributeError:
            return ""

    def work(job):
        name, j, mode = job
        p = pairs[name]
        scen, A, B = p["scenario"], p["A"], p["B"]
        base = {"mode": mode, "judge": j, "pair": name, "schema": SCHEMA,
                "model": tag, "deployment": deployment}
        if mode == "pointwise":
            out = {m: call(build_prompt(j, mode, scen, t), deployment) for m, t in (("A", A), ("B", B))}
            return f"{name}|{j}|{mode}|{tag}", {**base, "dims": {
                d: {"A": _score(out["A"], d), "B": _score(out["B"], d),
                    "A_reason": _reason(out["A"], d), "B_reason": _reason(out["B"], d)}
                for d in DIMS}}
        if mode == "graded":
            f = call(build_prompt(j, mode, scen, A, B), deployment)
            s = call(build_prompt(j, mode, scen, B, A), deployment)
            dims = {}
            for d in DIMS:
                fwd, swp = _score(f, d), 6 - _score(s, d)
                dims[d] = {"fwd": fwd, "swapped": swp, "mean": (fwd + swp) / 2,
                           "fwd_reason": _reason(f, d), "swapped_reason": _reason(s, d)}
            return f"{name}|{j}|{mode}|{tag}", {**base, "dims": dims}
        votes = {d: {"fwd": [], "swap": []} for d in DIMS}
        reasons = {d: "" for d in DIMS}
        for _ in range(args.samples):
            fw = call(build_prompt(j, mode, scen, A, B), deployment)
            sw = call(build_prompt(j, mode, scen, B, A), deployment)
            for d in DIMS:
                votes[d]["fwd"].append(
                    {"response_a": "A", "response_b": "B"}.get(_winner(fw, d), "tie"))
                votes[d]["swap"].append(
                    {"response_a": "B", "response_b": "A"}.get(_winner(sw, d), "tie"))
                reasons[d] = reasons[d] or _reason(fw, d)
        dims = {}
        for d in DIMS:
            maj = {k: max(set(v), key=v.count) for k, v in votes[d].items()}
            consistent = maj["fwd"] == maj["swap"]
            dims[d] = {
                "votes": votes[d],
                "n_A": votes[d]["fwd"].count("A") + votes[d]["swap"].count("A"),
                "n_B": votes[d]["fwd"].count("B") + votes[d]["swap"].count("B"),
                "position_consistent": consistent,
                "winner": maj["fwd"] if (consistent and maj["fwd"] != "tie") else "tie",
                "reason": reasons[d]}
        return f"{name}|{j}|{mode}|{tag}", {**base, "dims": dims}

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(work, j): j for j in jobs}
        for f in as_completed(futs):
            try:
                k, cell = f.result()
            except Exception as e:
                print(f"[judges] FAILED {futs[f]}: {e}")
                continue
            with _lock:
                results[k] = cell
                open(RES, "w").write(json.dumps(results, indent=2))
            done += 1
            print(f"[judges] ({done}/{len(jobs)}) {k}")
    report(results, names, args.samples, tag)


def _cell(c, mode, dim, n):
    if not c or "dims" not in c or dim not in c["dims"]:
        return "-"
    d = c["dims"][dim]
    if mode == "binary":
        return f"{d['n_A']}/{n} {d['winner']}"
    if mode == "pointwise":
        return f"{d['A']}v{d['B']}"
    return f"{d['mean']:.1f}"


def report(results, names, samples, tag):
    n = samples * 2
    short = {"information_value": "info", "practical_usability": "usable",
             "role_complementarity": "role", "autonomy": "auton", "overall": "OVERALL"}
    print("\n" + "=" * 100)
    print(f"model={tag}.  A = treatment.  binary: A-votes out of {n}  |  pointwise: A vs B, Likert 1-5  |  "
          "graded: 1 = A much better, 3 = no pref, 5 = B much better")
    print("=" * 100)
    for mode in ("binary", "pointwise", "graded"):
        for j in JUDGES:
            print(f"\n-- {mode} / {j} --")
            print(f"{'pair':<26}" + "".join(f"{short[d]:>14}" for d in DIMS))
            for name in names:
                c = results.get(f"{name}|{j}|{mode}|{tag}")
                row = "".join(f"{_cell(c, mode, d, n):>14}" for d in DIMS)
                print(f"{name:<26}{row}")

    # Dimension-vs-axis check: each axis pair should move most on its own dimension.
    axis_names = [x for x in names if x.startswith("axis_")]
    if axis_names:
        print("\n" + "=" * 100)
        print("AXIS/DIMENSION ALIGNMENT (graded means; |x-3| = strength, "
              "<3 favours treatment)")
        print("=" * 100)
        print(f"{'axis pair':<26}{'own dimension':<22}{'own':>8}{'largest other':>22}{'that':>8}")
        for name in axis_names:
            dim = name[len("axis_"):]
            if dim not in DIMS:
                continue
            for j in JUDGES:
                c = results.get(f"{name}|{j}|graded|{tag}")
                if not c or "dims" not in c:
                    continue
                own = abs(c["dims"][dim]["mean"] - 3)
                others = {d: abs(c["dims"][d]["mean"] - 3) for d in DIMS
                          if d not in (dim, "overall")}
                top = max(others, key=others.get) if others else "-"
                print(f"{name + ' / ' + j.split('_')[0]:<26}{dim:<22}{own:>8.1f}"
                      f"{top:>22}{others.get(top, 0):>8.1f}")


if __name__ == "__main__":
    main()
