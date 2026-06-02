"""
Index the Georgia SNAP Policy Manual into pgvector with BM25 support.

Usage:
    python scripts/index_snap.py --pdf snap_manual.pdf [--clear]
"""

import argparse
import os
import re
import sys
import time

import pdfplumber
import psycopg
from dotenv import load_dotenv

load_dotenv()

RESOURCE_DB_URL = os.getenv("RESOURCE_DB_URL")
EMBED_MODEL = "text-embedding-3-large"
CHUNK_TOKENS = 500       # target tokens per chunk
OVERLAP_LINES = 3        # lines of overlap between chunks
TOC_PAGES = 13           # skip table-of-contents pages at the start
PARENT_SECTION_MIN_CHUNKS = 30  # store full section text for sections with at least this many chunks

from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SECTION_RE = re.compile(r"^\s*(\d{4})\s+([A-Z][^\n]{5,80})\s*$", re.MULTILINE)

_META_LINE_RE = re.compile(
    r"^\s*(?:"
    r"\d{4}\s+(?:Previous MT|Policy Title|Effective Date|Chapter|Policy Number)"
    r"|Previous MT Num\S*"
    r"|Updated or Reviewed in MT"
    r"|MT-\d+"
    r"|Georgia Division of Family"
    r"|SNAP Policy Manual"
    r"|Policy Title:"
    r"|Effective Date:"
    r"|Chapter:\s*\d"
    r"|Policy Number:"
    r")[^\n]*",
    re.MULTILINE | re.IGNORECASE,
)


def clean_for_embedding(text: str) -> str:
    cleaned = _META_LINE_RE.sub("", text).strip()
    return cleaned if cleaned else text


def table_to_prose(table: list[list]) -> str:
    """Convert a pdfplumber table (list-of-lists) to readable key:value lines."""
    if not table or len(table) < 2:
        return ""
    headers = [str(h or "").strip() for h in table[0]]
    lines = []
    for row in table[1:]:
        cells = [str(c or "").strip() for c in row]
        if any(cells):
            pairs = [f"{h}: {v}" for h, v in zip(headers, cells) if v and h]
            if pairs:
                lines.append(" | ".join(pairs))
    return "\n".join(lines)


def extract_pages(pdf_path: str) -> list[dict]:
    """Return list of {page_num, text} dicts, skipping TOC. Uses pdfplumber.

    Tables are rendered once, cleanly: raw table cells are excluded from the
    flowing text and replaced with key:value prose appended at the end of the
    page. This avoids the duplicated / garbled table content that results when
    pdfplumber's text extractor and extract_tables() both emit the same cells.
    """
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            if i < TOC_PAGES:
                continue

            found_tables = page.find_tables() or []
            table_bboxes = [t.bbox for t in found_tables]

            if table_bboxes:
                # Extract text only from characters that fall outside every table bbox.
                def outside_tables(obj):
                    if obj.get("object_type") != "char":
                        return True
                    x0, top = obj.get("x0", 0), obj.get("top", 0)
                    for bx0, by0, bx1, by1 in table_bboxes:
                        if bx0 - 2 <= x0 <= bx1 + 2 and by0 - 2 <= top <= by1 + 2:
                            return False
                    return True
                text = page.filter(outside_tables).extract_text() or ""
            else:
                text = page.extract_text() or ""

            table_prose = []
            for t in found_tables:
                prose = table_to_prose(t.extract())
                if prose:
                    table_prose.append(prose)
            if table_prose:
                text = text + "\n\n" + "\n\n".join(table_prose)

            if text.strip():
                pages.append({"page_num": i + 1, "text": text})
    return pages


