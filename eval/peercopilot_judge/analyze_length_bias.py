"""
Post-hoc length-bias control (protocol.md section 6: "If quality ratings track
length ... more than anything else, you've learned what the judge is actually
measuring.").

Uses only data already in judge_scores.csv (word_count_1/2, preference) — no
new judge calls, no additional cost. Approach mirrors AlpacaEval 2.0's
length-controlled win rate: fit a logistic regression of
    P(pair[0] preferred) ~ (word_count(pair[0]) - word_count(pair[1]))
per arm-pair (optionally split by rubric), then read off the predicted
preference rate at length_diff = 0 — i.e. "who would win if both responses
were the same length." The gap between that and the raw (length-blind) win
rate is the length-bias estimate.

Usage (from repo root):
    python -m eval.peercopilot_judge.analyze_length_bias
    python -m eval.peercopilot_judge.analyze_length_bias --split-by-rubric

Ties are excluded from the logistic fit (standard for this kind of analysis)
but reported separately. With only a handful of non-tie observations per
pair, treat the fitted coefficient as illustrative, not a real estimate —
this script says so in its output when n is small.
"""
import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

SCORES_PATH = Path(__file__).resolve().parent / "output" / "judge_scores.csv"
SUMMARY_PATH = Path(__file__).resolve().parent / "output" / "length_bias_summary.csv"

MIN_N_FOR_FIT = 6  # below this, the logistic fit is essentially noise


def load_rows():
    with open(SCORES_PATH) as f:
        return list(csv.DictReader(f))


def build_pair_observations(rows, split_by_rubric: bool):
    """
    Returns {key: [(length_diff, y, is_tie), ...]} where key is
    (pair_arm_0, pair_arm_1) or (rubric, pair_arm_0, pair_arm_1), pair is the
    two arms sorted alphabetically, y=1 means pair_arm_0 was preferred,
    length_diff = word_count(pair_arm_0) - word_count(pair_arm_1).
    """
    obs = defaultdict(list)
    for r in rows:
        arm_1, arm_2 = r["arm_1"], r["arm_2"]
        pair = tuple(sorted((arm_1, arm_2)))
        wc1, wc2 = int(r["word_count_1"]), int(r["word_count_2"])

        if pair[0] == arm_1:
            length_diff = wc1 - wc2
            pref_is_pair0 = r["preference"] == "1"
            pref_is_pair1 = r["preference"] == "2"
        else:
            length_diff = wc2 - wc1
            pref_is_pair0 = r["preference"] == "2"
            pref_is_pair1 = r["preference"] == "1"

        is_tie = r["preference"] == "tie" or not (pref_is_pair0 or pref_is_pair1)
        y = 1 if pref_is_pair0 else (0 if pref_is_pair1 else None)

        key = (r["rubric"], pair[0], pair[1]) if split_by_rubric else pair
        obs[key].append((length_diff, y, is_tie))

    return obs


def fit_length_controlled_rate(observations):
    """
    observations: list of (length_diff, y, is_tie).
    Returns dict with raw_win_rate, length_controlled_win_rate, coefficient,
    n_ties, n_used, and a caveat string when n is too small to trust.
    """
    non_tie = [(d, y) for d, y, tie in observations if not tie]
    n_ties = len(observations) - len(non_tie)

    if not non_tie:
        return {"n_used": 0, "n_ties": n_ties, "caveat": "all ties, or no data"}

    diffs = np.array([d for d, _ in non_tie], dtype=float)
    ys = np.array([y for _, y in non_tie], dtype=float)
    raw_win_rate = float(ys.mean())

    if len(set(ys.tolist())) < 2 or len(non_tie) < MIN_N_FOR_FIT:
        return {
            "n_used": len(non_tie),
            "n_ties": n_ties,
            "raw_win_rate": raw_win_rate,
            "length_controlled_win_rate": None,
            "coefficient": None,
            "caveat": f"n={len(non_tie)} (<{MIN_N_FOR_FIT}) or no variation in outcome — "
            "fit skipped, not enough data to separate length effect from noise.",
        }

    from sklearn.linear_model import LogisticRegression

    x = diffs.reshape(-1, 1)
    # Standardize the predictor so the L2 penalty (needed to keep tiny/separable
    # samples from diverging) doesn't unfairly shrink a large-scale length_diff.
    x_std = x.std() or 1.0
    x_scaled = x / x_std

    model = LogisticRegression(penalty="l2", C=1.0)
    model.fit(x_scaled, ys)

    coefficient = float(model.coef_[0][0] / x_std)  # back to per-word-of-difference units
    length_controlled_win_rate = float(model.predict_proba(np.array([[0.0]]))[0][1])

    return {
        "n_used": len(non_tie),
        "n_ties": n_ties,
        "raw_win_rate": raw_win_rate,
        "length_controlled_win_rate": length_controlled_win_rate,
        "coefficient": coefficient,
        "caveat": None if len(non_tie) >= 20 else
        f"n={len(non_tie)} is small — treat the length-controlled estimate as illustrative.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split-by-rubric", action="store_true", help="Fit separately per rubric instead of pooling A+B.")
    args = parser.parse_args()

    if not SCORES_PATH.exists():
        raise SystemExit(f"{SCORES_PATH} not found — run run_judge.py first.")

    rows = load_rows()
    obs_by_key = build_pair_observations(rows, args.split_by_rubric)

    results = []
    for key, observations in sorted(obs_by_key.items()):
        result = fit_length_controlled_rate(observations)
        result["key"] = key
        results.append(result)

    print(f"Length-bias analysis over {len(rows)} judge_scores.csv rows "
          f"({'split by rubric' if args.split_by_rubric else 'rubrics pooled'}):\n")

    with open(SUMMARY_PATH, "w", newline="") as f:
        header = ["pair", "rubric", "n_used", "n_ties", "raw_win_rate",
                   "length_controlled_win_rate", "length_effect", "coefficient_per_word", "caveat"]
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()

        for r in results:
            if args.split_by_rubric:
                rubric, a0, a1 = r["key"]
            else:
                rubric = "A+B pooled"
                a0, a1 = r["key"]

            raw = r.get("raw_win_rate")
            lc = r.get("length_controlled_win_rate")
            effect = (raw - lc) if (raw is not None and lc is not None) else None

            print(f"[{rubric}] {a0} vs {a1}  (n={r['n_used']}, ties={r['n_ties']})")
            if raw is not None:
                print(f"    raw win rate for {a0}:              {raw:.2f}")
            if lc is not None:
                print(f"    length-controlled win rate for {a0}: {lc:.2f}"
                      f"  (effect attributable to length: {effect:+.2f})")
                print(f"    logistic coefficient (per word of length advantage): {r['coefficient']:.4f}")
            if r.get("caveat"):
                print(f"    caveat: {r['caveat']}")
            print()

            writer.writerow({
                "pair": f"{a0} vs {a1}",
                "rubric": rubric,
                "n_used": r["n_used"],
                "n_ties": r["n_ties"],
                "raw_win_rate": raw,
                "length_controlled_win_rate": lc,
                "length_effect": effect,
                "coefficient_per_word": r.get("coefficient"),
                "caveat": r.get("caveat") or "",
            })

    print(f"Wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
