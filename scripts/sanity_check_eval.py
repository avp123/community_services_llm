#!/usr/bin/env python3
"""Quick sanity check: run a subset of training questions through the full eval pipeline."""
import json
import os
import sys
from pathlib import Path

# Reuse everything from compare_routing
sys.path.insert(0, str(Path(__file__).parent))
import compare_routing as cr

ROOT = Path(__file__).parent.parent
SPLIT = "train"
CHECK_IDS = {"T01", "T03"}  # previously failing — check for improvement

def main():
    import psycopg
    from dotenv import load_dotenv
    load_dotenv()

    db_url = os.getenv("RESOURCE_DB_URL")
    questions_path = ROOT / "eval" / "questions" / "snap_train.json"
    rewrites_path  = ROOT / "eval" / "rewritten_questions_train.json"

    all_questions = json.loads(questions_path.read_text())["questions"]
    questions = [q for q in all_questions if q["id"] in CHECK_IDS]
    print(f"Running {len(questions)} questions: {[q['id'] for q in questions]}\n")

    rewrites = json.loads(rewrites_path.read_text()) if rewrites_path.exists() else {}

    conn = psycopg.connect(db_url)
    cur  = conn.cursor()
    cur.execute("""
        SELECT section_number, section_title, LEFT(full_content, 5500)
        FROM snap_sections ORDER BY section_number
    """)
    sections = cur.fetchall()
    conn.close()

    summaries = cr.load_summaries(sections, regen=False)
    sec_vecs  = cr.load_section_vectors(sections, regen=False)

    print(f"Loaded {len(sections)} sections, {len(summaries)} summaries\n")
    print("=" * 65)
    print("  SANITY CHECK — summary_llm  (ROUTE_MAX=3, max_tokens=1200)")
    print("=" * 65)

    cr.run_full_eval(
        method="summary_llm",
        questions=questions,
        summaries=summaries,
        sec_vecs=sec_vecs,
        sections=sections,
        rewrites=rewrites,
        hybrid_k=cr.HYBRID_K,
        db_url=db_url,
        split=SPLIT,
    )

if __name__ == "__main__":
    main()
