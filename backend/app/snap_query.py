"""RAG query pipeline for the Georgia SNAP Policy Manual."""

import json
import os
import re
from pathlib import Path

import numpy as np
import psycopg
from openai import AzureOpenAI, OpenAI

_USE_LOCAL_DB = os.getenv("USE_LOCAL_DB", "").lower() in ("1", "true", "yes")
RESOURCE_DB_URL = os.getenv("LOCAL_RESOURCE_DB_URL" if _USE_LOCAL_DB else "RESOURCE_DB_URL")

EMBED_MODEL = "text-embedding-3-large"
CHAT_MODEL = "gpt-5-chat"
TOP_K = 6
EXCERPT_CHARS = 2000
SECTION_COMPLETE_MAX_CHUNKS = 25  # complete sections with at most this many total chunks
PARENT_SECTION_MIN_CHUNKS = 30    # use snap_sections full text for sections above this threshold
RRF_K = 60                        # reciprocal rank fusion constant
SNIPPET_CHARS = 280   # shown in the source card quote
HIGHLIGHT_CHARS = 400  # used by PDF viewer for text-layer highlighting

# Section-routing retrieval (two-stage hybrid)
MAX_ROUTED_SECTIONS = 3      # how many sections the router may select
MAX_SECTION_CHARS = 40_000   # cap per section passed to the answer LLM (~10K tokens)
HYBRID_K = 5                 # RAG candidates per query passed to LLM re-ranker (union of rewritten+original = up to 10)

# Load section vectors and summaries for hybrid routing
_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
_VECTORS_FILE  = _EVAL_DIR / "section_vectors.json"
_SUMMARIES_FILE = _EVAL_DIR / "section_summaries.json"

def _load_section_index():
    vecs: dict[str, np.ndarray] = {}
    if _VECTORS_FILE.exists():
        for sec, v in json.loads(_VECTORS_FILE.read_text()).items():
            arr = np.array(v, dtype=np.float32)
            norm = np.linalg.norm(arr)
            vecs[sec] = arr / norm if norm > 0 else arr
    summaries: dict[str, str] = {}
    if _SUMMARIES_FILE.exists():
        summaries = json.loads(_SUMMARIES_FILE.read_text())
    return vecs, summaries

_SECTION_VECTORS, _SECTION_SUMMARIES = _load_section_index()

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
Never include a citation number like [1] in a tip — write it as a plain, self-contained sentence.

FLAGS:
FLAG[1]: <helpful tip in 1 plain sentence, no citation numbers>
FLAG[2]: <another tip>

FOLLOW-UP QUESTIONS — after FLAGS, ask exactly 2-3 short questions that would most help figure out if they
qualify. Only ask questions not already answered in this conversation. Each question must be answerable in
one short sentence (a number, a yes/no, or a couple words) — never a multi-part question. The reason must be
under 12 words and contain no citation numbers. Skip this block entirely if all relevant info has already
been provided.

