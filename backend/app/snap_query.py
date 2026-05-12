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

_EXPERT_FLAGS_RULES = """\

DECISION SUPPORT — after SOURCE_FACTS, scan the full conversation for case facts and flag issues the worker may overlook.
Watch especially for:
- Self-employment/gig income: net profit after expenses, averaged over 12 months (or since start if shorter)
- Student household members: most 18-49 students are ineligible unless they meet a specific exemption (working 20+ hrs/wk, caring for a child under 6, etc.)
- Elderly or disabled members: excess medical deductions (over $35/month) are commonly missed
- Shelter deduction: verify excess shelter costs (rent + utilities above 50% of net income) are being applied
- Categorical eligibility: SSI, TANF, or GA Works receipt may confer automatic or broad-based eligibility
- ABAWD requirements: able-bodied adults 18-49 without dependents — confirm work requirement compliance or exemption
- Paystub/verification gaps: paystubs must cover required period; gaps = incomplete verification
Only flag issues grounded in facts from this conversation. If no case facts have been shared, note 1-2 common watch-outs for this question's topic. Include 1-4 flags; omit if nothing substantive to flag.

FLAGS:
FLAG[1]: <specific actionable concern in 1 sentence>
FLAG[2]: <another concern>
"""

_SIMPLE_FLAGS_RULES = """\

HELPFUL TIPS — after SOURCE_FACTS, add 1-3 tips the person might not know:
- Benefits or deductions they may qualify for (expedited SNAP, categorical eligibility, utility allowances)
- Documents to gather before applying
- Common misconceptions to correct

FLAGS:
FLAG[1]: <helpful tip in 1 plain sentence>
FLAG[2]: <another tip>

FOLLOW-UP QUESTIONS — after FLAGS, ask 1-3 specific questions that would help determine eligibility more precisely.
Only ask questions not already answered in this conversation. Explain why each matters in plain language.
Skip this block entirely if all relevant info has already been provided.

QUESTIONS:
QUESTION[1]: <short plain-English question> | <1-sentence plain reason why this matters>
QUESTION[2]: <another question> | <why>
"""

SYSTEM_PROMPT_EXPERT = (
    "You are a decision support system helping Georgia SNAP caseworkers make accurate eligibility determinations.\n\n"
    "Your role is two-fold: (1) answer policy questions accurately with citations, and (2) proactively identify case-specific issues the worker may miss.\n\n"
    "RESPONSE STYLE:\n"
    "- Be concise and direct.\n"
    "- Bold key thresholds, income limits, and dates using **markdown bold**.\n"
    "- Use bullet points for lists of conditions or requirements.\n"
    "- Do NOT add a 'Sources' section — citations are inline only.\n\n"
    + _SHARED_CITATION_RULES
    + _EXPERT_FLAGS_RULES
)

