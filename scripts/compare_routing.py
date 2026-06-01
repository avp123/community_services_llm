#!/usr/bin/env python3
"""
Compare three section-routing strategies on the SNAP training questions.

Methods
-------
A  Section RAG    embed question → cosine-sim against per-section vectors
B  Summary LLM    LLM sees all 121 section summaries → picks 1-2
C  Hybrid         RAG shortlists top-5 → LLM re-ranks to 1-2 using summaries

Pass --rewrite to pre-process each question into official SNAP terminology
before routing — tests whether normalised queries improve retrieval.

No answer generation or judging — outputs a side-by-side routing table.

Usage:
    python scripts/compare_routing.py
    python scripts/compare_routing.py --rewrite            # with query rewriting
    python scripts/compare_routing.py --regen-summaries   # force re-generate summaries
    python scripts/compare_routing.py --regen-vectors     # force re-embed sections
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import psycopg
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

load_dotenv()

ROOT = Path(__file__).parent.parent
QUESTIONS_FILES = {
    "train": ROOT / "eval" / "questions" / "snap_train.json",
    "test":  ROOT / "eval" / "questions" / "snap_test.json",
    "val":   ROOT / "eval" / "questions" / "snap_val.json",
}
QUESTIONS_FILE  = QUESTIONS_FILES["train"]  # overridden by --split
SUMMARIES_FILE  = ROOT / "eval" / "section_summaries.json"
SEC_VECS_FILE   = ROOT / "eval" / "section_vectors.json"

RESOURCE_DB_URL  = os.getenv("RESOURCE_DB_URL")
EMBED_MODEL      = "text-embedding-3-large"
CHAT_MODEL       = "gpt-5-chat"
HYBRID_K         = 5   # RAG candidates passed to the re-ranker
ROUTE_MAX        = 3   # max sections any method may select
REWRITES_FILES = {
    "train": ROOT / "eval" / "rewritten_questions_train.json",
    "test":  ROOT / "eval" / "rewritten_questions_test.json",
    "val":   ROOT / "eval" / "rewritten_questions_val.json",
}
REWRITES_FILE      = REWRITES_FILES["train"]  # overridden by --split
SUMMARIES_V2_FILE  = ROOT / "eval" / "section_summaries_v2.json"
SUM_VECS_FILE      = ROOT / "eval" / "section_summary_vectors.json"
CONFUSED_THRESHOLD = 0.80   # draft-summary cosine-sim above this → contrastive pass

embed_client  = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
gpt4o_client  = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))   # for long-context summary gen
chat_client   = AzureOpenAI(
    api_key        = os.getenv("OPENAI_API_KEY_AZURE"),
    azure_endpoint = os.getenv("OPENAI_AZURE_ENDPOINT"),
    api_version    = "2024-12-01-preview",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

class ContentFilterError(Exception):
    pass


def _chat(messages, max_tokens: int = 20, retries: int = 5):
    for attempt in range(retries):
        try:
            return chat_client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                max_completion_tokens=max_tokens,
            )
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "too_many_requests" in exc_str.lower():
                wait = 10 * (2 ** attempt)
                print(f"\n  [rate limit] waiting {wait}s …", end="", flush=True)
                time.sleep(wait)
            elif "content_filter" in exc_str or (
                "400" in exc_str and "filtered" in exc_str.lower()
            ):
                raise ContentFilterError(exc_str) from exc
            else:
                raise
    raise RuntimeError("Exceeded retries after rate limit errors")


def _chat_gpt4o(messages, max_tokens: int = 400, retries: int = 5):
    """Standard OpenAI GPT-4o — used for long-context summary generation."""
    for attempt in range(retries):
        try:
            return gpt4o_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "too_many_requests" in exc_str.lower():
                wait = 10 * (2 ** attempt)
                print(f"\n  [rate limit] waiting {wait}s …", end="", flush=True)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Exceeded retries after rate limit errors")


def _embed(text: str) -> np.ndarray:
    vec = embed_client.embeddings.create(model=EMBED_MODEL, input=[text]).data[0].embedding
    arr = np.array(vec, dtype=np.float32)
    return arr / np.linalg.norm(arr)


def _parse_sections(raw: str) -> list[str]:
    """Extract section numbers like '3205', '3425', '3810b' from LLM reply."""
    return [
        s.strip()
        for s in re.split(r"[\s,]+", raw)
        if re.match(r"^\d+[a-z]?$", s.strip())
    ][:ROUTE_MAX]


# ── Query rewriting ───────────────────────────────────────────────────────────

_REWRITE_PROMPT = """\
Rewrite this question using Georgia SNAP policy terminology.
Replace colloquial terms with official ones. Preserve ALL key concepts — \
do not drop any aspect of the original question.
Be concise — one sentence.

Examples:
"does my undocumented wife affect my food stamps"
→ "citizenship/alien status effect on assistance unit composition and eligibility"

"do I have to work to get benefits"
→ "ABAWD work requirement exemptions and E&T participation"