QUESTIONS:
QUESTION[1]: <short plain-English question, answerable in one sentence> | <under-12-word plain reason>
QUESTION[2]: <another question> | <why>
"""

SYSTEM_PROMPT_EXPERT = (
    "You are a decision support system helping Georgia SNAP caseworkers make accurate eligibility determinations.\n\n"
    "Your role is two-fold: (1) answer policy questions accurately with citations, and (2) proactively identify case-specific issues the worker may miss.\n\n"
    "BEFORE ANSWERING:\n"
    "1. Extract EVERY requirement, condition, exception, and procedural step relevant to this question from the retrieved sections.\n"
    "2. Check the question's premises against policy: if the question states something as true (e.g. 'since X applies...' or 'the customer is a Y...'), verify whether that premise is actually correct under policy. If a premise conflicts with or is incomplete relative to policy, flag it explicitly before continuing — do not silently accept a wrong premise.\n"
    "3. If the question describes a sequence of events, reconstruct the timeline. Identify which policy rule governs each stage. A rule that closes or limits a case at one stage does not prevent a different rule from applying at a later stage.\n"
    "4. Check each extracted item: does it apply to the specific facts given, at the correct stage?\n"
    "5. Only then write your answer, ensuring every applicable item is addressed.\n\n"
    "This matters because policy sections routinely contain:\n"
    "- A primary rule plus secondary conditions that only apply in specific cases\n"
    "- Date-triggered rule changes ('effective X date')\n"
    "- Processing steps that follow from the primary determination\n"
    "- Exception handling (e.g. if a deduction can't be verified, process without it)\n"
    "- Requirements that apply when an Authorized Representative is involved\n"
    "Missing any of these is as wrong as missing the primary rule.\n\n"
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
    "Many users have never dealt with government benefits before, may be reading this on a phone, and may not "
    "read English as a first language or have much time or patience for a long answer.\n\n"
    "WRITE AT A 5TH-6TH GRADE READING LEVEL:\n"
    "- One idea per sentence. Average sentence length under 15 words.\n"
    "- No legal or bureaucratic words (e.g. do not say 'household composition' — say 'the people you live with "
    "and buy food with'). If a specific official term is unavoidable (like 'SNAP' or a form name), say it in "
    "plain words first, then give the official term in parentheses the first time.\n"
    "- No nested conditionals in one sentence. Split 'if X and Y unless Z' into separate short sentences or a list.\n\n"
    "ALWAYS START WITH A ONE-SENTENCE BOTTOM LINE — the direct answer to their question, bolded, before any "
    "explanation. Examples: '**Yes, you can likely get SNAP.**' or '**You'll need to send in two documents.**' "
    "If the honest answer is 'it depends,' say what it depends on in that same first sentence.\n\n"
    "Your goals:\n"
    "- Actually help them, not just recite rules. If there's something they can do, tell them.\n"
    "- Be warm but concise. Short sentences. One idea at a time.\n"
    "- When a question involves more than one step (applying, gathering documents, appealing, etc.), give the "
    "steps as a numbered list in the order to do them, not as a paragraph.\n"
    "- Name specific forms, websites, or phone numbers when they're relevant — don't be vague.\n"
    "- Bold the most important numbers, dates, and form names so they're easy to scan.\n"
    "- Do NOT add a 'Sources' section — citations are inline only.\n\n"
    + _SHARED_CITATION_RULES
    + _SIMPLE_FLAGS_RULES
)


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
    r"|Chapter:\s*(?:\d|Appendix)"
    r"|Policy Number:"
    r")[^\n]*",
    re.MULTILINE | re.IGNORECASE,
)

# Last-in-block metadata markers — we find the rightmost match within the
# first 800 chars to locate where the header ends in a no-newline chunk.
_META_END_RES = [
    re.compile(r'Policy Number:\s*(?:\d{4}|Appendix)'),
    re.compile(r'Chapter:\s*(?:\d+|Appendix)'),
    re.compile(r'Effective Date:\s*\d'),
    re.compile(r'MT-\d{2}-\d{4}'),
    re.compile(r'Updated or Reviewed in MT'),
    re.compile(r'SNAP Policy Manual'),
    re.compile(r'Georgia Division of Family'),
]


def _norm_text(text: str) -> str:
    """Normalize text for fuzzy matching — same logic as the frontend norm()."""
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9\s]', ' ', text.lower())).strip()


def _highlight_text(content: str, section_title: str = "") -> str:
    """Return first HIGHLIGHT_CHARS with section-header metadata stripped.

    chunk_section() joins words with spaces (no newlines), so _META_LINE_RE
    (anchored to ^ line-starts) can't strip inline metadata. When content
    starts with a 4-digit section number we locate the end of the header block
    by finding the last known metadata marker, then skip past any repeated
    running header using the known section_title length."""
    # Line-based stripping — works when content has real newlines
    cleaned = _META_LINE_RE.sub("", content).strip()
    working = cleaned or content

    # Still starts with a section number? Metadata was inline (no newlines).
    if re.match(r'^\d{4}\s', working):
        search_area = working[:800]
        meta_end = 0
        for pat in _META_END_RES:
            m = pat.search(search_area)
            if m:
                meta_end = max(meta_end, m.end())

        if meta_end > 0:
            rest = working[meta_end:].lstrip()
            # Skip the repeated "NNNN SectionTitle" running header that often
            # follows the metadata block. We know the title length, so we cap
            # the skip to avoid consuming actual content.
            if re.match(r'^\d{4}\s', rest) and section_title:
                skip_cap = len(section_title) + 3  # title length + small variation buffer
                m = re.match(rf'^\d{{4}}.{{0,{skip_cap}}}\s+', rest)
                if m:
                    rest = rest[m.end():]
            if len(rest) >= 30:
                return rest[:HIGHLIGHT_CHARS]

    return working[:HIGHLIGHT_CHARS]


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


_REWRITE_PROMPT = (
    "Rewrite this question using Georgia SNAP policy terminology. "
    "Replace colloquial terms with official ones. Be concise — one sentence.\n\n"
    "Examples:\n"
    '"does my undocumented wife affect my food stamps"\n'
    '→ "citizenship alien status impact on assistance unit eligibility"\n\n'
    '"do I have to work to get benefits"\n'
    '→ "ABAWD work requirement exemptions E&T participation"\n\n'
    "Question: {question}\nRewritten:"
)


def _rewrite_query(question: str) -> str:
    """Rewrite a colloquial question into SNAP policy terminology for better retrieval."""
    try:
        resp = chat_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": _REWRITE_PROMPT.format(question=question)}],
            max_completion_tokens=40,
        )
        rewritten = (resp.choices[0].message.content or "").strip()
        return rewritten or question
    except Exception:
        return question


def _route_to_sections(question: str, q_vec: np.ndarray, cur,
                       orig_vec: np.ndarray | None = None) -> list[str]:
    """Hybrid routing: union cosine-sim top-k (rewritten + original) → LLM re-ranker."""
    if not _SECTION_VECTORS:
        # Vectors not loaded — fall back to fetching section blurbs from DB
        cur.execute(
            "SELECT section_number, section_title, LEFT(full_content, 300) FROM snap_sections ORDER BY section_number"
        )
        rows = cur.fetchall()
        valid_ids = {n for n, t, b in rows}
        lines = ["{} | {} | {}".format(n, t, re.sub(r'\s+', ' ', (b or ''))[:200]) for n, t, b in rows]
        prompt = (
            "You are routing a Georgia SNAP policy question.\n\n"
            "SECTIONS (number | title | opening text):\n" + "\n".join(lines) +
            f"\n\nQUESTION: {question}\n\n"
            "Which 1-3 section numbers contain the specific policy needed?\n"
            "Reply with ONLY the section number(s), comma-separated.\n"
            'Examples: "3205"  or  "3205, 3425"  or  "3810b"'
        )
        resp = chat_client.chat.completions.create(
            model=CHAT_MODEL, messages=[{"role": "user", "content": prompt}], max_completion_tokens=20,
        )
        raw = resp.choices[0].message.content.strip()
        return [s.strip() for s in re.split(r"[\s,]+", raw) if s.strip() in valid_ids][:MAX_ROUTED_SECTIONS]

    # Stage A: cosine-sim top-k from rewritten query; union with top-k from original if different
    scores_rw = {sec: float(np.dot(q_vec, v)) for sec, v in _SECTION_VECTORS.items()}
    candidate_set = set(sorted(scores_rw, key=scores_rw.__getitem__, reverse=True)[:HYBRID_K])
    if orig_vec is not None:
        scores_orig = {sec: float(np.dot(orig_vec, v)) for sec, v in _SECTION_VECTORS.items()}
        candidate_set |= set(sorted(scores_orig, key=scores_orig.__getitem__, reverse=True)[:HYBRID_K])
        candidates = sorted(candidate_set,
                            key=lambda s: max(scores_rw.get(s, 0), scores_orig.get(s, 0)),
                            reverse=True)
    else:
        candidates = sorted(candidate_set, key=scores_rw.__getitem__, reverse=True)

    # Fetch titles for candidates
    cur.execute(
        "SELECT section_number, section_title FROM snap_sections WHERE section_number = ANY(%s)",
        (candidates,),
    )
    titles = {row[0]: row[1] for row in cur.fetchall()}

    # Stage B: LLM re-ranker over candidates only
    lines = [
        f"{sec} | {titles.get(sec, sec)} | {_SECTION_SUMMARIES.get(sec, '')}"
        for sec in candidates
    ]
    prompt = (
        f"You are routing a Georgia SNAP policy question. "
        f"These are the most semantically similar sections:\n\n"
        "CANDIDATES (number | title | summary):\n" + "\n".join(lines) +
        f"\n\nQUESTION: {question}\n\n"
        "Which 1-3 of these sections actually contain the policy needed to answer this question?\n"
        "Reply with ONLY section number(s), comma-separated — no other text."
    )
    try:
        resp = chat_client.chat.completions.create(
            model=CHAT_MODEL, messages=[{"role": "user", "content": prompt}], max_completion_tokens=20,
        )
        raw = resp.choices[0].message.content.strip()
        candidate_set = set(candidates)
        selected = [s.strip() for s in re.split(r"[\s,]+", raw) if s.strip() in candidate_set]
        return selected[:MAX_ROUTED_SECTIONS] if selected else candidates[:MAX_ROUTED_SECTIONS]
    except Exception:
        return candidates[:MAX_ROUTED_SECTIONS]


def _retrieve(embedding: list[float], question: str, routing_question: str, k: int = TOP_K) -> list[dict]:
    """Hybrid retrieval: cosine-sim top-k → LLM re-rank → fetch full section text."""
    conn = psycopg.connect(RESOURCE_DB_URL)
    cur = conn.cursor()

    # ── Stage 1: hybrid route (union of rewritten + original embeddings) ────────
    q_vec = np.array(embedding, dtype=np.float32)
    norm  = np.linalg.norm(q_vec)
    if norm > 0:
        q_vec = q_vec / norm
    # Embed original question for union routing when rewrite differs
    orig_vec = None
    if routing_question != question:
        orig_arr = np.array(_embed(question), dtype=np.float32)
        orig_norm = np.linalg.norm(orig_arr)
        orig_vec = orig_arr / orig_norm if orig_norm > 0 else orig_arr
    selected = _route_to_sections(routing_question, q_vec, cur, orig_vec=orig_vec)

    # ── Stage 2: fetch full section content ───────────────────────────────────
    sources = []
    for sec_num in selected:
        cur.execute(
            """
            SELECT section_number, section_title, page_start, page_end, full_content
            FROM snap_sections
            WHERE section_number = %s
            """,
            (sec_num,),
        )
        row = cur.fetchone()
        if not row:
            continue
        sec_number, sec_title, page_start, page_end, content = row
        content = content or ""
        sources.append({
            "index": len(sources) + 1,
            "section_number": sec_number,
            "section_title": sec_title,
            "page_start": page_start,
            "page_end": page_end,
            "chunk_index": None,
            "excerpt": content[:MAX_SECTION_CHARS],
            "snippet": _find_snippet(content, question),
            "highlight_text": _highlight_text(content, sec_title),
            "similarity": 1.0,
            "pdf_url": f"{PDF_URL}#page={page_start}",
            "routed": True,
        })

    conn.close()
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
            quotes[int(m.group(1))] = m.group(2).strip().strip('"\'“”‘’')
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


_PDF_PAGE_CACHE: dict[int, str] = {}
_PDF_BYTES_CACHE: list[bytes | None] = [None]  # mutable so we avoid module-level global

def _pdf_page_text(page_num: int) -> str:
    """Return pdfplumber-extracted text for a PDF page (1-indexed), cached.

    Falls back to fetching the PDF from the remote URL when the local file is
    absent (e.g. on the Azure deployment where the file isn't on disk).
    """
    if page_num in _PDF_PAGE_CACHE:
        return _PDF_PAGE_CACHE[page_num]
    text = ""
    try:
        import io
        import pdfplumber
        pdf_path = Path(__file__).resolve().parents[2] / "snap_manual.pdf"
        if pdf_path.exists():
            source = str(pdf_path)
        else:
            if _PDF_BYTES_CACHE[0] is None:
                import requests
                r = requests.get("https://www.peercopilot.com/snap_manual.pdf", timeout=30)
                r.raise_for_status()
                _PDF_BYTES_CACHE[0] = r.content
            source = io.BytesIO(_PDF_BYTES_CACHE[0]) if _PDF_BYTES_CACHE[0] else None
        if source is not None:
            with pdfplumber.open(source) as pdf:
                if 1 <= page_num <= len(pdf.pages):
                    text = pdf.pages[page_num - 1].extract_text() or ""
    except Exception:
        pass
    _PDF_PAGE_CACHE[page_num] = text
    return text


def _anchor_quotes(sources: list[dict]) -> None:
    """
    For each cited source, search snap_chunks to find which chunk contains the
    LLM quote and update page_start, highlight_text, and pdf_url in place.

    Falls back to scanning the section's full_content + PDF page texts when
    the quote lands in a chunk gap (e.g. the page-boundary fragment that the
    indexer appended to full_content but didn't create a separate chunk for).
    """
    conn = psycopg.connect(RESOURCE_DB_URL)
    cur = conn.cursor()
    try:
        for s in sources:
            quote = s.get("quote")
            if not quote or len(quote) < 15:
                continue

            # Mirror the frontend: strip editorial brackets and anchor on the
            # first segment before any ellipsis. Multi-"…" quotes join text
            # from different pages, so the full string never appears verbatim.
            quote_anchor = re.sub(r'\[[^\]]*\]', '', quote)
            quote_anchor = re.split(r'[…]|\.{3,}', quote_anchor)[0].strip()
            if len(quote_anchor) < 15:
                quote_anchor = quote
            norm_q = _norm_text(quote_anchor)

            # ── Stage 1: search chunks ────────────────────────────────────────
            cur.execute(
                "SELECT page_start, page_end, content FROM snap_chunks "
                "WHERE section_number = %s ORDER BY chunk_index",
                (s["section_number"],),
            )
            chunk_rows = cur.fetchall()
            found = False
            for frac in (1.0, 0.6, 0.4):
                if found:
                    break
                target = norm_q[:max(15, int(len(norm_q) * frac))]
                for chunk_page_start, chunk_page_end, content in chunk_rows:
                    if target in _norm_text(content):
                        # Chunk matched — now find the specific page within the
                        # chunk's range so the viewer opens the right page.
                        exact_page = chunk_page_start
                        if chunk_page_end and chunk_page_end > chunk_page_start:
                            for pg in range(chunk_page_start, chunk_page_end + 1):
                                if target in _norm_text(_pdf_page_text(pg)):
                                    exact_page = pg
                                    break
                        s["page_start"] = exact_page
                        s["highlight_text"] = quote
                        s["pdf_url"] = f"{PDF_URL}#page={exact_page}"
                        found = True
                        break
            if found:
                continue

            # ── Stage 2: chunk gap — scan PDF pages in section range ──────────
            # (quote is in full_content but missed by chunk boundaries)
            # The quote is in full_content but not in any chunk (indexing gap).
            # Scan each page from page_start to page_end (inclusive) to find it.
            cur.execute(
                "SELECT page_start, page_end FROM snap_sections WHERE section_number = %s",
                (s["section_number"],),
            )
            sec_row = cur.fetchone()
            if not sec_row:
                continue
            sec_page_start, sec_page_end = sec_row
            # Also look one page past page_end — the DB page_end may be stale.
            for pg in range(sec_page_start, (sec_page_end or sec_page_start) + 2):
                page_text = _pdf_page_text(pg)
                if not page_text:
                    continue
                norm_page = _norm_text(page_text)
                for frac in (1.0, 0.6, 0.4):
                    target = norm_q[:max(15, int(len(norm_q) * frac))]
                    if target in norm_page:
                        s["page_start"] = pg
                        # Use the quote directly: it's verbatim PDF text and the
                        # frontend normalizes before matching. Avoids the offset
                        # mismatch that comes from indexing into the normalized string.
                        s["highlight_text"] = quote
                        s["pdf_url"] = f"{PDF_URL}#page={pg}"
                        found = True
                        break
                if found:
                    break

            if found:
                continue

            # ── Stage 3: cross-section search ────────────────────────────────
            # The LLM cited the wrong section — the quote doesn't appear anywhere
            # in the cited section. Search all chunks to find the real source and
            # correct the reference so the right page opens with a good highlight.
            cur.execute(
                "SELECT sc.section_number, sc.section_title, sc.page_start, sc.page_end, sc.content "
                "FROM snap_chunks sc "
                "WHERE sc.section_number != %s "
                "ORDER BY sc.section_number, sc.chunk_index",
                (s["section_number"],),
            )
            for frac in (1.0, 0.6, 0.4):
                if found:
                    break
                target = norm_q[:max(15, int(len(norm_q) * frac))]
                for alt_sec, alt_title, chunk_ps, chunk_pe, content in cur.fetchall():
                    if target in _norm_text(content):
                        exact_page = chunk_ps
                        if chunk_pe and chunk_pe > chunk_ps:
                            for pg in range(chunk_ps, chunk_pe + 1):
                                if target in _norm_text(_pdf_page_text(pg)):
                                    exact_page = pg
                                    break
                        s["section_number"] = alt_sec
                        s["section_title"] = alt_title
                        s["page_start"] = exact_page
                        s["highlight_text"] = quote
                        s["pdf_url"] = f"{PDF_URL}#page={exact_page}"
                        found = True
                        break
                if not found:
                    cur.scroll(0, mode='absolute')  # reset cursor for next frac
    finally:
        conn.close()


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

    routing_question = _rewrite_query(question)
    embedding = _embed(routing_question)
    sources = _retrieve(embedding, question, routing_question)

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

    if mode == "simple":
        # Applicant mode never shows citation badges — strip any stray [N]
        # markers the model left in tips/questions text.
        flags = [re.sub(r"\[\d+\]", "", f).strip() for f in flags]
        for q in questions:
            q["question"] = re.sub(r"\[\d+\]", "", q["question"]).strip()
            q["reason"] = re.sub(r"\[\d+\]", "", q["reason"]).strip()

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

    # Update each source's page_start and highlight_text to the specific chunk
    # containing the LLM quote, rather than the section's first page.
    _anchor_quotes(cited_sources)

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
