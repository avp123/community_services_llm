#!/usr/bin/env python3
"""
Evaluate SNAP RAG model predictions against rubric.

Precomputed answers:
  python scripts/evaluate.py --split train --model new
  python scripts/evaluate.py --split test  --model new
  python scripts/evaluate.py --split test  --model old

Live generation from the running server, then evaluate:
  python scripts/evaluate.py --split test --generate

Custom answers file:
  python scripts/evaluate.py --split test --answers path/to/answers.json

Save detailed per-question results:
  python scripts/evaluate.py --split test --model new --output eval/results/test_new.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
QUESTIONS_DIR = ROOT / "eval" / "questions"
ANSWERS_DIR = ROOT / "eval" / "answers"

QUESTIONS_FILES = {
    "train": QUESTIONS_DIR / "snap_train.json",
    "test":  QUESTIONS_DIR / "snap_test.json",
    "val":   QUESTIONS_DIR / "snap_val.json",
}

PRECOMPUTED_ANSWERS = {
    ("train", "new"): ANSWERS_DIR / "snap_train_new.json",
    ("test",  "new"): ANSWERS_DIR / "snap_test_new.json",
    ("test",  "old"): ANSWERS_DIR / "snap_test_old.json",
}

JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-5-chat")


# ── Data loading ─────────────────────────────────────────────────────────────

def load_questions(split: str) -> dict[str, dict]:
    with open(QUESTIONS_FILES[split]) as f:
        return {q["id"]: q for q in json.load(f)["questions"]}


def load_answers(path: Path | str) -> dict[str, dict]:
    with open(path) as f:
        return {q["id"]: q for q in json.load(f)["questions"]}


# ── Live answer generation ────────────────────────────────────────────────────

def generate_answers(split: str, questions: dict[str, dict]) -> tuple[dict[str, dict], Path]:
    """Call query_snap() for every question and save a timestamped answers file."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.snap_query import query_snap  # noqa: PLC0415

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = ANSWERS_DIR / f"snap_{split}_generated_{timestamp}.json"

    records = []
    for qid, q in questions.items():
        print(f"  Generating {qid} …")
        result = query_snap(q["question"], mode="expert")
        routed = [s["section_number"] for s in result.get("sources", []) if s.get("routed")]
        if routed:
            print(f"    → routed to: {', '.join(routed)}")
        records.append({
            "id": qid,
            "question": q["question"],
            "predicted_answer": result["answer"],
            "routed_sections": routed,
        })

    out_path.write_text(json.dumps({
        "dataset": f"SNAP {split.title()} Set — Generated Answers",
        "description": f"Generated {datetime.now().isoformat()} by scripts/evaluate.py",
        "questions": records,
    }, indent=2))
    print(f"  Saved generated answers → {out_path}")

    return {r["id"]: r for r in records}, out_path


# ── LLM judge ────────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """\
You are evaluating an AI assistant's answer to a Georgia SNAP policy question.

QUESTION:
{question}

CORRECT ANSWER SUMMARY:
{correct_answer_summary}

KEY RUBRIC POINTS (each should be clearly addressed):
{rubric_points}

COMMON ERRORS TO AVOID:
{common_errors}

PREDICTED ANSWER:
{predicted_answer}

For each rubric point decide: does the predicted answer cover it (true/false)?
For each common error decide: does the predicted answer commit it (true/false)?
Give an overall score 1–5:
  5 = covers all rubric points, no errors
  4 = covers ≥80% of points, at most 1 minor error
  3 = covers 50–80% of points, or 1 significant error
  2 = covers <50% of points, or multiple errors
  1 = wrong or actively misleading

