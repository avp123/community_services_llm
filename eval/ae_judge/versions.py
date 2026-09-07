"""
The 5 system-prompt versions being compared, loaded from
debugging/data/version_a.md .. version_e.md.

- A: current production PeerCoPilot prompt (balanced: resources + light
  peer-support framing, non-directive). Note this is byte-for-byte the same
  text `get_default_peer_copilot_system_prompt("cspnj")` returns, so version A
  is run via construct_response(version="new", organization="cspnj") with NO
  system_prompt_base override -- exercising the real default code path rather
  than a copy of the string.
- B: vanilla baseline (construct_response(version="vanilla")). version_b.md
  matches backend/app/submodules.py's _VANILLA_SYSTEM_PROMPT exactly.
- C: information-only assistant, no peer-support coaching.
- D: coaching-heavy "PeerSupport Copilot" -- questions, tradeoffs, example
  language.
- E: a hybrid drafted to keep D's step-by-step/options structure while adding
  concrete resources near the end (see debugging/data/annotation_packet.md).

All run through the real production pipeline (backend.app.submodules.
construct_response) with full RAG + tools, organization="cspnj", so that
retrieval/tool-use behavior isn't a confound -- only the system prompt varies.
"""
import os

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "debugging",
    "data",
)


ORGANIZATION = "cspnj"


def _load(name: str) -> str:
    with open(os.path.join(_DATA_DIR, name), encoding="utf-8") as f:
        text = f.read().strip()
    # construct_response's system_prompt_base is used verbatim (no .format()
    # call on the caller's behalf), so substitute {organization} here.
    return text.format(organization=ORGANIZATION)


VERSION_PROMPTS = {
    "A": None,  # use construct_response's own default for organization="cspnj"
    "B": None,  # use construct_response(version="vanilla")
    "C": _load("version_c.md"),
    "D": _load("version_d.md"),
    "E": _load("version_e.md"),
    # "Version A" as it existed during pilot_1.txt/pilot_2.txt (earlier era,
    # since replaced by the current production A above) -- "presence-first",
    # conversational-prose, no-bullets, no-clinical-screening design. Kept as
    # a distinct key since it's a different prompt text from "A" and is only
    # comparable to human ratings from those two pilots, not the A-E
    # annotation-packet session.
    "A0": _load("version_a_pilot12.md"),
    # The pre-2026-09-06 production Version A (the "Prompt C" candidate), replaced
    # in backend/app/submodules.py by F3 on that date. Registered so the earlier
    # eval results -- where "A" means this prompt, not F3 -- stay interpretable.
    # NOTE: every "A" entry in output/responses.json predates the swap and is THIS
    # prompt's output, not the current production prompt's.
    "A_legacy": _load("version_a_legacy.md"),
    # F: designed 2026-09-06 directly from the pilot evidence (see
    # eval/ae_judge/FINDINGS.md sections 2-3). Targets the two mechanisms that
    # actually separated preferred from dispreferred responses -- take-away
    # density and register -- and explicitly bans the output patterns version A's
    # prompt licenses (framing/"considerations" sections, verification hedging
    # that replaces the answer) and the one vanilla B falls into when there is
    # nothing to look up (technique-labelled generic scripts).
    "F": _load("version_f.md"),
    # F2: F with a binding 350-word / 3-4 move limit. F overshot its own soft
    # 400-word target (median 566 words). "Too long" was the providers' most
    # frequent single complaint, but they also ranked the longest response they
    # read that day #1 -- so length is the one design question the pilot data
    # genuinely does not settle, and the judge's known verbosity bias cannot
    # settle it either. Both are kept so a human can decide.
    "F2": _load("version_f2.md"),
    # F3: F with a 450-word hard limit chosen to match vanilla B's median length
    # (440 words), so a B-vs-F comparison is not confounded by length -- the one
    # axis the judge is known to be biased on. Also protects the resource block
    # from the length cut (F2's regression) and fixes the real defect the judge
    # caught on scenario_2: falling back to 2-1-1 and citing a stale program name
    # instead of looking up the county office.
    "F3": _load("version_f3.md"),
    # F4: F3 with the fixed template replaced by request-type routing. The tool is
    # a chat tool -- pilot_2 shows providers asking narrow questions rather than
    # pasting a scenario, pilot_3 describes typing "agencies, please, more
    # agencies" as a follow-up, and pilot_1's main complaint was the tool
    # "repeating itself when I made changes to the question" and re-listing
    # resources it had already given. A rigid shape reproduces that failure. The
    # content rules (borrowable language, named resources, no technique labels,
    # no padding) stay unconditional; only the shape is now conditional.
    "F4": _load("version_f4.md"),
    # F5: F4's request-type routing, with two regressions fixed. F4 dropped the
    # resource block on all four interpersonal scenarios (6-9) because the routing
    # text let it skip "a part that has nothing to go in it" -- backwards, since
    # the "9 out of 10 not 10 out of 10" complaint was made about a family-conflict
    # scenario. F5 makes resources near-unconditional and names the interpersonal
    # case explicitly, and re-binds the 450-word cap F4 drifted past (538).
    "F5": _load("version_f5.md"),
}
