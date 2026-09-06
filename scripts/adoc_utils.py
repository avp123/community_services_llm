"""Parsing/cleaning helpers for the AsciiDoc export of the Georgia SNAP Policy Manual.

Each file in snap_manual_sections/ is one policy section, e.g.:

    = 3205 Assistance Units
    :chapter-number: 3200
    :effective-date: June 2026
    :mt: MT-87
    :policy-number: 3205
    :policy-title: Assistance Units
    :previous-mt-number: MT-81

    include::partial$policy-header.adoc[]

    == Requirements
    ...

`:policy-number:` / `:policy-title:` also appear verbatim in the running header
block of every page of the companion PDF ("Policy Title: Assistance Units ...
Policy Number: 3205"), which is what lets us map each section back to its PDF
page range without re-parsing the PDF body text (see index_snap_adoc.py).
"""

import re

_INCLUDE_RE = re.compile(r"^include::.*\[.*\]\s*$", re.MULTILINE)
_ATTR_LINE_RE = re.compile(r"^:([\w-]+):\s*(.*)$")
_BLOCK_ATTR_RE = re.compile(r"^\[[^\]\n]*\]\s*$", re.MULTILINE)  # [#anchor], [horizontal,...], [cols=...]
_HEADING_RE = re.compile(r"^=+\s+(.*)$", re.MULTILINE)
_CAPTION_RE = re.compile(r"^\.(\S.*)$", re.MULTILINE)  # block title, e.g. ".Chart 3205.1 - ..."
_LABELED_LIST_RE = re.compile(r"^(\S.*?)::(?:\s+(.*))?$", re.MULTILINE)
_XREF_RE = re.compile(r"xref:([^\[\]]+?)\[([^\]]*)\]")
_TABLE_BLOCK_RE = re.compile(r"(?:^\[([^\]\n]*)\]\s*\n)?^\|===\s*\n(.*?)\n\|===\s*$", re.MULTILINE | re.DOTALL)
_CELL_MARKER_RE = re.compile(r"(?:\A|(?<=\s))(?:\^|[0-9]+\+?)?[as]?\|")
_ADMONITION_RE = re.compile(
    r"^\[(NOTE|WARNING|TIP|IMPORTANT|CAUTION)\]\s*\n====\s*\n(.*?)\n====\s*$",
    re.MULTILINE | re.DOTALL,
)
_ROLE_SPAN_RE = re.compile(r"\[\.[\w-]+\]([#*_])(.*?)\1")
_SUPERSCRIPT_RE = re.compile(r"\^(\w{1,4})\^")
_STRAY_DELIM_RE = re.compile(r"^={2,}\s*$", re.MULTILINE)


def humanize_slug(slug: str) -> str:
    """'appendix-a-financial-standards-overview' -> 'Appendix A: Financial Standards Overview'."""
    slug = slug.strip()
    m = re.match(r"^appendix-([a-z])-(.+)$", slug, re.IGNORECASE)
    if m:
        letter, rest = m.groups()
        return f"Appendix {letter.upper()}: {rest.replace('-', ' ').title()}"
    if re.match(r"^\d{4}[a-z]?$", slug):
        return f"Section {slug}"
    return slug.replace("-", " ").title()