def detect_sections(pages: list[dict]) -> list[dict]:
    """
    Group pages into sections based on 4-digit section headers.
    Returns list of {section_number, section_title, page_start, page_end, text}.

    Uses finditer() to catch multiple section headers on a single page (e.g. a
    page that begins section 3200 and immediately defines section 3205).
    """
    sections = []
    current = None
    seen_sections: set[str] = set()

    for p in pages:
        page_text = p["text"]
        new_matches = [
            (m.start(), m.group(1), m.group(2))
            for m in SECTION_RE.finditer(page_text)
            if m.group(1) not in seen_sections
        ]

        if not new_matches:
            if current:
                current["text"] += "\n" + page_text
                current["page_end"] = p["page_num"]
            continue

        # Append the fragment before the first new section header to the current section
        first_pos = new_matches[0][0]
        if current and first_pos > 0:
            fragment = page_text[:first_pos]
            if fragment.strip():
                current["text"] += "\n" + fragment
                # The section's content bleeds onto this page; update page_end and
                # store the fragment so chunk_section can assign the correct page.
                current["page_end"] = p["page_num"]
                current["_end_page_slice"] = (p["page_num"], fragment)

        for i, (pos, sec_num, sec_title) in enumerate(new_matches):
            if current:
                sections.append(current)
            seen_sections.add(sec_num)
            end_pos = new_matches[i + 1][0] if i + 1 < len(new_matches) else len(page_text)
            title = re.sub(r"\|\s*\d+\s*$", "", sec_title).strip()
            section_text = page_text[pos:end_pos]
            current = {
                "section_number": sec_num,
                "section_title": title,
                "page_start": p["page_num"],
                "page_end": p["page_num"],
                "text": section_text,
                "_start_page_slice": section_text,
            }

    if current:
        sections.append(current)

    return sections


def naive_token_count(text: str) -> int:
    return int(len(text.split()) * 1.3)


def chunk_section(section: dict, section_pages: list[dict]) -> list[dict]:
    """
    Split a section into chunks at line boundaries.

    Lines are the natural unit from pdfplumber (never mid-sentence). Chunks
    accumulate lines until they approach CHUNK_TOKENS, then flush and begin
    a new chunk with OVERLAP_LINES lines of shared context.
    """
    # Collect (line, page_num) pairs across all pages in this section
    line_page: list[tuple[str, int]] = []
    for p in section_pages:
        for line in p["text"].split("\n"):
            if line.strip():
                line_page.append((line, p["page_num"]))

    if not line_page:
        return []

    chunks = []
    chunk_idx = 0
    start = 0

    while start < len(line_page):
        current_lines: list[str] = []
        current_tokens = 0
        page_start = line_page[start][1]
        page_end = line_page[start][1]

        i = start
        while i < len(line_page):
            line, pg = line_page[i]
            line_tokens = naive_token_count(line)
            if current_tokens + line_tokens > CHUNK_TOKENS and current_lines:
                break
            current_lines.append(line)
            current_tokens += line_tokens
            page_end = pg
            i += 1

        chunks.append({
            "section_number": section["section_number"],
            "section_title": section["section_title"],
            "chunk_index": chunk_idx,
            "page_start": page_start,
            "page_end": page_end,
            "content": "\n".join(current_lines),
        })

        if i == len(line_page):
            break

        # Overlap: step back OVERLAP_LINES from where we stopped
        start = max(start + 1, i - OVERLAP_LINES)
        chunk_idx += 1

    return chunks


def embed_batch(texts: list[str], retries: int = 3) -> list[list[float]]:
    for attempt in range(retries):
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
            return [r.embedding for r in resp.data]
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [Embed] Error (attempt {attempt+1}): {e} — retrying...")
                time.sleep(2 ** attempt)
            else:
                raise


