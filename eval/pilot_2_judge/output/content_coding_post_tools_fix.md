# Content coding: Version A vs Version B, post tools-fix re-run (2026-08-30)

Manual coding of the 18 responses regenerated after giving Version B the same
tool access as Version A (`_ALL_TOOLS_SCHEMA` fix). Same 10 categories as the
original `content_coding.md`. Purpose: check whether the earlier behavioral
differences (scripts, verification, resources, etc.) were an artifact of B's
weaker tools, or hold up now that tools are equal.

## Summary counts (out of 9 scenarios each)

| Category | Version A | Version B | vs. original (pre-tools-fix) run |
|---|---|---|---|
| 1. Useful external resources | 6/9 (+1 mild) | ~3.5/9 | Gap persists, similar size (was 8 vs 4) |
| 2. Useful connections/distinctions | 9/9 | 8/9 | Tied — still not a differentiator |
| 3. Unsolicited scripts | **0/9** | **4/9** (M2, M3, S4, S5) | Gap is now BIGGER (was 0 vs ~2.5) |
| 4. Unsolicited coaching | 0-1/9 (mild) | 3.5/9 | Gap similar/bigger (was 3 vs 4) |
| 5. Clinical/case-management framing | 1/9 (mild) | 3/9 clear | Similar (was 1 vs 4) |
| 6. Introduced goals | 0/9 | 1/9 (mild) | Smaller than before (was 0 vs 2) |
| 7. Speculative risks | 2-3/9 (soft) | 3/9 (clear/strong) | Similar pattern, still concentrated in M2/S4/S5 |
| 8. Unnecessary questions | 0/9 | 0/9 | Tied — not a differentiator (both versions now end almost every response with legitimate clarifying questions) |
| 9. Verification/uncertainty language | **8/9** | **0/9** | Gap is now MAXIMAL (was 7 vs 1) |
| 10. Restatement/generic advice | 0/9 | 3/9 (mild) | Similar (was 1 vs 0, now B shows more) |

## Read

**Giving Version B full tool access did not close the behavioral gap — if
anything, several differences are sharper in this fresh sample than before.**
Scripts went from a ~0-vs-2.5 gap to a clean 0-vs-4; verification language
went from 7-vs-1 to 8-vs-0. This strongly confirms the earlier ablation-study
finding: these behaviors are driven by the **system prompt** (specifically
the "Trust the peer supporter" and "Be reliable" sections), not by which
tools are available. Tool access changes what facts a response *can* cite;
it doesn't change whether the model injects scripts, coaching, or omits
verification hedges — that's controlled by the prompt text.

As in the original run, scripts/coaching/clinical-framing/speculative-risk
cluster tightly in the three psychiatric/relational scenarios (M2, S4, S5) —
the resource-lookup scenarios (S1-S3, S6) show almost none of these
behaviors in either version, reinforcing that scenario content type matters
as much as which version is answering.