"client didn't bring ID documents on time for their expedited case, can we still open their case"
→ "expedited case reactivation after postponed verification deadline expires §3110"

"customer got a one-time bonus from work, does that count as income"
→ "nonrecurring lump-sum payment excluded from countable income determination"

Question: {question}
Rewritten:"""


def load_rewrites(questions: list[dict], regen: bool = False) -> dict[str, str]:
    if not regen and REWRITES_FILE.exists():
        print(f"  [rewrites]  loaded from cache ({REWRITES_FILE.name})")
        return json.loads(REWRITES_FILE.read_text())

    print(f"  [rewrites]  rewriting {len(questions)} questions …")
    rewrites: dict[str, str] = {}
    for q in questions:
        resp = _chat([{"role": "user", "content": _REWRITE_PROMPT.format(question=q["question"])}], max_tokens=60)
        rewrites[q["id"]] = resp.choices[0].message.content.strip()
        print(f"    {q['id']}: {rewrites[q['id']][:80]}")

    REWRITES_FILE.write_text(json.dumps(rewrites, indent=2))
    print(f"  [rewrites]  saved → {REWRITES_FILE.name}")
    return rewrites


# ── Summaries ─────────────────────────────────────────────────────────────────

_SUMMARY_PROMPT = """\
You are building a routing index for the Georgia SNAP Policy Manual.

SECTION: {sec_num} — {title}

CONTENT:
{content}

Write a concise 4-6 sentence summary for routing purposes. Include:
- The specific policy topics, rules, and decision points covered
- Key forms, thresholds, time limits, charts, and terminology found in this section
- Notable NOT HERE IF conditions — scenarios that sound related but belong in a different section (cite section numbers)
- What caseworker questions this section can and cannot answer

Be concrete — avoid vague phrases like "covers various rules"."""


def load_summaries(sections: list[tuple], regen: bool = False,
                   db_url: str | None = None) -> dict[str, str]:
    if not regen and SUMMARIES_FILE.exists():
        print(f"  [summaries] loaded from cache ({SUMMARIES_FILE.name})")
        return json.loads(SUMMARIES_FILE.read_text())

    # Fetch full content when regenerating (sections list only has 5500-char excerpt)
    full_content: dict[str, str] = {}
    if db_url:
        conn = psycopg.connect(db_url)
        cur  = conn.cursor()
        cur.execute("SELECT section_number, full_content FROM snap_sections")
        for sec_num, content in cur.fetchall():
            full_content[sec_num] = content or ""
        conn.close()
        print(f"  [summaries] fetched full content for {len(full_content)} sections")

    print(f"  [summaries] generating for {len(sections)} sections via GPT-4o …")
    summaries: dict[str, str] = {}
    for i, (sec_num, title, excerpt) in enumerate(sections):
        content = full_content.get(sec_num, excerpt or "").strip()
        prompt = _SUMMARY_PROMPT.format(sec_num=sec_num, title=title, content=content)
        resp = _chat_gpt4o([{"role": "user", "content": prompt}], max_tokens=400)
        summaries[sec_num] = resp.choices[0].message.content.strip()
        print(f"    {i+1:3}/{len(sections)}  {sec_num:<8} {title[:55]}", end="\r", flush=True)
        time.sleep(0.1)

    print(f"\n  [summaries] saved → {SUMMARIES_FILE.name}")
    SUMMARIES_FILE.write_text(json.dumps(summaries, indent=2))
    return summaries


# ── Section vectors ───────────────────────────────────────────────────────────

def load_section_vectors(sections: list[tuple], regen: bool = False) -> dict[str, np.ndarray]:
    if not regen and SEC_VECS_FILE.exists():
        print(f"  [vectors]   loaded from cache ({SEC_VECS_FILE.name})")
        raw = json.loads(SEC_VECS_FILE.read_text())
        return {k: np.array(v, dtype=np.float32) for k, v in raw.items()}

    print(f"  [vectors]   embedding {len(sections)} sections …")
    vecs: dict[str, np.ndarray] = {}
    for i, (sec_num, title, content) in enumerate(sections):
        # Embed first 2000 chars — enough for a stable section-level representation
        text = f"Section {sec_num}: {title}\n\n{(content or '').strip()[:2000]}"
        vecs[sec_num] = _embed(text)
        print(f"    {i+1:3}/{len(sections)}  {sec_num:<8} {title[:55]}", end="\r")

    print(f"\n  [vectors]   saved → {SEC_VECS_FILE.name}")
    SEC_VECS_FILE.write_text(json.dumps({k: v.tolist() for k, v in vecs.items()}))
    return vecs


# ── V2 contrastive summaries ──────────────────────────────────────────────────

_SUMMARY_DRAFT_PROMPT = """\
You are building a routing index for the Georgia SNAP Policy Manual.
A router LLM will see this summary alongside {n_sections} other section \
summaries and must pick the 1-2 most relevant sections for a caseworker question.

SECTION: {sec_num} — {title}
CONTENT (excerpt):
{content}

Write a routing summary with EXACTLY this structure — no other text:

COVERS: [1 sentence — the specific policy this section owns, using the exact terms and form numbers from the text]

UNIQUE SIGNALS: [8-12 specific terms, form numbers, thresholds, or procedure names that appear HERE — comma separated]

NOT HERE IF: [2-4 conditions where a similar-sounding question belongs in a different section — cite section numbers if known]

ALSO HANDLES: [1-3 question types whose answer is here but whose phrasing would suggest a different section]"""

_SUMMARY_V2_PROMPT = """\
You are building a routing index for the Georgia SNAP Policy Manual.
A router LLM will see this summary alongside {n_sections} other section \
summaries and must pick the 1-2 most relevant sections for a caseworker question. \
Your summary must help the router discriminate — not just describe.

SECTION: {sec_num} — {title}
CONTENT (excerpt):
{content}

{neighbor_block}

Write a routing summary with EXACTLY this structure — no other text:

COVERS: [1 sentence — the specific policy this section owns, using the exact terms and form numbers from the text]

UNIQUE SIGNALS: [8-12 specific terms, form numbers, thresholds, or procedure names that appear HERE but not in neighboring sections — comma separated]

NOT HERE IF: [2-4 conditions where a similar-sounding question belongs in a different section — cite the section number explicitly for each]

ALSO HANDLES: [1-3 question types whose answer is here but whose phrasing would suggest a different section — include the misleading keywords and the section they'd wrongly route to]"""

_ROUTING_V2_PROMPT = """\
Select the 1-2 most relevant sections for this caseworker question.

Pay special attention to:
- UNIQUE SIGNALS: terms in the question that match a section's unique vocabulary
- NOT HERE IF: conditions that redirect to a different section
- ALSO HANDLES: question types that look like one section but belong in another

Question: {question}

Sections:
{summary_block}

Return JSON: {{"sections": ["NNNN", "NNNN"], "reasoning": "one sentence"}}"""


def _build_neighbor_block(sec_num: str, sec_meta: dict,
                           sec_vecs: dict[str, np.ndarray],
                           drafts: dict[str, str], n: int = 4) -> str:
    if sec_num not in sec_vecs:
        return ""
    target = sec_vecs[sec_num]
    scores = [(float(np.dot(target, v)), s) for s, v in sec_vecs.items() if s != sec_num]
    scores.sort(reverse=True)
    lines = ["NEIGHBORING SECTIONS (similar topic — your summary must distinguish this section from these):"]
    for _, num in scores[:n]:
        title = sec_meta[num][1] if num in sec_meta else num
        draft = drafts.get(num, "")
        first = draft.split(".")[0] + "." if draft else title
        lines.append(f"  §{num} ({title}): {first}")
    return "\n".join(lines)


def load_summaries_v2(sections: list[tuple], sec_vecs: dict[str, np.ndarray],
                       regen: bool = False) -> dict[str, str]:
    if not regen and SUMMARIES_V2_FILE.exists():
        print(f"  [summaries_v2] loaded from cache ({SUMMARIES_V2_FILE.name})")
        return json.loads(SUMMARIES_V2_FILE.read_text())

    n = len(sections)
    sec_meta = {s[0]: s for s in sections}

    print(f"  [summaries_v2] pass 1 — drafting {n} sections …")
    drafts: dict[str, str] = {}
    for i, (sec_num, title, content) in enumerate(sections):
        prompt = _SUMMARY_DRAFT_PROMPT.format(
            n_sections=n, sec_num=sec_num, title=title,
            content=(content or "").strip()[:5000],
        )
        resp = _chat([{"role": "user", "content": prompt}], max_tokens=400)
        drafts[sec_num] = resp.choices[0].message.content.strip()
        print(f"    {i+1:3}/{n}  {sec_num}", end="\r")

    print(f"\n  [summaries_v2] embedding {n} drafts to find confused pairs …")
    draft_vecs: dict[str, np.ndarray] = {}
    for sec_num, text in drafts.items():
        draft_vecs[sec_num] = _embed(text)

    keys = list(draft_vecs)
    confused: set[str] = set()
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if float(np.dot(draft_vecs[a], draft_vecs[b])) >= CONFUSED_THRESHOLD:
                confused.add(a)
                confused.add(b)
    print(f"  [summaries_v2] {len(confused)} sections need contrastive pass")

    final = dict(drafts)
    for i, sec_num in enumerate(sorted(confused)):
        _, title, content = sec_meta[sec_num]
        nb = _build_neighbor_block(sec_num, sec_meta, sec_vecs, drafts)
        prompt = _SUMMARY_V2_PROMPT.format(
            n_sections=n, sec_num=sec_num, title=title,
            content=(content or "").strip()[:5000],
            neighbor_block=nb,
        )
        resp = _chat([{"role": "user", "content": prompt}], max_tokens=500)
        final[sec_num] = resp.choices[0].message.content.strip()
        print(f"    {i+1:3}/{len(confused)}  {sec_num}", end="\r")

    print(f"\n  [summaries_v2] saved → {SUMMARIES_V2_FILE.name}")
    SUMMARIES_V2_FILE.write_text(json.dumps(final, indent=2))
    return final


def load_summary_vectors(summaries_v2: dict[str, str],
                          regen: bool = False) -> dict[str, np.ndarray]:
    if not regen and SUM_VECS_FILE.exists():
        print(f"  [sum_vecs]   loaded from cache ({SUM_VECS_FILE.name})")
        raw = json.loads(SUM_VECS_FILE.read_text())
        return {k: np.array(v, dtype=np.float32) for k, v in raw.items()}

    print(f"  [sum_vecs]   embedding {len(summaries_v2)} v2 summaries …")
    vecs: dict[str, np.ndarray] = {}
    for i, (sec_num, text) in enumerate(summaries_v2.items()):
        vecs[sec_num] = _embed(text)
        print(f"    {i+1:3}/{len(summaries_v2)}  {sec_num}", end="\r")

    print(f"\n  [sum_vecs]   saved → {SUM_VECS_FILE.name}")
    SUM_VECS_FILE.write_text(json.dumps({k: v.tolist() for k, v in vecs.items()}))
    return vecs


def _parse_json_sections(raw: str) -> list[str]:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        secs = [str(s).strip() for s in data.get("sections", [])]
        return [s for s in secs if re.match(r"^\d+[a-z]?$", s)][:ROUTE_MAX]
    except Exception:
        return _parse_sections(raw)


def route_summary_llm_v2(question: str, summaries_v2: dict[str, str],
                          sections: list[tuple]) -> list[str]:
    lines = [f"§{sec} ({title}):\n{summaries_v2.get(sec, title)}" for sec, title, _ in sections]
    prompt = _ROUTING_V2_PROMPT.format(
        question=question,
        summary_block="\n\n".join(lines),
    )
    resp = _chat([{"role": "user", "content": prompt}], max_tokens=80)
    return _parse_json_sections(resp.choices[0].message.content.strip())


def route_hybrid_v2(question: str, q_vec: np.ndarray,
                    vectors: dict[str, np.ndarray],
                    summaries_v2: dict[str, str],
                    sections: list[tuple]) -> list[str]:
    candidates = route_rag(q_vec, vectors, top_k=HYBRID_K)
    meta = {sec: title for sec, title, _ in sections}
    lines = [f"§{sec} ({meta.get(sec, sec)}):\n{summaries_v2.get(sec, meta.get(sec, sec))}"
             for sec in candidates]
    prompt = (
        f"You are routing a Georgia SNAP policy question. "
        f"These are the {HYBRID_K} most semantically similar sections.\n\n"
        "Pay special attention to:\n"
        "- UNIQUE SIGNALS: terms in the question that match a section's unique vocabulary\n"
        "- NOT HERE IF: conditions that redirect to a different section\n"
        "- ALSO HANDLES: question types that look like one section but belong in another\n\n"
        f"Question: {question}\n\n"
        "Candidates:\n"
        + "\n\n".join(lines)
        + '\n\nReturn JSON: {"sections": ["NNNN", "NNNN"], "reasoning": "one sentence"}'
    )
    resp = _chat([{"role": "user", "content": prompt}], max_tokens=80)
    selected = _parse_json_sections(resp.choices[0].message.content.strip())
    return selected if selected else candidates[:ROUTE_MAX]


# ── Routing methods ───────────────────────────────────────────────────────────

def route_rag(q_vec: np.ndarray, sec_vecs: dict[str, np.ndarray],
              top_k: int = ROUTE_MAX) -> list[str]:
    scores = {sec: float(np.dot(q_vec, v)) for sec, v in sec_vecs.items()}
    return sorted(scores, key=scores.__getitem__, reverse=True)[:top_k]


def route_summary_llm(question: str, summaries: dict[str, str],
                      sections: list[tuple]) -> list[str]:
    lines = []
    for sec_num, title, _ in sections:
        summary = summaries.get(sec_num, title)
        lines.append(f"{sec_num} | {title} | {summary}")

    prompt = (
        "You are routing a Georgia SNAP policy question to the most relevant sections.\n\n"
        "SECTIONS (number | title | summary):\n"
        + "\n".join(lines)
        + f"\n\nQUESTION: {question}\n\n"
        f"Which 1-{ROUTE_MAX} sections contain the specific policy needed to answer this question?\n"
        "Reply with ONLY the section number(s) comma-separated — no other text.\n"
        'Examples: "3205"  or  "3205, 3425"  or  "3810b"'
    )
    try:
        resp = _chat([{"role": "user", "content": prompt}])
    except ContentFilterError as exc:
        print(f"\n  [content filter] route_summary_llm skipping: {exc}", flush=True)
        return []
    return _parse_sections(resp.choices[0].message.content.strip())


def route_hybrid(question: str, q_vec: np.ndarray,
                 sec_vecs: dict[str, np.ndarray],
                 summaries: dict[str, str],
                 sections: list[tuple],
                 k: int = HYBRID_K,
                 orig_vec: np.ndarray | None = None) -> list[str]:
    # Stage A: cosine-sim top-k from rewritten query; union with top-k from original if provided
    scores_rw = {sec: float(np.dot(q_vec, v)) for sec, v in sec_vecs.items()}
    candidate_set = set(sorted(scores_rw, key=scores_rw.__getitem__, reverse=True)[:k])
    if orig_vec is not None:
        scores_orig = {sec: float(np.dot(orig_vec, v)) for sec, v in sec_vecs.items()}
        candidate_set |= set(sorted(scores_orig, key=scores_orig.__getitem__, reverse=True)[:k])
        candidates = sorted(candidate_set,
                            key=lambda s: max(scores_rw.get(s, 0), scores_orig.get(s, 0)),
                            reverse=True)
    else:
        candidates = sorted(candidate_set, key=scores_rw.__getitem__, reverse=True)

    meta = {sec: title for sec, title, _ in sections}
    lines = [
        f"{sec} | {meta.get(sec, sec)} | {summaries.get(sec, meta.get(sec, sec))}"
        for sec in candidates
    ]
    n_cands = len(candidates)
    prompt = (
        f"You are routing a Georgia SNAP policy question. "
        f"These are the {n_cands} most semantically similar sections:\n\n"
        "CANDIDATES (number | title | summary):\n"
        + "\n".join(lines)
        + f"\n\nQUESTION: {question}\n\n"
        f"Which 1-{ROUTE_MAX} of these sections actually contain the policy needed?\n"
        "Reply with ONLY section number(s), comma-separated — no other text."
    )
    try:
        resp = _chat([{"role": "user", "content": prompt}])
    except ContentFilterError as exc:
        print(f"\n  [content filter] route_hybrid falling back to RAG: {exc}", flush=True)
        return candidates[:ROUTE_MAX]
    selected = _parse_sections(resp.choices[0].message.content.strip())
    return selected if selected else candidates[:ROUTE_MAX]


# ── Full pipeline eval ────────────────────────────────────────────────────────

_ANSWER_SYSTEM = """\
You are an expert Georgia SNAP policy advisor helping caseworkers apply the \
Georgia SNAP Policy Manual correctly.

BEFORE ANSWERING:
1. Extract EVERY requirement, condition, exception, and procedural step relevant \
to this question from the retrieved sections.
2. Check the question's premises against policy: if the question states something \
as true (e.g. "since X applies..." or "the customer is a Y..."), verify whether \
that premise is actually correct under the retrieved policy. If a premise conflicts \
with or is incomplete relative to policy, flag it explicitly before continuing — \
do not silently accept a wrong or partial premise.
3. If the question describes a sequence of events (a case was approved, then \
something changed, then something else happened), reconstruct the timeline. \
Identify which policy rule governs each stage. A rule that closes or limits a case \
at one stage does not prevent a different rule from applying at a later stage.
4. Check each item: does it apply to the specific facts given, at the correct stage?
5. Write your answer addressing all applicable items.

Be specific. Cite section numbers. Address all conditions and exceptions.

After your answer, output EXACTLY this JSON on its own line — no other text after it:
{"confident": true, "search_query": ""}
OR, if the retrieved sections do NOT contain the specific policy needed:
{"confident": false, "search_query": "<concise SNAP policy term or topic to search next>"}"""

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
Give an overall score 1-5:
  5 = covers all rubric points, no errors
  4 = covers >=80% of points, at most 1 minor error
  3 = covers 50-80% of points, or 1 significant error
  2 = covers <50% of points, or multiple errors
  1 = wrong or actively misleading

Respond with valid JSON only, no markdown fences:
{{"overall_score": <1-5>, "rubric_hit": <n>, "rubric_total": <n>, \
"reasoning": "<1-2 sentence explanation>"}}"""


def _fetch_sections(sec_nums: list[str], cur) -> list[tuple[str, str, str]]:
    out = []
    for s in sec_nums:
        cur.execute(
            "SELECT section_number, section_title, full_content FROM snap_sections WHERE section_number = %s",
            (s,),
        )
        row = cur.fetchone()
        if row:
            out.append(row)
    return out


def _generate_answer(question: str, sec_rows: list[tuple[str, str, str]]) -> tuple[str, bool, str]:
    """Generate an answer and return (answer_text, confident, search_query).

    The model is instructed to append a JSON confidence block.  We strip it
    from the visible answer so the judge never sees it.
    """
    context = "\n\n".join(
        f"=== Section {n}: {t} ===\n{c[:40_000]}" for n, t, c in sec_rows
    )
    resp = _chat(
        [
            {"role": "system", "content": _ANSWER_SYSTEM},
            {"role": "user", "content": f"QUESTION: {question}\n\nPOLICY SECTIONS:\n{context}"},
        ],
        max_tokens=1200,
    )
    raw = resp.choices[0].message.content.strip()

    # Extract the trailing JSON confidence block (last {...} on the last line)
    confident, search_query = True, ""
    match = re.search(r'\{[^{}\n]*"confident"[^{}\n]*\}\s*$', raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            confident    = bool(data.get("confident", True))
            search_query = data.get("search_query", "").strip()
            raw = raw[:match.start()].rstrip()
        except Exception:
            pass  # malformed JSON — treat as confident, keep raw as-is

    return raw, confident, search_query


def _judge_one(q: dict, predicted: str) -> dict:
    prompt = _JUDGE_PROMPT.format(
        question=q["question"],
        correct_answer_summary=q["correct_answer_summary"],
        rubric_points="\n".join(f"- {p}" for p in q["key_rubric_points"]),
        common_errors="\n".join(f"- {e}" for e in q["common_errors"]),
        predicted_answer=predicted,
    )
    resp = _chat([{"role": "user", "content": prompt}], max_tokens=300)
    raw = resp.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def run_full_eval(method: str, questions: list[dict], summaries: dict,
                  sec_vecs: dict, sections: list[tuple], rewrites: dict,
                  hybrid_k: int, db_url: str, split: str = "train") -> None:
    conn = psycopg.connect(db_url)
    cur  = conn.cursor()

    MAX_GEN_ATTEMPTS = 3

    records, judge_results = [], []
    for q in questions:
        qid      = q["id"]
        question = q["question"]
        routed_q = rewrites.get(qid, question)
        q_vec    = _embed(routed_q)
        # Embed original question for union routing (only differs when rewriting)
        orig_vec = _embed(question) if routed_q != question else None

        # ── Routing + generation with retry ─────────────────────────────────
        current_q   = routed_q
        current_vec = q_vec
        final_routed: list[str] = []
        answer = ""
        for attempt in range(MAX_GEN_ATTEMPTS):
            if method == "summary_llm":
                routed = route_summary_llm(current_q, summaries, sections)
            else:
                routed = route_hybrid(current_q, current_vec, sec_vecs, summaries,
                                      sections, k=hybrid_k,
                                      orig_vec=orig_vec if attempt == 0 else None)
            final_routed = routed
            print(f"  {qid} [attempt {attempt+1}] → routed: {routed}")
            sec_rows = _fetch_sections(routed, cur)
            answer, confident, search_query = _generate_answer(question, sec_rows)

            if attempt < MAX_GEN_ATTEMPTS - 1 and not confident and search_query:
                print(f"       [not confident] search_query: {search_query!r} — re-routing …")
                current_q   = f"{routed_q} {search_query}"
                current_vec = _embed(current_q)
            else:
                break  # confident, no useful hint, or final attempt

        records.append({"id": qid, "question": question, "predicted_answer": answer,
                        "routed_sections": final_routed})

        print(f"       judging …")
        try:
            ev = _judge_one(q, answer)
            judge_results.append({
                "id": qid, "score": ev["overall_score"],
                "rubric_hit": ev.get("rubric_hit", "?"),
                "rubric_total": ev.get("rubric_total", "?"),
                "reasoning": ev.get("reasoning", ""),
            })
        except Exception as exc:
            print(f"       JUDGE ERROR: {exc}")

    conn.close()

    # Save answers
    out_dir = ROOT / "eval" / "answers"
    out_dir.mkdir(exist_ok=True)
    ans_path = out_dir / f"snap_{split}_{method}_k{hybrid_k}.json"
    ans_path.write_text(json.dumps({"questions": records}, indent=2))
    print(f"\n  Answers saved → {ans_path}")

    # Print judge report
    if not judge_results:
        return
    n = len(judge_results)
    avg = sum(r["score"] for r in judge_results) / n
    print(f"\n{'='*65}")
    print(f"  FULL EVAL — {method}  (hybrid_k={hybrid_k})")
    print(f"{'='*65}")
    print(f"  {'ID':<6} {'Score':>5}  Notes")
    print("  " + "-"*55)
    for r in sorted(judge_results, key=lambda x: x["id"]):
        print(f"  {r['id']:<6} {r['score']:>5}  {r['reasoning'][:55]}")
    print(f"\n  Questions : {n}")
    print(f"  Avg score : {avg:.2f} / 5")

    res_path = ROOT / "eval" / "results" / f"full_eval_{split}_{method}_k{hybrid_k}.json"
    res_path.write_text(json.dumps({"method": method, "hybrid_k": hybrid_k,
                                    "avg_score": round(avg, 3), "questions": judge_results}, indent=2))
    print(f"  Results   → {res_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--regen-summaries", action="store_true")
    parser.add_argument("--regen-vectors",   action="store_true")
    parser.add_argument("--rewrite",         action="store_true",
                        help="Pre-process questions into SNAP terminology before routing")
    parser.add_argument("--regen-rewrites",    action="store_true",
                        help="Force re-generate query rewrites even if cached")
    parser.add_argument("--v2",               action="store_true",
                        help="Use contrastive v2 summaries + structured routing prompt")
    parser.add_argument("--regen-summaries-v2", action="store_true",
                        help="Force re-generate v2 summaries")
    parser.add_argument("--regen-sum-vecs",   action="store_true",
                        help="Force re-embed v2 summary vectors")
    parser.add_argument("--hybrid-k",         type=int, default=HYBRID_K,
                        help=f"RAG candidates passed to Hybrid re-ranker (default {HYBRID_K})")
    parser.add_argument("--full-eval",        action="store_true",
                        help="Route → generate answers → judge for summary_llm and hybrid")
    parser.add_argument("--split",            choices=["train", "test", "val"], default="train",
                        help="Question split to use (default: train)")
    args = parser.parse_args()

    global QUESTIONS_FILE, REWRITES_FILE
    QUESTIONS_FILE = QUESTIONS_FILES[args.split]
    REWRITES_FILE  = REWRITES_FILES[args.split]

    questions = json.loads(QUESTIONS_FILE.read_text())["questions"]

    conn = psycopg.connect(RESOURCE_DB_URL)
    cur  = conn.cursor()
    cur.execute("""
        SELECT section_number, section_title, LEFT(full_content, 5500)
        FROM snap_sections ORDER BY section_number
    """)
    sections = cur.fetchall()   # [(sec_num, title, content_excerpt), ...]
    conn.close()

    print(f"\nLoaded {len(sections)} sections from snap_sections\n")

    print("[1/3] Summaries")
    summaries = load_summaries(sections, regen=args.regen_summaries,
                               db_url=RESOURCE_DB_URL if args.regen_summaries else None)

    print("\n[2/3] Section vectors")
    sec_vecs = load_section_vectors(sections, regen=args.regen_vectors)

    rewrites: dict[str, str] = {}
    if args.rewrite:
        print("\n[2.5/3] Query rewrites")
        rewrites = load_rewrites(questions, regen=args.regen_rewrites)

    print(f"\n[3/3] Routing {len(questions)} questions …\n")

    results = []
    for q in questions:
        qid, question = q["id"], q["question"]
        routed_q = rewrites.get(qid, question) if args.rewrite else question
        print(f"  {qid} …")
        q_vec    = _embed(routed_q)
        orig_vec = _embed(question) if routed_q != question else None
        rag     = route_rag(q_vec, sec_vecs)
        summary = route_summary_llm(routed_q, summaries, sections)
        hybrid  = route_hybrid(routed_q, q_vec, sec_vecs, summaries, sections,
                               k=args.hybrid_k, orig_vec=orig_vec)
        results.append({
            "id": qid,
            "question": question,
            "routed_question": routed_q if args.rewrite else None,
            "rag": rag,
            "summary_llm": summary,
            "hybrid": hybrid,
        })

    # ── Print table ────────────────────────────────────────────────────────────
    label = "Section RAG vs Summary LLM vs Hybrid" + (" (with rewrite)" if args.rewrite else "")
    print("\n" + "=" * 72)
    print(f"  ROUTING COMPARISON — {label}")
    print("=" * 72)
    if args.rewrite:
        print(f"  {'ID':<5}  {'Rewritten question':<45}")
        print("  " + "-" * 68)
        for r in results:
            print(f"  {r['id']:<5}  {(r['routed_question'] or '')[:65]}")
        print()
    print(f"  {'ID':<5}  {'RAG (cos-sim)':^20}  {'Summary LLM':^20}  {'Hybrid (RAG→LLM)':^20}")
    print("  " + "-" * 68)
    for r in results:
        rag_s = ", ".join(r["rag"])
        sum_s = ", ".join(r["summary_llm"])
        hyb_s = ", ".join(r["hybrid"])
        all_agree = (rag_s == sum_s == hyb_s)
        flag = "  ✓" if all_agree else ""
        print(f"  {r['id']:<5}  {rag_s:^20}  {sum_s:^20}  {hyb_s:^20}{flag}")

    # Agreement stats
    agree_all    = sum(1 for r in results if r["rag"] == r["summary_llm"] == r["hybrid"])
    agree_sb     = sum(1 for r in results if set(r["summary_llm"]) == set(r["hybrid"]))
    disagree_rag = sum(1 for r in results if set(r["rag"]) != set(r["summary_llm"]))
    print(f"\n  All three agree   : {agree_all}/{len(results)}")
    print(f"  Summary == Hybrid : {agree_sb}/{len(results)}")
    print(f"  RAG differs from Summary : {disagree_rag}/{len(results)}")

    # Retrieval scores (requires policy_sections field in questions)
    gold = {q["id"]: set(q.get("policy_sections", [])) for q in questions}
    if any(gold.values()):
        def hit(predicted: list[str], gold_set: set[str]) -> bool:
            return bool(set(predicted) & gold_set)
        def full_hit(predicted: list[str], gold_set: set[str]) -> bool:
            return gold_set.issubset(set(predicted))

        methods = [("RAG", "rag"), ("Summary LLM", "summary_llm"), ("Hybrid", "hybrid")]
        print(f"\n  {'Method':<14}  {'Any-hit':>8}  {'Full-hit':>9}")
        print("  " + "-" * 35)
        for label, key in methods:
            any_h  = sum(hit(r[key], gold[r["id"]]) for r in results if r["id"] in gold)
            full_h = sum(full_hit(r[key], gold[r["id"]]) for r in results if r["id"] in gold)
            n = sum(1 for r in results if r["id"] in gold)
            print(f"  {label:<14}  {any_h:>4}/{n}  {full_h:>5}/{n}")

        # Per-question detail
        print(f"\n  {'ID':<5}  {'Gold':<18}  {'RAG':>3}  {'Sum':>3}  {'Hyb':>3}")
        print("  " + "-" * 40)
        for r in results:
            if r["id"] not in gold:
                continue
            g = gold[r["id"]]
            r_hit = "✓" if hit(r["rag"], g) else "✗"
            s_hit = "✓" if hit(r["summary_llm"], g) else "✗"
            h_hit = "✓" if hit(r["hybrid"], g) else "✗"
            print(f"  {r['id']:<5}  {', '.join(sorted(g)):<18}  {r_hit:>3}  {s_hit:>3}  {h_hit:>3}")

    suffix = "_rewrite" if args.rewrite else ""
    out = ROOT / "eval" / "results" / f"routing_comparison{suffix}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\n  Saved → {out}")

    if args.full_eval:
        # reload questions with rubric fields for judging
        questions_with_rubric = json.loads(QUESTIONS_FILE.read_text())["questions"]
        for method in ("summary_llm", "hybrid"):
            print(f"\n\n{'='*65}")
            print(f"  FULL EVAL — {method}  (hybrid_k={args.hybrid_k})")
            print(f"{'='*65}\n")
            run_full_eval(
                method=method,
                questions=questions_with_rubric,
                summaries=summaries,
                sec_vecs=sec_vecs,
                sections=sections,
                rewrites=rewrites,
                hybrid_k=args.hybrid_k,
                db_url=RESOURCE_DB_URL,
                split=args.split,
            )
        return

    if not args.v2:
        return

    # ── V2: contrastive summaries + structured routing ────────────────────────
    print("\n\n" + "=" * 72)
    print("  V2 — Contrastive summaries + structured routing prompt")
    print("=" * 72)

    print("\n[V2-1] Contrastive summaries (two-pass)")
    summaries_v2 = load_summaries_v2(sections, sec_vecs, regen=args.regen_summaries_v2)

    print("\n[V2-2] Summary embeddings")
    sum_vecs = load_summary_vectors(summaries_v2, regen=args.regen_sum_vecs)

    print(f"\n[V2-3] Routing {len(questions)} questions …\n")

    results_v2 = []
    for q in questions:
        qid, question = q["id"], q["question"]
        routed_q = rewrites.get(qid, question) if args.rewrite else question
        print(f"  {qid} …")
        q_vec = _embed(routed_q)
        sum_v2   = route_summary_llm_v2(routed_q, summaries_v2, sections)
        hyb_v2a  = route_hybrid_v2(routed_q, q_vec, sec_vecs,  summaries_v2, sections)
        hyb_v2b  = route_hybrid_v2(routed_q, q_vec, sum_vecs,  summaries_v2, sections)
        results_v2.append({
            "id": qid,
            "question": question,
            "routed_question": routed_q if args.rewrite else None,
            "summary_llm_v2":       sum_v2,
            "hybrid_v2a_sec_vecs":  hyb_v2a,
            "hybrid_v2b_sum_vecs":  hyb_v2b,
        })

    # ── Print v2 table ─────────────────────────────────────────────────────────
    print(f"\n  {'ID':<5}  {'SumLLM-v2':^20}  {'Hybrid-v2a (sec)':^20}  {'Hybrid-v2b (sum)':^20}")
    print("  " + "-" * 68)
    for r in results_v2:
        s1 = ", ".join(r["summary_llm_v2"])
        s2 = ", ".join(r["hybrid_v2a_sec_vecs"])
        s3 = ", ".join(r["hybrid_v2b_sum_vecs"])
        print(f"  {r['id']:<5}  {s1:^20}  {s2:^20}  {s3:^20}")

    # ── Accuracy vs ground truth ───────────────────────────────────────────────
    gt = {q["id"]: set(q["policy_sections"])
          for q in json.loads(QUESTIONS_FILE.read_text())["questions"]}

    def hit(pred, gold):
        p = set(pred)
        norm = p | {s.rstrip("ab") for s in p if s[-1:] in "ab"}
        return bool(norm & gold)

    for key, label in [("summary_llm_v2", "SumLLM-v2"),
                        ("hybrid_v2a_sec_vecs", "Hybrid-v2a (sec vecs)"),
                        ("hybrid_v2b_sum_vecs", "Hybrid-v2b (sum vecs)")]:
        n_hit = sum(1 for r in results_v2 if hit(r[key], gt[r["id"]]))
        print(f"  {label:<25}: {n_hit}/{len(results_v2)} = {n_hit/len(results_v2)*100:.0f}%")

    out_v2 = ROOT / "eval" / "results" / f"routing_comparison_v2{suffix}.json"
    out_v2.write_text(json.dumps(results_v2, indent=2))
    print(f"\n  Saved → {out_v2}")


if __name__ == "__main__":
    main()