def ensure_schema(cur) -> bool:
    """
    Create snap_sections table, add ts_content column and GIN index if missing.
    Returns True if ts_content is available, False if we lack privilege.
    """
    # snap_sections for parent-doc retrieval (graceful — warn but continue)
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS snap_sections (
                section_number TEXT PRIMARY KEY,
                section_title  TEXT,
                page_start     INT,
                page_end       INT,
                full_content   TEXT
            )
        """)
    except Exception as e:
        cur.connection.rollback()
        print(f"      WARNING: cannot create snap_sections ({e})")
        print("      Run as superuser:")
        print("        CREATE TABLE snap_sections (")
        print("          section_number TEXT PRIMARY KEY, section_title TEXT,")
        print("          page_start INT, page_end INT, full_content TEXT);")

    try:
        cur.execute("""
            ALTER TABLE snap_chunks
            ADD COLUMN IF NOT EXISTS ts_content tsvector
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS snap_chunks_ts_idx
            ON snap_chunks USING gin(ts_content)
        """)
        return True
    except Exception as e:
        cur.connection.rollback()

    # ALTER failed (insufficient privilege) — check if admin already added the column
    try:
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'snap_chunks' AND column_name = 'ts_content'
        """)
        if cur.fetchone():
            return True  # column exists; INSERT will populate it
    except Exception:
        pass

    print("      WARNING: ts_content column missing. BM25 hybrid search disabled.")
    print("      Run as superuser: ALTER TABLE snap_chunks ADD COLUMN ts_content tsvector;")
    print("                        CREATE INDEX snap_chunks_ts_idx ON snap_chunks USING gin(ts_content);")
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--clear", action="store_true", help="Delete existing rows first")
    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        print(f"PDF not found: {args.pdf}")
        sys.exit(1)

    print(f"[1/4] Extracting text from {args.pdf} (pdfplumber)...")
    pages = extract_pages(args.pdf)
    print(f"      {len(pages)} content pages")

    print("[2/4] Detecting sections...")
    sections = detect_sections(pages)
    print(f"      {len(sections)} sections found")

    print("[3/4] Chunking sections (line-boundary strategy)...")
    all_chunks = []
    for s in sections:
        start_slice = s.get("_start_page_slice")
        end_slice = s.get("_end_page_slice")  # (page_num, fragment_text) or None
        s_pages = []
        for p in pages:
            if p["page_num"] < s["page_start"] or p["page_num"] > s["page_end"]:
                continue
            if p["page_num"] == s["page_start"] and start_slice is not None:
                s_pages.append({"page_num": p["page_num"], "text": start_slice})
            elif end_slice and p["page_num"] == end_slice[0] and p["page_num"] != s["page_start"]:
                # Last page of section: only the fragment before the next section started
                s_pages.append({"page_num": p["page_num"], "text": end_slice[1]})
            else:
                s_pages.append(p)
        all_chunks.extend(chunk_section(s, s_pages))
    print(f"      {len(all_chunks)} chunks total")

    print("[4/4] Embedding and inserting into pgvector...")
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

    # ── Populate snap_sections (full text for parent-doc retrieval) ───────────
    print("      Populating snap_sections …")
    sections_inserted = 0
    sections_failed = False
    for s in sections:
        try:
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
            sections_inserted += 1
        except Exception as e:
            conn.rollback()
            print(f"      WARNING: snap_sections unavailable ({e})")
            print("      Parent-doc retrieval disabled until admin creates snap_sections.")
            sections_failed = True
            break
    if not sections_failed:
        conn.commit()
        print(f"      {sections_inserted} sections stored in snap_sections")
    else:
        print("      Skipped snap_sections population.")

    BATCH = 16
    inserted = 0
    for i in range(0, len(all_chunks), BATCH):
        batch = all_chunks[i : i + BATCH]
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
                    (
                        chunk["section_number"], chunk["section_title"],
                        chunk["chunk_index"], chunk["page_start"], chunk["page_end"],
                        chunk["content"], str(emb), chunk["content"],
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO snap_chunks
                        (section_number, section_title, chunk_index,
                         page_start, page_end, content, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                    """,
                    (
                        chunk["section_number"], chunk["section_title"],
                        chunk["chunk_index"], chunk["page_start"], chunk["page_end"],
                        chunk["content"], str(emb),
                    ),
                )
        conn.commit()
        inserted += len(batch)
        print(f"      {inserted}/{len(all_chunks)} chunks inserted", end="\r")

    conn.close()
    print(f"\nDone. {inserted} chunks indexed.")


if __name__ == "__main__":
    main()
