"""
Run J1/J2/J3 over pairs, in all three elicitation modes.

  binary     both orderings x --samples, majority per ordering; disagreement = tie
  pointwise  each arm scored 1-5 independently
  graded     1-5 preference, both orderings, swapped reverse-coded (6 - score)
             so 1 = A much better, 3 = no preference, 5 = B much better

Usage:
    conda run -n feedback bash -c 'set -a; source backend/.env; set +a; \
        python -m eval.ae_judge.run_judges --family axis'
    ... --pairs axis_direction,s8_unhappy_treatment
    ... --family all
"""
import argparse
import json
import os
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from eval.ae_judge.judges import FRAMINGS, build_prompt, call
from eval.ae_judge.pairs import load

_OUT = os.path.join(os.path.dirname(__file__), "output")
RES = os.path.join(_OUT, "judge_results.json")
JUDGES = list(FRAMINGS)
_lock = threading.Lock()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="axis", choices=["axis", "scenario", "all"])
    ap.add_argument("--pairs", default=None, help="comma-separated pair names")
    ap.add_argument("--samples", type=int, default=3, help="binary samples per ordering")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    pairs = load()
    names = ([n for n in args.pairs.split(",")] if args.pairs else
             [n for n, p in pairs.items() if args.family == "all" or p["family"] == args.family])

    results = json.loads(open(RES).read()) if os.path.exists(RES) else {}
    jobs = []
    for n in names:
        for j in JUDGES:
            for mode in ("binary", "pointwise", "graded"):
                if f"{n}|{j}|{mode}" not in results:
                    jobs.append((n, j, mode))
    ncalls = sum({"binary": args.samples * 2, "pointwise": 2, "graded": 2}[m] for _, _, m in jobs)
    print(f"[judges] {len(names)} pairs, {len(jobs)} cells, {ncalls} calls")

    def work(job):
        name, j, mode = job
        p = pairs[name]
        scen, A, B = p["scenario"], p["A"], p["B"]
        if mode == "pointwise":
            out = {m: call(build_prompt(j, mode, scen, t)) for m, t in (("A", A), ("B", B))}
            return f"{name}|{j}|{mode}", {
                "mode": mode, "judge": j, "pair": name,
                "A_score": out["A"].get("score"), "B_score": out["B"].get("score"),
                "A_reason": out["A"].get("reason", ""), "B_reason": out["B"].get("reason", "")}
        if mode == "graded":
            f = call(build_prompt(j, mode, scen, A, B))
            s = call(build_prompt(j, mode, scen, B, A))
            fwd, swp = int(f.get("score", 3)), 6 - int(s.get("score", 3))
            return f"{name}|{j}|{mode}", {
                "mode": mode, "judge": j, "pair": name, "fwd": fwd, "swapped": swp,
                "mean": (fwd + swp) / 2, "fwd_reason": f.get("reason", ""),
                "swapped_reason": s.get("reason", "")}
        votes = {"fwd": [], "swap": []}
        reasons = []
        for _ in range(args.samples):
            d = call(build_prompt(j, mode, scen, A, B))
            votes["fwd"].append({"response_a": "A", "response_b": "B"}.get(d.get("winner"), "tie"))
            reasons.append(d.get("reason", ""))
            d = call(build_prompt(j, mode, scen, B, A))
            votes["swap"].append({"response_a": "B", "response_b": "A"}.get(d.get("winner"), "tie"))
        maj = {k: max(set(v), key=v.count) for k, v in votes.items()}
        consistent = maj["fwd"] == maj["swap"]
        return f"{name}|{j}|{mode}", {
            "mode": mode, "judge": j, "pair": name, "votes": votes,
            "n_A": votes["fwd"].count("A") + votes["swap"].count("A"),
            "n_B": votes["fwd"].count("B") + votes["swap"].count("B"),
            "position_consistent": consistent,
            "winner": maj["fwd"] if (consistent and maj["fwd"] != "tie") else "tie",
            "reason": reasons[0] if reasons else ""}

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
    report(results, names, args.samples)


def report(results, names, samples):
    n = samples * 2
    print("\n" + "=" * 96)
    print(f"A = treatment.  binary: A-votes out of {n}  |  pointwise: A vs B (1-5)  |  "
          "graded: 1 = A much better, 3 = no preference, 5 = B much better")
    print("=" * 96)
    for mode in ("binary", "pointwise", "graded"):
        print(f"\n-- {mode} --")
        print(f"{'pair':<30}" + "".join(f"{j.split('_')[0]:>22}" for j in JUDGES))
        for name in names:
            row = ""
            for j in JUDGES:
                c = results.get(f"{name}|{j}|{mode}")
                if not c:
                    cell = "-"
                elif mode == "binary":
                    cell = f"{c['n_A']}/{n}  {c['winner']}"
                elif mode == "pointwise":
                    cell = f"{c['A_score']} vs {c['B_score']}"
                else:
                    cell = f"{c['mean']:.1f}  ({c['fwd']}/{c['swapped']})"
                row += f"{cell:>22}"
            print(f"{name:<30}{row}")


if __name__ == "__main__":
    main()
