"""
Index the Georgia SNAP Policy Manual from its AsciiDoc export (snap_manual_sections/*.adoc)
instead of scraping the PDF body text. The PDF is still used, but only to look up each
section's page range (for the "open PDF at page X" citation feature) — its body text
is no longer the source of truth for chunking/embedding.

How the join works: every page of the PDF repeats a metadata header block —

    Policy Title: Assistance Units
    Effective Date: June 2026
    Chapter: 3200 Policy Number: 3205

— and this is a verbatim match for the `:policy-title:` / `:policy-number:` frontmatter
attributes on the corresponding .adoc file. We scan the PDF once for these blocks and
join on (policy_number, policy_title) to get page_start/page_end per section.

Three sections (3010, 3025, 3030) are transclusion stubs in this AsciiDoc export — they
just `include::` a shared cross-program page we don't have — so their real content is
pulled from the PDF the old way (detect_sections) as a fallback.

Usage:
    python scripts/index_snap_adoc.py --pdf snap_manual.pdf --sections snap_manual_sections [--clear]
    python scripts/index_snap_adoc.py --dry-run   # parse + map pages, print a report, touch nothing
"""

import argparse
import os
import re
import sys
from pathlib import Path

import pdfplumber
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
from adoc_utils import clean_adoc_body, humanize_slug, parse_adoc_file  # noqa: E402
from index_snap import (  # noqa: E402
    clean_for_embedding,
    detect_sections,
    embed_batch,
    ensure_schema,
    extract_pages,
    naive_token_count,
)

RESOURCE_DB_URL = os.getenv("RESOURCE_DB_URL")
EMBED_MODEL = "text-embedding-3-large"
CHUNK_TOKENS = 500
OVERLAP_LINES = 3

SKIP_FILES = {"index.adoc", "pamms.adoc"}
STUB_SECTIONS = {"3010", "3025", "3030"}  # include::-only files with no real content here

_HEADER_BLOCK_RE = re.compile(
    r"Policy Title:\s*(?P<title>.+?)\s*\nEffective Date:[^\n]*\n"
    r"Chapter:[^\n]*Policy Number:\s*(?P<num>[^\n]+)",
    re.DOTALL,
)


# ── Step 1: load + clean the AsciiDoc sections ──────────────────────────────

def load_adoc_sections(sections_dir: Path) -> list[dict]:
    sections = []
    for path in sorted(sections_dir.glob("*.adoc")):
        if path.name in SKIP_FILES or "toc" in path.name:
            continue
        parsed = parse_adoc_file(path.read_text())
        num = parsed["frontmatter"].get("policy-number", "").strip()
        title = parsed["frontmatter"].get("policy-title", "").strip()
        is_numbered = bool(re.match(r"^\d{4}$", num))
        section_number = num if is_numbered else path.stem

        sections.append({
            "file": path.name,
            "section_number": section_number,
            "policy_number": num,
            "policy_title": title,
            "section_title": title or humanize_slug(path.stem),
            "text": clean_adoc_body(parsed["body"]),
            "is_stub": path.stem in STUB_SECTIONS,
        })
    return sections


# ── Step 2: page-range map from the PDF header blocks ───────────────────────

def build_page_map(pdf_path: str) -> dict[tuple[str, str], tuple[int, int]]:
    """(policy_number, policy_title) -> (page_start, page_end)."""
    entries = []  # (policy_number, policy_title, page_num)
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            for m in _HEADER_BLOCK_RE.finditer(text):
                title = re.sub(r"\s+", " ", m.group("title")).strip()
                num = m.group("num").strip()
                entries.append((num, title, i + 1))

    page_map: dict[tuple[str, str], tuple[int, int]] = {}
    for idx, (num, title, page_num) in enumerate(entries):
        next_page = entries[idx + 1][2] if idx + 1 < len(entries) else page_num
        page_map[(num, title)] = (page_num, next_page)
    return page_map


# ── Step 3: fallback content for transclusion-stub sections ─────────────────

