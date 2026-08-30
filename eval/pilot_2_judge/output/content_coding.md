# Content coding: Version A vs Version B, 9 scenarios

Manual coding by Claude of the 18 responses in `nine_scenarios_responses.json`, per
categories calibrated with the user on 2026-08-30. Y = present, Y(mild) = borderline/soft
presence noted in text, N = absent. This is qualitative judgment, not an automated score —
treat borderline calls as debatable and check the source response if a specific cell matters.

**Category definitions (as calibrated):**
1. Useful external info/resources — specific, verifiable resource (name + contact/link)
2. Useful connections/distinctions — a real explanatory distinction or cross-connection, not just a list
3. Unsolicited scripts — literal example wording offered, not requested
4. Unsolicited peer-support coaching — advice on HOW to engage/listen/validate/pace, not literal scripts
5. Clinical/case-management framing — an overly clinical *approach* to a peer-to-peer scenario (not just relevant clinical facts stated neutrally)
6. Introduced goals — mentions a goal/priority the service user didn't state (noting soft vs firm)
7. Speculative risks — unprompted risk-flagging (noting scenario-specific vs generic/boilerplate)
8. Unnecessary questions — a clarifying question posed when the response could have proceeded
9. Verification/uncertainty language — explicit hedges ("could not verify," "current as of," "please confirm")
10. Restatement/generic advice — substantially restates the scenario or gives generic advice without adding value

## Per-scenario coding