def parse_adoc_file(text: str) -> dict:
    """Split a raw .adoc file into {title, frontmatter: dict, body: str}."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("= "):
        return {"title": "", "frontmatter": {}, "body": text}

    title = lines[0][2:].strip()
    i = 1
    frontmatter: dict[str, str] = {}
    while i < len(lines):
        m = _ATTR_LINE_RE.match(lines[i])
        if not m:
            break
        frontmatter[m.group(1)] = m.group(2).strip()
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    body = "\n".join(lines[i:])
    return {"title": title, "frontmatter": frontmatter, "body": body}


def _cols_count(cols_attr: str | None) -> int | None:
    if not cols_attr:
        return None
    m = re.search(r"cols=\"?([^,\"\]]+(?:,[^,\"\]]+)*)\"?", cols_attr)
    if not m:
        return None
    spec = m.group(1)
    m2 = re.match(r"^(\d+)\*", spec.strip())
    if m2:
        return int(m2.group(1))
    fields = [f for f in spec.split(",") if f.strip()]
    return len(fields) if fields else None


def _split_cells(table_body: str) -> list[str]:
    """Split raw PSV table content into cell strings, in reading order.

    A cell starts at a line beginning with an optional alignment/format spec
    (^, a, digit+, etc.) followed by `|`. Cell content — including embedded
    blank lines / multi-paragraph text — runs until the next such marker.
    """
    parts = _CELL_MARKER_RE.split("\n" + table_body)
    return [p.strip() for p in parts if p.strip()]


def adoc_table_to_prose(cols_attr: str | None, table_body: str) -> str:
    """Render an AsciiDoc PSV table as readable key: value prose lines."""
    cells = _split_cells(table_body)
    if not cells:
        return ""

    ncols = _cols_count(cols_attr)
    if not ncols:
        # Heuristic: header row is the text up to the first blank-line-separated
        # paragraph break in the raw block; count markers in that span instead.
        first_para = table_body.split("\n\n", 1)[0]
        guess = len(_split_cells(first_para))
        ncols = guess if 1 <= guess <= 6 else 2

    if ncols <= 1:
        return "\n".join(f"- {c}" for c in cells)

    rows = [cells[i:i + ncols] for i in range(0, len(cells), ncols)]
    if len(rows[-1]) != ncols:
        rows = rows[:-1]  # drop a trailing partial row (malformed/short table)
    if not rows:
        return "\n".join(f"- {c}" for c in cells)

    header, data_rows = rows[0], rows[1:]
    if not data_rows:
        # Single-row table (e.g. a TOC list rendered as [.noheader,cols=1*]) —
        # just list the cells.
        return "\n".join(f"- {c}" for c in cells)

    lines = []
    for row in data_rows:
        lines.append(" | ".join(f"{h}: {v}" if h else v for h, v in zip(header, row)))
    return "\n".join(lines)


def _replace_tables(body: str) -> str:
    def _sub(m):
        cols_attr, table_body = m.group(1), m.group(2)
        return adoc_table_to_prose(cols_attr, table_body)
    return _TABLE_BLOCK_RE.sub(_sub, body)


def _replace_xrefs(body: str) -> str:
    def _sub(m):
        target, link_text = m.group(1), m.group(2).strip()
        if link_text:
            return link_text
        # target is a filename-ish ref: "3600.adoc", "attachment$form-173.pdf", "3205.adoc#anchor"
        base = re.sub(r"^.*\$", "", target)          # drop "attachment$" prefix
        base = re.sub(r"#.*$", "", base)               # drop "#anchor" suffix
        base = re.sub(r"\.[a-zA-Z0-9]{2,4}$", "", base)  # drop file extension
        return humanize_slug(base)
    return _XREF_RE.sub(_sub, body)


def clean_adoc_body(body: str) -> str:
    """Strip AsciiDoc markup down to plain prose suitable for embedding/LLM context."""
    text = _INCLUDE_RE.sub("", body)
    text = _replace_tables(text)
    text = _replace_xrefs(text)
    text = _ADMONITION_RE.sub(lambda m: f"{m.group(1).title()}: {m.group(2).strip()}", text)
    text = _ROLE_SPAN_RE.sub(lambda m: m.group(2), text)
    text = _SUPERSCRIPT_RE.sub(lambda m: m.group(1), text)
    text = _BLOCK_ATTR_RE.sub("", text)
    text = _STRAY_DELIM_RE.sub("", text)
    text = _CAPTION_RE.sub(lambda m: m.group(1), text)
    text = _HEADING_RE.sub(lambda m: m.group(1), text)
    text = _LABELED_LIST_RE.sub(
        lambda m: f"{m.group(1)}: {m.group(2)}" if m.group(2) else f"{m.group(1)}:", text
    )
    # Collapse the blank-line litter left behind by stripped directive lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