def load_stub_sections(pdf_path: str) -> dict[str, dict]:
    """Extract 3010/3025/3030 the old (PDF text) way — they have no real .adoc body."""
    pages = extract_pages(pdf_path)
    legacy_sections = detect_sections(pages)
    stubs = {}
    for s in legacy_sections:
        if s["section_number"] in STUB_SECTIONS:
            stubs[s["section_number"]] = {
                "text": clean_for_embedding(s["text"]),
                "page_start": s["page_start"],
                "page_end": s["page_end"],
                "section_title": s["section_title"],
            }
    return stubs


# ── Step 4: split 3810 into 3810a / 3810b (same rule as the old pipeline) ───

def split_3810(section: dict) -> list[dict]:
    text = section["text"]
    m = re.search(r"\nRestoration\b", text)
    if not m:
        print("  WARNING: 'Restoration' heading not found in 3810 — keeping unsplit")
        return [section]

    split_pos = m.start() + 1
    part_a, part_b = text[:split_pos], text[split_pos:]
    total_len = len(text) or 1
    page_start, page_end = section["page_start"], section["page_end"]
    mid_page = page_start + int((split_pos / total_len) * (page_end - page_start))

    return [
        {**section, "section_number": "3810a",
         "section_title": "Issuance — Basic Rules and Scheduling",
         "text": part_a, "page_start": page_start, "page_end": mid_page},
        {**section, "section_number": "3810b",
         "section_title": "Issuance — Restoration and Food Loss Replacement",
         "text": part_b, "page_start": mid_page + 1, "page_end": page_end},
    ]


# ── Step 5: chunk a section's cleaned text, interpolating page numbers ──────

def chunk_adoc_section(section: dict) -> list[dict]:
    lines = [l for l in section["text"].split("\n") if l.strip()]
    if not lines:
        return []

    cum = [0]
    for l in lines:
        cum.append(cum[-1] + len(l) + 1)
    total_chars = cum[-1] or 1

    page_start, page_end = section["page_start"], section["page_end"]
    if page_start is None or page_end is None:
        def page_at(char_offset: int) -> int | None:
            return None
    else:
        page_span = max(page_end - page_start, 0)

        def page_at(char_offset: int) -> int | None:
            frac = char_offset / total_chars
            return page_start + round(frac * page_span)

    chunks = []
    chunk_idx = 0
    start = 0
    while start < len(lines):
        current_lines: list[str] = []
        current_tokens = 0
        i = start
        while i < len(lines):
            line = lines[i]
            t = naive_token_count(line)
            if current_tokens + t > CHUNK_TOKENS and current_lines:
                break
            current_lines.append(line)
            current_tokens += t
            i += 1

        chunks.append({
            "section_number": section["section_number"],
            "section_title": section["section_title"],
            "chunk_index": chunk_idx,
            "page_start": page_at(cum[start]),
            "page_end": page_at(cum[i]),
            "content": "\n".join(current_lines),
        })

        if i == len(lines):
            break
        start = max(start + 1, i - OVERLAP_LINES)
        chunk_idx += 1

    return chunks


# ── Orchestration ────────────────────────────────────────────────────────────