| Scenario | Ver | 1.Resources | 2.Connections | 3.Scripts | 4.Coaching | 5.Clinical/CM | 6.Introduced goals | 7.Spec. risks | 8.Unnec. Qs | 9.Verification | 10.Restatement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 | A | Y (SSA, Disability Rights NJ, NJ WorkAbility, PHA, NJCDC — all linked/phoned) | Y (SSDI vs SSI; income vs employment; immigration category ≠ documented status) | N | N | N | N | N | N | Y ("current as of today," "could not verify... but appear active") | N |
| M1 | B | Y (NJWINS, PHA/county, NJ 211, Legal Services NJ) | Y (SSDI vs SSI; qualified non-citizen vs work-credit paths) | N | N | N (procedural/legal-checklist tone, not clinical) | N | N | N | N (no explicit hedges despite live contact info) | N |
| M2 | A | Y (Hearing Voices Network USA, Wildflower Alliance, w/ links+email) | Y (separates "having experiences" from "how he acts"; "treating symptoms" vs "protecting relationships" reframe) | N | N (mild — analytic reframing, not literal engagement coaching) | N (mentions clinical terms only as optional/conditional, explicitly respects his rejection of clinical framing) | N | N (explicitly limits scope: "less like an emergency-risk situation") | N | Y ("I was not able to verify a Newark-specific group... national network is current") | N |
| M2 | B | Y (Hearing Voices Network [diff URL], NAMI NJ, CSC directory) | Y (diagnosis-disagreement vs practical-impact reframe) | Y(mild) — one embedded suggested phrase ("You do not have to agree on what the experiences are...") | Y — explicit advice on how family should communicate, what "goes better" | Y(mild-mod) — CBTp/Open Dialogue/CSC vocabulary, "higher level of care" framing | N/weak (implicit "levels of care" framing) | **Y (clear, scenario-specific)** — explicit safety checklist incl. "commands from voices to harm self or others," "stockpiling weapons," despite scenario stating no violence/no crisis | N | N (no hedges on resource currency) | N |
| M3 | A | Y (NJ TDI, NJ FamilyCare, SNAP/Mercer Co., USF/LIHEAP, TRADE, Modivcare, NJ Transit — all with phone/link) | Y (TDI vs workers' comp path; utility-bill-in-whose-name nuance; Medicaid→transportation unlock) | N | Y(mild) — reassurance framing re: benefit hesitancy ("does not create public debt or criminal consequences") | N | N | N | N | Y ("I was able to verify... today. Mercer County transportation details may still be worth confirming") | N |
| M3 | B | Y (Mercer Co. Board of Social Services, NJHelps.org, LIHEAP/USF/SHARES, NJ Transit Access Link) | Y(mild) — prioritization insight ("Medicaid transportation... biggest immediate difference"), otherwise more procedural listing | Y(offered, not delivered) — offers "a script he can use when calling" but doesn't provide it | Y(mild) — "so the process feels less intimidating" framing, numbered action-plan tone | Y(mild) — case-management-flavored (numbered steps, "He'll likely need..." checklist) | N | N | N | N (no hedges despite live contact info/address) | N |
| S1 | A | Y (Gateway CAP w/ verification note, Salem Co. DHHS, Family Success Center, NJ 211) | Y (cross-program eligibility connection: SNAP/SSI/SSDI/Medicaid → easier USF/LIHEAP qualification) | N | N | N | N | N | N | Y ("Verified via NJ DCA county agency listing and Gateway CAP contact page") | N |
| S1 | B | Y (Salem Co. Food Resources, Catholic Charities, FoodBank of South Jersey, Gateway CAP, Salem Co. Board of Social Services, NJ 211) | N/weak (parallel lists, no cross-connection drawn) | N | N | N | N | N | N | N (no hedges) | N |
| S2 | A | Y (SSA COLA/SSI pages, cited $ figures with source links) | Y (explains *why* no single limit — earned/unearned treated differently, $65 exclusion + half) | N | N | N | N | N | N | Y ("What is confirmed by SSA for 2026" + links; flags supplement amount as variable) | N |
| S2 | B | N/weak (states figures, no links/citation: "commonly cited maximum SSI amounts") | Y (same earned/unearned/exclusion explanation) | N | N | N | N | N | N | Y(weak) — "commonly cited" is a soft, non-specific hedge | N |
| S3 | A | Y (two nj.gov links, explicit valid date range) | Y (gross vs net income; elderly/disabled exception noted) | N | N | N | N | N | N | Y ("Verified from NJ Human Services pages current for Oct 2025–Sept 2026") | N |
| S3 | B | N/weak (names MyNJHelps.gov/NJ SNAP page, no links) | Y (gross vs net; deductions for housing/childcare/medical) | N | N | N | N | N | N | N (states date range but no "verified" language or citation) | N |
| S4 | A | Y (Hearing Voices Network, Wildflower Alliance, National Empowerment Center — linked) | Y (maps distinct refusal-reasons to distinct support options; reframes "compliance" → "functioning/safety") | N | Y(mild) — response structured around "clarifying what refuses means," option-mapping is coaching-adjacent | Y(mild-mod) — goes fairly deep into clinical specifics (dosing alternatives, injectables, taper mechanics) | N — explicitly avoids pushing medication; offers taper only if *he* wants to reduce | Y(soft, conditional) — "if he is unable to meet basic needs... becoming medically unsafe... at imminent risk," framed conditionally | N | N (no hedges on the 3 resource links) | N |
| S4 | B | N (no named orgs — just "his mental health team," "crisis team," generically) | Y(mild) — capacity vs clinical-urgency distinction | N | **Y (clear, explicit)** — "Keep communication supportive rather than argumentative... often escalates conflict," directive tone throughout | **Y (clear)** — explicit deterioration-monitoring checklist (paranoia, hallucinations, agitation, suicidal thoughts, threats) | Y(soft) — implicitly frames ongoing safety-monitoring as a task | **Y (clear, asserted upfront)** — "untreated psychosis can sometimes lead to harm... hospitalization, loss of housing" stated as a general primer, not conditional | Y(borderline/legitimate — no location given in this specific prompt) — "If you tell me what country you're in..." | N | Y(mild) — fairly generic/textbook, no NJ-specific programs named |
| S5 | A | Y (Hearing Voices Network, Wildflower Alliance, National Empowerment Center, mentions CSPNJ) | Y (strong: "meaningful" vs "disruptive" experience distinction; reframes med-debate → sleep/parenting/communication) | N | Y(mild) — family-conflict-dynamics guidance, "middle ground" framing | N/weak — clinical terms mentioned only as conditional possibility | N — explicitly avoids "symptom elimination or medication compliance" framing | N/weak — sleep-disruption note framed as general pattern, not asserted risk | N | Y ("I could not verify a current Newark-specific group, but the national directory is active") | N |
| S5 | B | **N (zero named resources/orgs at all)** | **Y (strongest of all 18)** — "having psychotic experiences" vs "being dangerous"; clinical-criteria vs spiritual-meaning; "who defines meaning" framing | **Y (clear, full script)** — "I respect that these experiences are real and meaningful to you, and I also need stability, predictability, and safety in our family life." | **Y (strongest of all 18)** — extensive interpersonal/family-communication guidance throughout | **Y (strongest of all 18)** — explicit clinical-criteria framing, harm-reduction monitoring checklist (sleeping? parenting safely? early signs?), CBTp/Open Dialogue/psychodynamic vocabulary | Y(mod) — introduces "stability, safety, relational functioning, and agency" as *the* goal of a harm-reduction model, not stated by the scenario | **Y (clear, most extensive of all 18)** — "grandiosity, paranoia... financial recklessness, neglect of children" list, despite scenario stating no violence/no crisis | N | N (no hedges; presents interpretive claims with full confidence, no sources at all) | N |
| S6 | A | N (correctly withholds until clarified) | N | N | N | N | N | N | N (appropriate/necessary, not "unnecessary") | N | N |
| S6 | B | N | N | N | N | N | N | N | N (appropriate/necessary) | N | N |

## Summary counts (out of 9 scenarios each)

| Category | Version A | Version B | Notes |
|---|---|---|---|
| 1. Useful external resources (specific, w/ contact) | 8/9 | 4/9 clear (+3 weak: named but no link) | Biggest, most consistent gap — A almost always gives verifiable contacts; B does so reliably only in the resource-lookup scenarios (M1, M2, M3, S1) |
| 2. Useful connections/distinctions | 8/9 | 7/9 (incl. mild) | Both do this well — not a real differentiator |
| 3. Unsolicited scripts | 0/9 | 2/9 clear + 1/9 offered-not-delivered | A: zero. B: M2, S5 (S5's is a full quoted script) |
| 4. Unsolicited coaching | 3/9 (all mild) | 4/9, and markedly stronger where present | B's instances (M2, S4, S5) are more explicit/directive than A's mild ones |
| 5. Clinical/case-management framing | 1/9 (mild) | 4/9, and markedly stronger where present | S4B and S5B both read as clearly clinical in register; A's one instance (S4) is milder |
| 6. Introduced goals | 0/9 | 2/9 (S4 soft, S5 moderate — "stability, safety, relational functioning, agency" as *the* goal) | A never introduces an unstated goal in this set; B does twice |
| 7. Speculative risks | 1/9 (soft, conditional) | 3/9, and markedly more severe (M2, S4 asserted upfront, S5 most extensive) | Notably, M2B and S5B both introduce risk content (violence-adjacent, child-neglect) into scenarios that explicitly state "no violence history, not in crisis" |
| 8. Unnecessary questions | 0/9 | ~1/9 borderline (S4B, arguably legitimate since that prompt lacks location) | Not a real differentiator in this set — S6's clarifying question is appropriate for both versions |
| 9. Verification/uncertainty language | 7/9 | 1/9 clear + 1/9 weak | A: consistently hedges when info might be stale/unverified. B: almost never does, even when giving equally time-sensitive info (contact numbers, dollar figures) |
| 10. Restatement/generic advice | 0/9 | 1/9 (mild, S4) | Minor differentiator |

## Read

The clearest, most consistent differences: **Version A reliably cites specific, contactable
resources and flags verification status; Version B does this only sometimes and rarely hedges.**
**Version A essentially never introduces scripts, unstated goals, or unprompted risk narratives
in this set; Version B does so in a cluster of scenarios (M2, S4, S5) — notably concentrated in
the mental-health/psychosis scenarios**, where B repeatedly drifts into clinical-monitoring
checklists and risk-flagging beyond what the scenario stated (most extreme in S5B, despite the
scenario explicitly noting "no history of violence, not in crisis").

Connections/distinctions and unnecessary-questions show no meaningful A/B gap — both versions
are similarly strong at explaining and similarly restrained about asking blocking questions.
