"""RAG query pipeline for the Georgia SNAP Policy Manual."""

import os
import re

import psycopg
from openai import AzureOpenAI, OpenAI

_USE_LOCAL_DB = os.getenv("USE_LOCAL_DB", "").lower() in ("1", "true", "yes")
RESOURCE_DB_URL = os.getenv("LOCAL_RESOURCE_DB_URL" if _USE_LOCAL_DB else "RESOURCE_DB_URL")

EMBED_MODEL = "text-embedding-3-large"
CHAT_MODEL = "gpt-5-chat"
TOP_K = 6
EXCERPT_CHARS = 2000
SNIPPET_CHARS = 280   # shown in the source card quote

PDF_URL = "https://pamms.dhs.ga.gov/dfcs/_exports/snap-policy-manual.pdf"

embed_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

chat_client = AzureOpenAI(
    api_key=os.getenv("OPENAI_API_KEY_AZURE"),
    azure_endpoint=os.getenv("OPENAI_AZURE_ENDPOINT"),
    api_version="2024-12-01-preview",
)

# ── System prompts ────────────────────────────────────────────────────────────

_SHARED_CITATION_RULES = """\
CITATION RULES:
- Cite sources inline using [1], [2], etc. immediately after the relevant statement.
- Multiple citations are fine: [1][3]
- Do not guess — if the sources lack the answer, say so.

SOURCE_FACTS (append after your answer, no extra text, exactly this format):
SOURCE_FACTS:
FACT[1]: <one sentence — the specific figure, rule, or table row from source 1 most relevant to this question>
QUOTE[1]: <copy 1-2 complete sentences verbatim from source 1 that directly support your answer — must be exact text from the source, no paraphrasing>
FACT[2]: <one sentence for source 2>
QUOTE[2]: <verbatim 1-2 sentences from source 2>
(one FACT + QUOTE pair per cited source, in the same order)
"""

SYSTEM_PROMPT_EXPERT = (
    "You are a knowledgeable assistant helping Georgia SNAP caseworkers apply policy accurately.\n\n"
    "Answer questions using ONLY the provided manual sections. Be precise and cite policy language.\n\n"
    "RESPONSE STYLE:\n"
    "- Be concise and direct.\n"
    "- Bold key thresholds, income limits, and dates using **markdown bold**.\n"
    "- Use bullet points for lists of conditions or requirements.\n"
    "- Do NOT add a 'Sources' section — citations are inline only.\n\n"
    + _SHARED_CITATION_RULES
)

SYSTEM_PROMPT_SIMPLE = (
    "You are a friendly assistant helping people understand if they might qualify for Georgia SNAP food benefits.\n\n"
    "Answer questions using ONLY the provided manual sections. Use plain, everyday language.\n\n"
    "RESPONSE STYLE:\n"
    "- Write as if explaining to someone with no government experience.\n"
    "- Avoid acronyms — spell them out (e.g. 'Supplemental Nutrition Assistance Program (SNAP)').\n"
    "- Use short sentences. Lead with the direct answer, then explain why.\n"
    "- Bold the most important numbers or dates.\n"
    "- Do NOT add a 'Sources' section — citations are inline only.\n\n"
    + _SHARED_CITATION_RULES
)


def _embed(text: str) -> list[float]:
    return embed_client.embeddings.create(
        model=EMBED_MODEL, input=[text]
    ).data[0].embedding


def _find_snippet(content: str, question: str) -> str:
    """
    Return the most data-rich 2-3 lines from a chunk.
    Scores line-by-line so table rows (no sentence punctuation) are found correctly.
    """
    lines = [l for l in content.split('\n') if l.strip()]
    if not lines:
        return content[:SNIPPET_CHARS]

    q_words = set(re.sub(r'[^\w\s]', '', question.lower()).split())

    def score(line: str) -> int:
        s = line.count('$') * 5
        s += len(re.findall(r'\b\d{3,}\b', line))
        s += line.count('%') * 2
        s += sum(2 for w in q_words if w in line.lower())
        return s

    scores = [score(l) for l in lines]
    best_i = max(range(len(scores)), key=lambda i: scores[i])

    # Include one line above (often a header/label) then fill up to SNIPPET_CHARS
    start = max(0, best_i - 1)
    result, chars = [], 0
    for line in lines[start:]:
        result.append(line)
        chars += len(line) + 1
        if chars >= SNIPPET_CHARS:
            break

    return '\n'.join(result).strip()


