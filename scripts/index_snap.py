"""
Index the Georgia SNAP Policy Manual into pgvector.

Usage:
    python scripts/index_snap.py --pdf snap_manual.pdf [--clear]
"""

import argparse
import os
import re
import sys
import time

import psycopg
import PyPDF2
from dotenv import load_dotenv

load_dotenv()

RESOURCE_DB_URL = os.getenv("RESOURCE_DB_URL")
EMBED_MODEL = "text-embedding-3-large"
CHUNK_TOKENS = 500       # target tokens per chunk
OVERLAP_TOKENS = 80      # overlap between chunks
TOC_PAGES = 13           # skip table-of-contents pages at the start

from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SECTION_RE = re.compile(r"^\s*(\d{4})\s+([A-Z][^\n]{5,80})\s*$", re.MULTILINE)

# Matches section-header metadata lines that PDF extraction puts at the top of
# each section (policy title block, MT numbers, chapter/number lines).
# Stripping these before embedding so the vector represents actual policy
# content rather than administrative boilerplate.
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
    """Strip administrative metadata lines before embedding."""
    cleaned = _META_LINE_RE.sub("", text).strip()
    return cleaned if cleaned else text


def extract_pages(pdf_path: str) -> list[dict]:
    """Return list of {page_num, text} dicts, skipping TOC."""
    pages = []
    with open(pdf_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for i, page in enumerate(reader.pages):
            if i < TOC_PAGES:
                continue
            text = page.extract_text() or ""
            if text.strip():
                pages.append({"page_num": i + 1, "text": text})
    return pages


def detect_sections(pages: list[dict]) -> list[dict]:
    """
    Group pages into sections based on 4-digit section headers.
    Returns list of {section_number, section_title, page_start, page_end, text}.
    """
    sections = []
    current = None
    seen_sections: set[str] = set()  # prevents running page headers from re-triggering

    for p in pages:
        m = SECTION_RE.search(p["text"])
        if m and m.group(1) not in seen_sections:
            if current:
                # Text before the header on this page belongs to the previous section
                text_before = p["text"][:m.start()]
                if text_before.strip():
                    current["text"] += "\n" + text_before
                sections.append(current)
            seen_sections.add(m.group(1))
            # Clean title — strip page-number suffixes like "| 27"
            title = re.sub(r"\|\s*\d+\s*$", "", m.group(2)).strip()
            current = {
                "section_number": m.group(1),
                "section_title": title,
                "page_start": p["page_num"],
                "page_end": p["page_num"],
                "text": p["text"][m.start():],  # start from the header, not top of page
                # store separately so chunk_section can use the sliced text
                # instead of re-reading the full raw page
                "_start_page_slice": p["text"][m.start():],
            }
        elif current:
            current["text"] += "\n" + p["text"]
            current["page_end"] = p["page_num"]

    if current:
        sections.append(current)

    return sections


def naive_token_count(text: str) -> int:
    """Rough token estimate: words × 1.3."""
    return int(len(text.split()) * 1.3)


def chunk_section(section: dict, section_pages: list[dict]) -> list[dict]:
    """
    Split a section into overlapping chunks, tracking which page each chunk starts on.
    section_pages: [{page_num, text}] for the pages that belong to this section.
    """
    # Build a flat list of (word, page_num) so each chunk knows its real page.
    word_page_pairs: list[tuple[str, int]] = []
    for p in section_pages:
        for word in p["text"].split():
            word_page_pairs.append((word, p["page_num"]))

    if not word_page_pairs:
        return []

    chunk_words = int(CHUNK_TOKENS / 1.3)
    overlap_words = int(OVERLAP_TOKENS / 1.3)

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(word_page_pairs):
        end = min(start + chunk_words, len(word_page_pairs))
        pairs = word_page_pairs[start:end]
        chunk_text = " ".join(w for w, _ in pairs)
        # Use the page of the first word in this chunk as page_start
        chunk_page_start = pairs[0][1]
        chunk_page_end = pairs[-1][1]

        chunks.append({
            "section_number": section["section_number"],
            "section_title": section["section_title"],
            "chunk_index": chunk_index,
            "page_start": chunk_page_start,
            "page_end": chunk_page_end,
            "content": chunk_text,
        })
        if end == len(word_page_pairs):
            break
        start = end - overlap_words
        chunk_index += 1

    return chunks


def embed_batch(texts: list[str], retries: int = 3) -> list[list[float]]:
    """Embed a batch of texts with retry."""
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--clear", action="store_true", help="Delete existing rows first")
    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        print(f"PDF not found: {args.pdf}")
        sys.exit(1)

    print(f"[1/4] Extracting text from {args.pdf}...")
    pages = extract_pages(args.pdf)
    print(f"      {len(pages)} content pages")

    print("[2/4] Detecting sections...")
    sections = detect_sections(pages)
    print(f"      {len(sections)} sections found")

    print("[3/4] Chunking sections...")
    all_chunks = []
    for s in sections:
        # Collect pages within this section's range, substituting the correctly
        # sliced text for the start page so cross-page section boundaries don't
        # pull in trailing content from the preceding section.
        start_slice = s.get("_start_page_slice")
        s_pages = []
        for p in pages:
            if p["page_num"] < s["page_start"] or p["page_num"] > s["page_end"]:
                continue
            if p["page_num"] == s["page_start"] and start_slice is not None:
                s_pages.append({"page_num": p["page_num"], "text": start_slice})
            else:
                s_pages.append(p)
        all_chunks.extend(chunk_section(s, s_pages))
    print(f"      {len(all_chunks)} chunks total")

    print("[4/4] Embedding and inserting into pgvector...")
    conn = psycopg.connect(RESOURCE_DB_URL)
    cur = conn.cursor()

    if args.clear:
        cur.execute("DELETE FROM snap_chunks")
        conn.commit()
        print("      Cleared existing rows.")

    BATCH = 16
    inserted = 0
    for i in range(0, len(all_chunks), BATCH):
        batch = all_chunks[i : i + BATCH]
        texts = [clean_for_embedding(c["content"]) for c in batch]
        embeddings = embed_batch(texts)

        for chunk, emb in zip(batch, embeddings):
            cur.execute(
                """
                INSERT INTO snap_chunks
                    (section_number, section_title, chunk_index,
                     page_start, page_end, content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                """,
                (
                    chunk["section_number"],
                    chunk["section_title"],
                    chunk["chunk_index"],
                    chunk["page_start"],
                    chunk["page_end"],
                    chunk["content"],
                    str(emb),
                ),
            )
        conn.commit()
        inserted += len(batch)
        print(f"      {inserted}/{len(all_chunks)} chunks inserted", end="\r")

    conn.close()
    print(f"\nDone. {inserted} chunks indexed.")


if __name__ == "__main__":
    main()