SYSTEM_PROMPT_SIMPLE = (
    "You are a friendly, knowledgeable guide helping people navigate Georgia SNAP (food assistance) benefits.\n"
    "Many users have never dealt with government benefits before and may not know where to start.\n\n"
    "Your goals:\n"
    "- Actually help them, not just recite rules. If there's something they can do, tell them.\n"
    "- Use plain, everyday language. No jargon. Spell out acronyms the first time.\n"
    "- Be warm but concise. Short sentences. One idea at a time.\n"
    "- Name specific forms, websites, or phone numbers when they're relevant — don't be vague.\n"
    "- Bold the most important numbers, dates, and form names so they're easy to scan.\n"
    "- Do NOT add a 'Sources' section — citations are inline only.\n\n"
    + _SHARED_CITATION_RULES
    + _SIMPLE_FLAGS_RULES
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


def _parse_facts(
    text: str,
) -> tuple[str, dict[int, str], dict[int, str], list[str], list[dict]]:
    """
    Split LLM output into (answer, key_facts, quotes, flags, questions).

    Everything after SOURCE_FACTS: is treated as a metadata block and scanned
    for FACT/QUOTE/FLAG/QUESTION patterns regardless of what section headers
    the model uses (it varies: FLAGS, HELPFUL TIPS, FOLLOW-UP QUESTIONS, etc.).
    """
    key_facts: dict[int, str] = {}
    quotes: dict[int, str] = {}
    flags: list[str] = []
    questions: list[dict] = []

    block = re.search(r'SOURCE_FACTS:\s*\n?(.*)', text, re.DOTALL | re.IGNORECASE)
    if block:
        answer = text[:block.start()].strip()
        meta = block.group(1)

        for m in re.finditer(r'FACT\[?(\d+)\]?:\s*(.+)', meta):
            key_facts[int(m.group(1))] = m.group(2).strip()
        for m in re.finditer(r'QUOTE\[?(\d+)\]?:\s*(.+)', meta):
            quotes[int(m.group(1))] = m.group(2).strip()
        # FLAG without a pipe (not a QUESTION)
        for m in re.finditer(r'^FLAG\[?\d*\]?:\s*(.+)', meta, re.MULTILINE | re.IGNORECASE):
            val = m.group(1).strip()
            if '|' not in val:
                flags.append(val)
        # QUESTION must contain a pipe separating question from reason
        for m in re.finditer(r'^QUESTION\[?\d*\]?:\s*(.+?)\s*\|\s*(.+)', meta, re.MULTILINE | re.IGNORECASE):
            questions.append({"question": m.group(1).strip(), "reason": m.group(2).strip()})
    else:
        answer = text.strip()

    return answer, key_facts, quotes, flags, questions


_FORM_RESOURCES = {
    "297a": {"url": "https://dfcs.georgia.gov/document/document/297a/download",                                          "label": "Download Form 297A (Rights & Responsibilities)"},
    "297":  {"url": "https://dfcs.georgia.gov/document/document/297/download",                                           "label": "Download Form 297 (SNAP Application)"},
    "298":  {"url": "https://dfcs.georgia.gov/media/16446/download",                                                     "label": "Download Form 298 (Senior SNAP Application)"},
    "508":  {"url": "https://dfcs.georgia.gov/document/document/form-508-food-stampmedicaidtanf-renewal-form/download",  "label": "Download Form 508 (Renewal Form)"},
    "528":  {"url": "https://dfcs.georgia.gov/document/document/528-english/download",                                   "label": "Download Form 528 (Periodic Report)"},
    "846":  {"url": "https://pamms.dhs.ga.gov/dfcs/snap/_attachments/form-846.pdf",                                      "label": "Download Form 846 (Change Report)"},
    "841":  {"url": "https://dfcs.georgia.gov/document/document/form-841-food-loss-replacement-form/download",           "label": "Download Form 841 (Food Loss Replacement)"},
    "880":  {"url": "https://pamms.dhs.ga.gov/dfcs/snap/_attachments/form-880.pdf",                                      "label": "Download Form 880 (Verification Checklist)"},
    "821":  {"url": "https://pamms.dhs.ga.gov/dfcs/snap/_attachments/form-821.pdf",                                      "label": "Download Form 821 (Shelter Cost Statement)"},
    "104":  {"url": "https://pamms.dhs.ga.gov/dfcs/snap/_attachments/form-104.pdf",                                      "label": "Download Form 104 (Child Care Expense Statement)"},
    "173":  {"url": "https://pamms.dhs.ga.gov/dfcs/snap/_attachments/form-173.pdf",                                      "label": "Download Form 173 (Verification Checklist)"},
    "47":   {"url": "https://dfcs.georgia.gov/document/document/snap-form-47-english/download",                          "label": "Download Form 47 (SNAP Info Brochure)"},
    "1":    {"url": "https://pamms.dhs.ga.gov/dfcs/snap/_attachments/form-1.pdf",                                        "label": "Download OSAH Form 1 (Fair Hearing Request)"},
}

_TOPIC_RESOURCES = [
    (r'\bfair hearing\b|\bappeal\b|\bOSAH\b|\bdenied\b',
     {"url": "https://pamms.dhs.ga.gov/dfcs/snap/_attachments/form-1.pdf", "label": "Request a Fair Hearing (OSAH Form 1)"}),
    (r'\brenew\b|\brenewal\b|\brecertif',
     {"url": "https://dfcs.georgia.gov/document/document/form-508-food-stampmedicaidtanf-renewal-form/download", "label": "Download Renewal Form (Form 508)"}),
    (r'\bfood loss\b|\bspoiled\b|\bpower outage\b',
     {"url": "https://dfcs.georgia.gov/document/document/form-841-food-loss-replacement-form/download", "label": "Request Food Loss Replacement (Form 841)"}),
    (r'\bsenior snap\b|\belderly\b|\bage 60\b',
     {"url": "https://dfcs.georgia.gov/media/16446/download", "label": "Senior SNAP Application (Form 298)"}),
    (r'\bebt\b|\bbalance\b|\bpin\b',
     {"url": "https://www.connectebt.com/ebtconnect/recipient/GA/", "label": "Check Your EBT Balance"}),
    (r'\bapply\b|\bapplication\b|\bhow to (get|apply)\b',
     {"url": "https://www.gateway.ga.gov/access/", "label": "Apply Online at Georgia Gateway"}),
    (r'\bgateway\b',
     {"url": "https://www.gateway.ga.gov/access/", "label": "Georgia Gateway — Apply or Manage Benefits"}),
    (r'\blegal aid\b|\bright to\b|\bappeal\b',
     {"url": "https://www.georgialegalaid.org/resource/what-should-i-know-about-food-stamps-snap", "label": "Georgia Legal Aid — SNAP Rights"}),
]

def _pick_resource(answer: str) -> dict | None:
    """Return the most relevant form/resource link based on the answer content."""
    # Form 297A must be checked before 297 (longer match first)
    m = re.search(r'\bForm\s+(\d+[A-Za-z]?)\b', answer, re.IGNORECASE)
    if m:
        key = m.group(1).lower()
        if key in _FORM_RESOURCES:
            return _FORM_RESOURCES[key]
    for pattern, resource in _TOPIC_RESOURCES:
        if re.search(pattern, answer, re.IGNORECASE):
            return resource
    return {"url": "https://dfcs.georgia.gov/services/snap", "label": "Georgia DFCS — SNAP"}


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
) -> tuple[dict, int]:
    """
    Run the full RAG pipeline for a SNAP policy question.

    Args:
        mode: "expert" (caseworker language) or "simple" (plain English for applicants)

    Returns:
        ({"answer": str, "sources": list[dict], ...}, azure_chat_completion_tokens)
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
        max_completion_tokens=1600,
    )
    raw = response.choices[0].message.content or ""
    usage_tokens = 0
    u = getattr(response, "usage", None)
    if u is not None:
        usage_tokens = int(getattr(u, "total_tokens", 0) or 0)

    answer, key_facts, quotes, flags, questions = _parse_facts(raw)

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

    resource = _pick_resource(answer) if mode == "simple" else None
    return (
        {
            "answer": answer,
            "sources": cited_sources,
            "flags": flags,
            "questions": questions,
            "resource": resource,
        },
        usage_tokens,
    )