def _retrieve(embedding: list[float], question: str, k: int = TOP_K) -> list[dict]:
    conn = psycopg.connect(RESOURCE_DB_URL)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT section_number, section_title, page_start, page_end, content,
               1 - (embedding <=> %s::vector) AS similarity
        FROM snap_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (str(embedding), str(embedding), k),
    )
    rows = cur.fetchall()
    conn.close()

    sources = []
    for i, row in enumerate(rows):
        content = row[4]
        sources.append(
            {
                "index": i + 1,
                "section_number": row[0],
                "section_title": row[1],
                "page_start": row[2],
                "page_end": row[3],
                "excerpt": content[:EXCERPT_CHARS],
                "snippet": _find_snippet(content, question),
                "similarity": round(float(row[5]), 4),
                "pdf_url": f"{PDF_URL}#page={row[2]}",
            }
        )
    return sources


def _parse_facts(text: str) -> tuple[str, dict[int, str], dict[int, str]]:
    """
    Split LLM output into (answer, {index: key_fact}, {index: verbatim_quote}).
    Handles FACT[N]/QUOTE[N] and bare FACT N/QUOTE N since models vary.
    """
    block = re.search(r'SOURCE_FACTS:\s*\n(.*)', text, re.DOTALL | re.IGNORECASE)
    key_facts: dict[int, str] = {}
    quotes: dict[int, str] = {}
    if block:
        answer = text[:block.start()].strip()
        body = block.group(1)
        for m in re.finditer(r'FACT\[?(\d+)\]?:\s*(.+)', body):
            key_facts[int(m.group(1))] = m.group(2).strip()
        for m in re.finditer(r'QUOTE\[?(\d+)\]?:\s*(.+)', body):
            quotes[int(m.group(1))] = m.group(2).strip()
    else:
        answer = text.strip()
    return answer, key_facts, quotes


def _order_by_appearance(cited_sources: list[dict], answer: str) -> list[dict]:
    """Re-sort sources by first appearance of their citation in the answer text."""
    def first_pos(s):
        m = re.search(rf'\[{s["index"]}\]', answer)
        return m.start() if m else 999999
    return sorted(cited_sources, key=first_pos)


def query_snap(
    question: str,
    conversation_history: list | None = None,
    mode: str = "expert",
) -> dict:
    """
    Run the full RAG pipeline for a SNAP policy question.

    Args:
        mode: "expert" (caseworker language) or "simple" (plain English for applicants)

    Returns:
        {"answer": str, "sources": list[dict]}
    """
    conversation_history = conversation_history or []
    system_prompt = SYSTEM_PROMPT_SIMPLE if mode == "simple" else SYSTEM_PROMPT_EXPERT

    embedding = _embed(question)
    sources = _retrieve(embedding, question)

    sources_block = "\n\n".join(
        f"[{s['index']}] Section {s['section_number']}: {s['section_title']} "
        f"(Page {s['page_start']})\n{s['excerpt']}"
        for s in sources
    )

    messages = [
        {"role": "system", "content": system_prompt + "\n\nSOURCES:\n" + sources_block}
    ]
    for msg in conversation_history:
        messages.append(msg)
    messages.append({"role": "user", "content": question})

    response = chat_client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        max_tokens=1200,
    )
    raw = response.choices[0].message.content or ""

    answer, key_facts, quotes = _parse_facts(raw)

    cited = {int(m) for m in re.findall(r"\[(\d+)\]", answer)}
    cited_sources = [s for s in sources if s["index"] in cited]
    cited_sources = _order_by_appearance(cited_sources, answer)

    # Re-number sources 1..N in appearance order so badge numbers match cards
    index_map: dict[int, int] = {}
    for new_i, s in enumerate(cited_sources, 1):
        index_map[s["index"]] = new_i
        s["key_fact"] = key_facts.get(s["index"])
        s["quote"] = quotes.get(s["index"])
        s["index"] = new_i

    # Rewrite [N] in answer to match new numbering
    def replace_cite(m):
        old = int(m.group(1))
        return f"[{index_map[old]}]" if old in index_map else m.group(0)
    answer = re.sub(r"\[(\d+)\]", replace_cite, answer)

    return {"answer": answer, "sources": cited_sources}