Respond with valid JSON only, no markdown fences:
{{
  "rubric_coverage": {{<exact rubric point text>: true/false, …}},
  "errors_committed": {{<exact error text>: true/false, …}},
  "overall_score": <1–5>,
  "reasoning": "<1–2 sentence explanation>"
}}"""


def _judge_client():
    from openai import AzureOpenAI
    return AzureOpenAI(
        api_key=os.environ["OPENAI_API_KEY_AZURE"],
        azure_endpoint=os.environ["OPENAI_AZURE_ENDPOINT"],
        api_version="2024-12-01-preview",
    )


def evaluate_one(q: dict, predicted_answer: str, client) -> dict:
    prompt = _JUDGE_PROMPT.format(
        question=q["question"],
        correct_answer_summary=q["correct_answer_summary"],
        rubric_points="\n".join(f"- {p}" for p in q["key_rubric_points"]),
        common_errors="\n".join(f"- {e}" for e in q["common_errors"]),
        predicted_answer=predicted_answer,
    )
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=900,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


# ── Evaluation loop ───────────────────────────────────────────────────────────

def run_evaluation(questions: dict, answers: dict, client) -> list[dict]:
    results = []
    for qid in sorted(questions):
        if qid not in answers:
            print(f"  WARNING: {qid} missing from answers — skipped")
            continue
        predicted = answers[qid].get("predicted_answer") or answers[qid].get("policy_engine_answer", "")
        print(f"  Judging {qid} …")
        try:
            ev = evaluate_one(questions[qid], predicted, client)
        except Exception as exc:
            print(f"  ERROR judging {qid}: {exc}")
            continue

        rubric_hit   = sum(1 for v in ev["rubric_coverage"].values() if v)
        rubric_total = len(ev["rubric_coverage"])
        errors_hit   = sum(1 for v in ev["errors_committed"].values() if v)

        results.append({
            "id": qid,
            "score": ev["overall_score"],
            "rubric_hit": rubric_hit,
            "rubric_total": rubric_total,
            "rubric_pct": round(rubric_hit / rubric_total * 100, 1) if rubric_total else 0.0,
            "errors_committed": errors_hit,
            "rubric_coverage": ev["rubric_coverage"],
            "errors_detail": ev["errors_committed"],
            "reasoning": ev.get("reasoning", ""),
        })
    return results


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_report(results: list[dict], label: str) -> None:
    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"{'='*65}")
    if not results:
        print("  No results.")
        return

    n = len(results)
    avg_score  = sum(r["score"] for r in results) / n
    avg_rubric = sum(r["rubric_pct"] for r in results) / n
    total_errs = sum(r["errors_committed"] for r in results)

    print(f"  Questions evaluated : {n}")
    print(f"  Avg score  (1–5)    : {avg_score:.2f}")
    print(f"  Avg rubric coverage : {avg_rubric:.1f}%")
    print(f"  Total errors committed: {total_errs}")
    print()
    print(f"  {'ID':<6} {'Score':>5} {'Rubric%':>8} {'Errors':>7}  Notes")
    print("  " + "-"*62)
    for r in sorted(results, key=lambda x: x["id"]):
        note = r["reasoning"][:55] if r["reasoning"] else ""
        print(f"  {r['id']:<6} {r['score']:>5} {r['rubric_pct']:>7.0f}% {r['errors_committed']:>7}  {note}")

    # Flag weak answers
    weak = [r for r in results if r["score"] <= 2]
    if weak:
        print(f"\n  LOW-SCORING (≤2): {', '.join(r['id'] for r in weak)}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate SNAP RAG model predictions against rubric",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--split", choices=["train", "test", "val"], default="test",
                        help="Question split to evaluate (default: test)")
    parser.add_argument("--model", choices=["new", "old"], default="new",
                        help="Precomputed answer set to use (default: new)")
    parser.add_argument("--answers", metavar="PATH",
                        help="Path to a custom answers JSON (overrides --model)")
    parser.add_argument("--generate", action="store_true",
                        help="Generate fresh answers from the live server, then evaluate")
    parser.add_argument("--output", metavar="PATH",
                        help="Save full per-question results to this JSON file")
    parser.add_argument("--no-eval", action="store_true",
                        help="With --generate: generate answers but skip LLM judging")
    args = parser.parse_args()

    questions = load_questions(args.split)

    # --- Determine answers source ---
    label: str
    if args.generate:
        print(f"Generating answers for '{args.split}' split from live server …")
        answers, gen_path = generate_answers(args.split, questions)
        label = f"{args.split.upper()} — live model ({gen_path.name})"
        if args.no_eval:
            print("Skipping evaluation (--no-eval). Done.")
            return
    elif args.answers:
        answers = load_answers(args.answers)
        label = f"{args.split.upper()} — {args.answers}"
    else:
        key = (args.split, args.model)
        if key not in PRECOMPUTED_ANSWERS:
            parser.error(
                f"No precomputed answers for split='{args.split}' model='{args.model}'.\n"
                "Available: train/new, test/new, test/old. Use --generate or --answers."
            )
        answers = load_answers(PRECOMPUTED_ANSWERS[key])
        label = f"{args.split.upper()} split — {args.model} model"

    # --- Run LLM evaluation ---
    print(f"\nEvaluating: {label}")
    client = _judge_client()
    results = run_evaluation(questions, answers, client)
    print_report(results, label)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "label": label,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "n": len(results),
                "avg_score": round(sum(r["score"] for r in results) / len(results), 3) if results else 0,
                "avg_rubric_pct": round(sum(r["rubric_pct"] for r in results) / len(results), 1) if results else 0,
                "total_errors": sum(r["errors_committed"] for r in results),
            },
            "questions": results,
        }, indent=2))
        print(f"\nDetailed results saved → {args.output}")


if __name__ == "__main__":
    main()