def build_sections(pdf_path: str, sections_dir: Path) -> tuple[list[dict], list[str]]:
    """Returns (resolved_sections, warnings)."""
    warnings = []
    adoc_sections = load_adoc_sections(sections_dir)
    page_map = build_page_map(pdf_path)
    stubs = load_stub_sections(pdf_path) if any(s["is_stub"] for s in adoc_sections) else {}

    resolved = []
    for s in adoc_sections:
        if s["is_stub"]:
            # stub sections have no policy_number in frontmatter; key by filename stem
            stub = stubs.get(s["section_number"])
            if not stub:
                warnings.append(f"STUB {s['file']}: no PDF fallback content found — skipping")
                continue
            resolved.append({
                "section_number": s["section_number"],
                "section_title": stub["section_title"],
                "text": stub["text"],
                "page_start": stub["page_start"],
                "page_end": stub["page_end"],
            })
            continue

        key = (s["policy_number"], s["policy_title"])
        pages = page_map.get(key)
        if not pages:
            warnings.append(
                f"NO PAGE MATCH {s['file']} (policy-number={s['policy_number']!r}, "
                f"policy-title={s['policy_title']!r}) — dropping page citation for this section"
            )
            pages = (None, None)

        resolved.append({
            "section_number": s["section_number"],
            "section_title": s["section_title"],
            "text": s["text"],
            "page_start": pages[0],
            "page_end": pages[1],
        })

    final = []
    for s in resolved:
        if s["section_number"] == "3810":
            final.extend(split_3810(s))
        else:
            final.append(s)
    return final, warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default="snap_manual.pdf")
    parser.add_argument("--sections", default="snap_manual_sections")
    parser.add_argument("--clear", action="store_true", help="Delete existing rows first")
    parser.add_argument("--dry-run", action="store_true", help="Parse + map only, print a report, write nothing")
    args = parser.parse_args()

    sections_dir = Path(args.sections)
    if not os.path.exists(args.pdf):
        print(f"PDF not found: {args.pdf}")
        sys.exit(1)
    if not sections_dir.exists():
        print(f"Sections dir not found: {sections_dir}")
        sys.exit(1)

    print(f"[1/4] Loading + cleaning .adoc sections from {sections_dir} …")
    print(f"[2/4] Mapping sections to PDF page ranges via {args.pdf} …")
    final_sections, warnings = build_sections(args.pdf, sections_dir)
    print(f"      {len(final_sections)} sections resolved")
    if warnings:
        print(f"      {len(warnings)} warning(s):")
        for w in warnings:
            print(f"        - {w}")

    no_pages = [s["section_number"] for s in final_sections if s["page_start"] is None]
    if no_pages:
        print(f"      Sections with NO page range (citations will lack a PDF link): {no_pages}")

    print("[3/4] Chunking …")
    all_chunks = []
    for s in final_sections:
        all_chunks.extend(chunk_adoc_section(s))
    print(f"      {len(all_chunks)} chunks total")

    if args.dry_run:
        print("[4/4] --dry-run: skipping embed + DB write.")
        total_words = sum(len(s["text"].split()) for s in final_sections)
        print(f"      {total_words:,} words across {len(final_sections)} sections")
        return

    print("[4/4] Embedding and inserting into pgvector...")
    import psycopg
    conn = psycopg.connect(RESOURCE_DB_URL)
    cur = conn.cursor()
    has_ts = ensure_schema(cur)
    conn.commit()

    if args.clear:
        cur.execute("DELETE FROM snap_chunks")
        try:
            cur.execute("DELETE FROM snap_sections")
        except Exception:
            conn.rollback()
            print("      (snap_sections not yet created — skipping its clear)")
        conn.commit()
        print("      Cleared existing rows.")

    print("      Populating snap_sections …")
    for s in final_sections:
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
            (s["section_number"], s["section_title"], s["page_start"], s["page_end"], s["text"]),
        )
    conn.commit()
    print(f"      {len(final_sections)} sections stored in snap_sections")

    BATCH = 16
    inserted = 0
    for i in range(0, len(all_chunks), BATCH):
        batch = all_chunks[i:i + BATCH]
        texts = [clean_for_embedding(c["content"]) for c in batch]
        embeddings = embed_batch(texts)
        for chunk, emb in zip(batch, embeddings):
            if has_ts:
                cur.execute(
                    """
                    INSERT INTO snap_chunks
                        (section_number, section_title, chunk_index,
                         page_start, page_end, content, embedding, ts_content)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::vector, to_tsvector('english', %s))
                    """,
                    (chunk["section_number"], chunk["section_title"], chunk["chunk_index"],
                     chunk["page_start"], chunk["page_end"], chunk["content"], str(emb), chunk["content"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO snap_chunks
                        (section_number, section_title, chunk_index,
                         page_start, page_end, content, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                    """,
                    (chunk["section_number"], chunk["section_title"], chunk["chunk_index"],
                     chunk["page_start"], chunk["page_end"], chunk["content"], str(emb)),
                )
        conn.commit()
        inserted += len(batch)
        print(f"      {inserted}/{len(all_chunks)} chunks inserted", end="\r")

    conn.close()
    print(f"\nDone. {inserted} chunks indexed across {len(final_sections)} sections.")
    print("Next: regenerate eval/section_vectors.json and eval/section_summaries.json, e.g.")
    print("  python scripts/compare_routing.py --regen-summaries --regen-vectors --split train")


if __name__ == "__main__":
    main()
