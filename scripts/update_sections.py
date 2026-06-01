"""
Rebuild snap_sections from the PDF without re-embedding chunks.

- Extracts pages with clean table rendering (non-table text + table prose, no duplication)
- Detects sections with finditer() (catches multiple headers per page)
- Splits section 3810 at the "Restoration" heading → 3810a + 3810b
- UPSERTs snap_sections; does NOT touch snap_chunks or call OpenAI

Usage:
    python scripts/update_sections.py --pdf snap_manual.pdf
"""

import argparse
import os
import re
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

# Reuse helpers from index_snap
sys.path.insert(0, os.path.dirname(__file__))
from index_snap import extract_pages, detect_sections  # noqa: E402

RESOURCE_DB_URL = os.getenv("RESOURCE_DB_URL")


def split_3810(sections: list[dict]) -> list[dict]:
    """Split section 3810 at the 'Restoration' heading into 3810a and 3810b."""
    result = []
    for s in sections:
        if s["section_number"] != "3810":
            result.append(s)
            continue

        text = s["text"]
        # Find the Restoration heading (a line that IS exactly "Restoration")
        m = re.search(r"\nRestoration\b", text)
        if not m:
            print("  WARNING: 'Restoration' heading not found in 3810 — keeping unsplit")
            result.append(s)
            continue

        split_pos = m.start() + 1  # keep leading newline with Part B

        part_a = text[:split_pos]
        part_b = text[split_pos:]

        # Estimate page boundary proportionally
        total_len = len(text) or 1
        mid_page = s["page_start"] + int(
            (split_pos / total_len) * (s["page_end"] - s["page_start"])
        )

        result.append({
            "section_number": "3810a",
            "section_title": "Issuance — Basic Rules and Scheduling",
            "page_start": s["page_start"],
            "page_end": mid_page,
            "text": part_a,
        })
        result.append({
            "section_number": "3810b",
            "section_title": "Issuance — Restoration and Food Loss Replacement",
            "page_start": mid_page + 1,
            "page_end": s["page_end"],
            "text": part_b,
        })
        print(f"  Split 3810 → 3810a ({len(part_a):,} chars) + 3810b ({len(part_b):,} chars)")

    return result


def upsert_sections(sections: list[dict], cur) -> int:
    count = 0
    for s in sections:
        cur.execute(
            """
            INSERT INTO snap_sections
                (section_number, section_title, page_start, page_end, full_content)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (section_number) DO UPDATE
                SET section_title = EXCLUDED.section_title,
                    page_start    = EXCLUDED.page_start,
                    page_end      = EXCLUDED.page_end,
                    full_content  = EXCLUDED.full_content
            """,
            (s["section_number"], s["section_title"],
             s["page_start"], s["page_end"], s["text"]),
        )
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        print(f"PDF not found: {args.pdf}")
        sys.exit(1)

    print(f"[1/4] Extracting pages from {args.pdf} …")
    pages = extract_pages(args.pdf)
    print(f"      {len(pages)} content pages")

    print("[2/4] Detecting sections …")
    sections = detect_sections(pages)
    print(f"      {len(sections)} sections found")

    print("[3/4] Splitting 3810 at Restoration …")
    sections = split_3810(sections)
    print(f"      {len(sections)} sections after split")

    print("[4/4] Upserting snap_sections …")
    # Also remove the old unsplit 3810 if it exists
    conn = psycopg.connect(RESOURCE_DB_URL)
    cur = conn.cursor()
    cur.execute("DELETE FROM snap_sections WHERE section_number = '3810'")
    deleted = cur.rowcount
    if deleted:
        print(f"      Removed old 3810 row")

    n = upsert_sections(sections, cur)
    conn.commit()
    conn.close()
    print(f"      {n} sections written to snap_sections")
    print("Done.")


if __name__ == "__main__":
    main()
