# What CSPNJ peer providers actually prefer, and whether a judge can reproduce it

Built from `debugging/data/`: `pilot_1.txt`, `pilot_2.txt`, `pilot_3.txt`,
`annotation_packet.md`. Two providers, four sessions.

---

## 1. The single most important correction

**The version letters do not name quality levels.** The same annotator, in one
session, put **B** first on two scenarios and fourth on a third, and put **D**
first on one scenario and called it *"way too long"* on another. A/B/C/D/E name
system prompts; what the annotator ranked was the particular text in front of
them.

Two consequences, both of which invalidated earlier work here:

- A judge tuned to reproduce "D beats B" has learned nothing transferable.
  It has to score **properties**.
- `validate_all.py` compared the judge's ranking of *freshly generated* pipeline
  responses against a human ranking of the *packet's* responses. Different text.
  A miss there could never be attributed to the rubric. Every number it produced
  is uninterpretable.

`packet_ground_truth.py` fixes this: it pulls the exact Tool A-E texts the
annotator read, from all three packet scenarios (the earlier harness used one),
taking the held-out set from 10 pairs to **16**.

---

## 2. The value model

Ordered by how consistently each separated preferred from dispreferred responses.

### V1. Take-away density — "can I use this line right now?"
The dominant discriminator. Every part of a response is either something the
provider can **lift** or something they only **read**.

> "I prefer the questions that I can use right away, or some specific resources
> that I can borrow."
> "We are not using the AI to [rehearse] the basics that we already know."

Liftable: a named agency with a number; a question phrased so it can be asked
verbatim; a sentence the *service user* could say to a prescriber or a family
member; a step with the specifics attached; a fact they'd otherwise Google.

Not liftable: restating the scenario, naming a frame or lens, "it may help to
consider…", explaining why an approach is good.

**This is not a length measure.** Counting bullets is a length proxy — a mistake
this project made and had to undo (see §4).

### V2. Named, checkable, relevant resources
> "It would be 10 out of 10 if the agency information was down below. Because we
> don't have the information, it's going to be just 9 out of 10."
> "Some clients, they don't even know what to put on the Google… there are a lot
> of scams. So I prefer to give them the real words information."
> "For version B, I could see they're very accurate. Very familiar agencies."

Accuracy and fit are part of it, not extras — pilot_1's provider verifies every
referral before handing it over, so a dud referral costs them time. Score the
**net**: three good referrals beat six of which four don't apply.

### V3. Register — practitioner, not textbook, not seminar, not flattery
Three separable failure modes, all real in the data:

**(a) Being taught their own craft.** This is what sank the packet's Tool B.
> "Just like validation or reflection, that kind of thing. Those are the things
> that we learn from the textbook, and we don't need it."
> "As a peer provider, it is really about relationship. If I just look at the
> script and just pretending that I'm listening, I don't think that is appropriate."

**(b) Seminar register.** Abstract taxonomies — "functioning vs. recovery",
"independence vs. interdependence":
> "If the clients are talking to the researchers or scholars, I think it totally
> makes sense. But in a real world setting, I don't think that's really useful."

**(c) Flattery**, from pilot_1:
> "It felt like it was doing a little more of the 'oh, that's a great idea of
> you'… that's the type of thing that always puts me off."

**The distinction that matters most and is easiest to get backwards:** concrete
words in someone's mouth are *wanted* — "how can we elaborate into real
language?" A labelled technique over interchangeable filler ("**Validate +
reflect:** 'It makes sense you'd feel frustrated…'") is the violation. A tailored
line the service user could actually say ("When decisions are made without my
input, I shut down") is the thing they asked for. Two responses can both be full
of quotation marks and land on opposite sides of this line.

### V4. Shape — frame first, then linked steps, readable at a glance
> "This is something you're facing with… on the first paragraph. And then these
> are the things you might try out."
> "I tend to choose the version which I could see in a picture, like at a glance."
> "If we can try make it concise and bulletin board, that'd be great."

Negative: *"just listing option A, B, C, and D, which are kind of like really
separated, not linked together."*

### V5. Padding, not length
Being "too long" is the most frequent single complaint — and it is **not** a word
count. In the one fully-ranked scenario the **longest** response was ranked #1
and the second-shortest was #4. A length-only baseline scores 53% on the 17 pairs
(chance).

> "For response D, I feel like every information was helpful and very useful."
> …but of a different response: "First of all, it's way too long."
> …and of a short one: "For tool E, it's way too concise."

### V6. Tells me something I didn't already know
> "Even the names of agencies were some suggestion that I never thought of."
> pilot_1: "This is something that never occurred to me… silver sneakers to get
> discounted."

pilot_1 also valued being told *why* one step comes first ("get the ID, because
it unlocks the benefits, which unlock the housing").

### Judged from the harder of two use modes
> "If my client just walked in and they explain their situation and I want to get
> them answers right away, then definitely tool B, I don't think this is the right
> one."

---

## 3. Does the value model explain the observed rankings?

Yes — all 16 constraints, without contradiction:

| scenario | human | mechanism |
|---|---|---|
| packet S4 (`scenario_8`) | D > C > E > B > A | D: ~20 tailored lines she can say + role-play + "what to bring". C: correct, relevant NJ resources (DMHAS Ombudsman, DRNJ, 988). E: has resources but 2 of 3 don't apply to her (PerformCare is the children's system; the Ombudsman is for institutionalised adults), and it asks its questions twice. B: labelled techniques + generic filler. A: 603 words of meta-commentary, zero quoted lines. |
| packet S3 (`scenario_7`) | B, D > A, C | B: tight frame + concrete goal examples. D: ~15 borrowable lines. A: six dense sections of framing. C: seminar taxonomy — its resources, which the annotator explicitly liked, did not rescue it. |
| packet S1 (`scenario_1`) | B > A, D | B: three real phone numbers, an address, hours, and a Today/Tomorrow/This-week plan. A: hedged its one phone number away. D: admitted its tool lookup failed. |

Note how V2 behaves: resources win S1 outright, are decisive for C's #2 in S4,
and are *not enough* for C in S3. They are a strong term, not a trump card — and
"more resources" is not the measure, "resources that fit this person" is.

---

## 4. Can a judge reproduce it?

`validate_packet.py`, 16 literal pairs, both orderings, 3 samples each,
majority-voted. Six configurations:

| config | all 16 | s8 well-separated | s8 adjacent | s1+s7 | misses going to the longer text |
|---|---|---|---|---|---|
| v5 + gpt-5     | **13/16 81%** | **6/6** | 2/4 | 5/6 | 2/2 |
| v5 + gpt-5.1   | 11/16 69% | 5/6 | 2/4 | 4/6 | 2/2 |
| v6.1 + gpt-5   | 11/16 69% | 4/6 | 2/4 | 5/6 | 3/4 |
| v6.1 + gpt-5.1 | 11/16 69% | 5/6 | 2/4 | 4/6 | 3/4 |
| v6.0 + gpt-5   | 11/16 69% | 5/6 | 2/4 | 4/6 | 4/5 |
| v6.0 + gpt-5-mini | 10/16 62% | 4/6 | 2/4 | 4/6 | 4/5 |

Length-only baseline: 53%. Clean holdout (pilot_2's `scenario_9`, B > A0, which
neither rubric was written against): both correct, unanimous, both orderings.

**The v6 rebuild did not beat the rubric it was meant to replace.** Paired exact
McNemar between v5+gpt-5 and v6.1+gpt-5: 2 discordant pairs, both in scenario_8,
p = 0.50. v5's 13/16 does not reproduce at gpt-5.1 (11/16). Five of six configs
sit at 10–11. Treat the whole table as one distribution.

### What is stable across every configuration

1. **2/4 on adjacent-rank pairs, always.** The judge is at chance on neighbours.
   So, arguably, was the human — the ranking was dictated as *"Okay. Let's do D,
   C. Okay. E, C, E. Okay. B, A."*
2. **13 of the 16 misses across all six configs went to the longer response.**
   Verbosity bias survived every explicit instruction against it in both rubrics.
   It is the residual failure mode, and it bites specifically when neither
   response has a resource advantage (both B-vs-A misses).

### Why v6 is still the better default, on grounds the numbers can't see
`report_qualitative.py`: v6's correct verdicts cite a mechanism the annotator
actually used in **12/12** cases, with **zero** instances of
length-as-comprehensiveness, hedging-as-honesty, or polish-as-quality language.
Its verdicts read like the provider — *"I don't need to be taught validation
scripts — I need concrete NJ options and who to call."*

v5's read like its own rubric — *"this is an interpersonal/advocacy scenario…
does not reach the high bar for dimension 9."* On C-vs-B it lands the right
answer without ever identifying the textbook-technique objection the annotator
said drove it. Being right for a procedure reverse-engineered from one ranking is
what motivated this rebuild. This is a bet on transfer, not a result.

### A mistake worth recording
v6.0 asked the judge to **count** usable units before deciding. The counts were
unstable — the same two texts scored 3-vs-9 in one ordering and 5-vs-2 in the
other — and counting bullets rewards length with extra steps, reintroducing the
exact bias the rubric was written to remove. v6.1 replaced counts with
proportions and verbatim quotes.

---

## 5. What not to trust, and what to do next

Do not trust: adjacent-rank distinctions; any pair where one response is much
longer and neither has a resource advantage; any single number above as a
generalisation estimate.

16 pairs, **one annotator, one session** — not 16 independent observations. The
6 pairs from scenarios `rubric.py` was never tuned against give 5/6 for both
rubrics; a 95% CI on that spans roughly 40–100%. That is why p = 0.50 between
two rubrics that read very differently.

**The bottleneck is human data, not rubric prose.** Six untouched pairs cannot
separate these rubrics. The next real improvement is more annotators — ideally
several providers ranking the same texts, which would also settle whether the
adjacent-pair chance rate is judge noise or genuine human indifference.

---

## 6. Does adding pilot data to the prompt help? No.

`grounding.py` / `validate_grounding.py`: four escalating levels of real pilot data
in the judge prompt, each evaluated **leave-one-scenario-out** so the grounding for
a held-out scenario never contains anything derived from it. Without that filter the
experiment measures nothing — the annotator's reason for preferring B on scenario_7
*is* the answer key for scenario_7's pairs.

| grounding in the prompt | all 16 | well-separated | adjacent | untouched | position flips |
|---|---|---|---|---|---|
| **none** — generic persona, rubric only | **12/16 75%** | 5/6 | 2/4 | 5/6 | **0** |
| quotes — the providers' verbatim statements | 11/16 69% | 4/6 | 2/4 | 5/6 | 1 |
| summary — a distilled pilot-findings briefing | 10/16 62% | 5/6 | 1/4 | 4/6 | 3 |
| examples — 3 worked pairwise comparisons with the human's verdict *and* reason | 11/16 69% | 5/6 | 1/4 | 5/6 | 2 |

Three things, and the second is the real result:

1. **More grounding is not better; if anything it is slightly worse**, and it
   monotonically degrades position stability (0 → 1 → 3 → 2 flips). Prompt bloat
   buys instability.
2. **The same four pairs fail in every single condition** — `scenario_7:B>A`,
   `scenario_8:B>A`, `scenario_8:C>E`, `scenario_8:D>E` — and all four conditions
   produce the *identical* scenario_8 ranking, E > D > C > A > B (tau +0.40).
   Nothing in the prompt moves the error. It is not an information problem.
3. Worked few-shot examples, the intervention most likely to help a priori, did not
   beat the no-grounding condition on a single pair.

**Why this doesn't contradict `debug_four_versions_judge`** (which found persona
priming reverses rankings): that judge had a generic rubric with nothing in it about
what these providers want. The values have to be *somewhere*. Here they are already
in the D1–D6 dimensions, and restating them as quotes is redundant.

**What does move the ranking:** the v5 rubric's hand-written "exceptional coaching
depth" clause, which flips D above E and produces tau +0.80. That clause was
reverse-engineered from this exact ranking, and its advantage disappears at gpt-5.1.
So: hand-fitted *rules* move it, grounding *content* does not, and only one of those
is evidence of a better judge.

---

## 7. The recommendation

`judge.py` — v6 dimensions, generic persona, gpt-5, both orderings × 3 samples.
12/16, 5/6 on well-separated comparisons, zero position flips, nothing fitted to any
human ranking.

**It works for** "is version X clearly better than version Y here?", when the verdict
is unanimous across both orderings.

**It does not work for** fine-grained ranking. No judge tested reproduces
D > C > E > B > A from first principles; the un-fitted ones all return
E > D > C > A > B. Adjacent placements are chance-level in every configuration ever
run, and errors concentrate on pairs where one response is much longer and neither
has a resource advantage.

Excluding scenario_8's four E pairs — the concentration point of the disagreement —
both the recommended judge and hand-fitted v5 reach 10/12 (83%).

---

## 8. Version F — a prompt designed from the pilot evidence

`debugging/data/version_f.md`, and `version_f2.md` (same rules, binding 350-word limit).

**Diagnosis F is built on.** Version A's prompt already says most of the right things
in the abstract — "don't explain how to validate", "keep it concise", "make it
skimmable". It still lost three times out of three, because two of its clauses
license the exact patterns the providers rejected: it *asks for* "important
considerations" (→ "Key rights/frames", "A decision-support approach you can offer"),
and its verification rule ("if you cannot find or verify something, say so") produces
the punt that replaces the answer. Meanwhile vanilla B wins lookup scenarios by just
answering with numbers, and falls to 4th on an interpersonal one because with nothing
to look up it defaults to technique-labelled scripting.

So F is specified as an output *shape* plus explicit bans: frame → 3–6 labelled moves
→ named resources at the end → at most one closing question; give borrowable lines
the service user could actually say; never label a technique; check every referral
fits this person; attempt before asking; no framing/considerations sections.

**Judge-free audit** (`pilot_criteria_audit.py`, medians over 9 generated responses;
regexes validated against the packet texts they were written for):

| ver | words | contacts | borrowable lines | admin punts (of 9) |
|---|---|---|---|---|
| **F** | 566 | 4 | 12 | **0** |
| **F2** | 358 | 2 | 10 | **0** |
| A (production) | 605 | 3 | 1 | 3 |
| B (vanilla) | 440 | 0 | 3 | 1 |
| C | 547 | 4 | 0 | 1 |
| D | 769 | 0 | 14 | 2 |
| E | 705 | 5 | 6 | 0 |

F is the only version that is simultaneously high on resources *and* on borrowable
language, with no punts — the combination the annotator described wanting and never
got from a single version ("it would be 10 out of 10 if the agency information was
down below").

**Judge results, 9 scenarios, generated responses:**

| | v6 (recommended judge) | v5 (independent cross-check) |
|---|---|---|
| F vs A | 8/9 | 7/9 |
| F vs B | **9/9** | **7/9** |
| F vs C / D / E | 9/9, 9/9, 9/9 | (D) 6/9 |
| F2 vs B | 8/9 | 7/9 |
| F2 vs A | 6/9 | — |

**Discount the v6 sweep.** 44/45 unanimous is too clean, and the reason is structural:
F's prompt and the v6 rubric were written from the same value model by the same author,
so the generator was optimised against the evaluator's specification. The v5 numbers
(7/9 vs B, 7/9 vs A, 6/9 vs D) come from a rubric written before that value model
existed and are the honest estimate. **Both rubrics agree F beats the vanilla baseline**,
which is the bar that matters — production A did not clear it.

**Evidence the judge is not just rubber-stamping F:** it gave F its one loss
(scenario_2 vs A) for a real defect — F leaned on 2-1-1 and cited a stale "NJOneApp"
where A had the Camden County Board of Social Services direct line. Worth fixing.

**The open question the data cannot settle: length.** F runs ~566 words; the target the
annotator actually pointed at was ~425. But they also ranked the longest response they
read that day #1. F2 hits 358 words and keeps most of the borrowable language, but
halves the resources — the thing they most often said they wanted. The v6 judge prefers
F over F2 8/9, and that is precisely the axis where it has a documented verbosity bias,
so it does not get a vote. **A human should pick between F and F2.**

---

## 9. Length-matched: F3 vs B

`version_f3.md` — F with a binding 450-word limit chosen to match vanilla B's median
(440), plus two fixes: the resource block is protected from the length cut (F2 lost
half its resources to it), and it must look up the county office before falling back
to 2-1-1 (the real defect the judge caught on scenario_2).

**Length parity achieved:** F3 median 454 vs B 440; F3 is *shorter* than B on 5 of 9
scenarios, longer on 4.

| ver | words | contacts | borrowable | technique labels | framing | punts |
|---|---|---|---|---|---|---|
| F | 566 | 4 | 12 | 0/9 | 0/9 | 0/9 |
| **F3** | **454** | **5** | 10 | **0/9** | **0/9** | **0/9** |
| F2 | 358 | 2 | 10 | 0/9 | 0/9 | 0/9 |
| B | 440 | 0 | 3 | 1/9 | 1/9 | 1/9 |
| A | 605 | 3 | 1 | 0/9 | 4/9 | 3/9 |

(Unwanted columns are now incidence, not medians — a habit appearing on 1 of 9
scenarios has a median of 0 and would read as "never".)

**The length confound is ruled out.** The independent v5 rubric gives the same verdict
at every length:

| vs vanilla B | words | v6 judge | v5 judge (independent) |
|---|---|---|---|
| F | 566 | 9/9 | **7/9** |
| F3 | 454 | 8/9 | **7/9** |
| F2 | 358 | 8/9 | **7/9** |

7/9 across a 208-word range, including at parity with B. The advantage is content, not
length. (The v6 judge still prefers F over F3 3/9 — that is its documented verbosity
bias, and it is the reason F3 is the recommended variant despite v6 liking F more.)

**Qualitative, same scenario, same length** — scenario_8, B at 440 words vs F3 at 454.

What B does, against what the providers said:
- Opens *"A good peer response is to stay in the peer role: validate her experience,
  support her self-determination…"* — lectures on peer principles in its first sentence.
- Contains, verbatim, the two things the annotator named: a header reading
  **"Validate + reflect"** over the line *"It makes sense you'd feel frustrated."*
  → *"Those are the things that we learn from the textbook, and we don't need it."*
- **"Key boundaries for the peer provider: Don't tell her 'You should switch'… Don't
  undermine or diagnose."** — teaching a trained peer their own job.
- Zero named resources. Closes by asking for the setting instead.
- It is not worthless: several quoted lines are genuinely usable. They are just wrapped
  in technique headers, which is precisely the packet-B pattern ranked 4th of 5.

What F3 does:
- Two-sentence frame naming the real issue and the next step → *"this is the context and
  here is what you can do."*
- Four moves, each an action in order, no technique labels.
- ~10 borrowable lines specific to her situation, plus a fill-in summary template.
- Move 4 is a call to place *while they are together*, with the words to say to the clinic.
- A resource block with three real NJ numbers, what each is for, and a currency marker
  → *"it would be 10 out of 10 if the agency information was down below."*
- One narrowing question, after the resources rather than instead of them.

**Honest problems with F3 that a provider would notice:**
1. Its resources here are statewide (NJ Mental Health Cares, 988, 211), not county-level.
   The scenario names no county, so it is defensible — but it is a softer version of the
   failure that lost scenario_2, and the closing county question is a punt wearing a coat.
2. It asserts *"verified ongoing as of 2026-09"*. The intent is right (pilot_2's provider
   explicitly asked for "as of when" markers) but the claim has to actually be true, and
   nothing here checks that. This is the highest-risk line in the output.
3. Minor typographic artifacts (non-breaking hyphens in "1‑866", "treatment‑planning").

**Recommendation: F3.** It matches B's length, carries the most named resources of any
version, keeps D's borrowable depth, and shows none of the unwanted patterns on any of
the 9 scenarios. The remaining questions — is statewide-fallback acceptable, is the
verification claim trustworthy — are for a provider to answer, not the judge.

**F3 against the full field** (9 scenarios, generated responses):

| F3 vs | v6 judge | v5 judge (independent) |
|---|---|---|
| A (production) | 8/9 | 7/9 |
| B (vanilla baseline) | 8/9 | 7/9 |
| C | 8/9 | — |
| D (coaching-heavy) | 9/9 | **4/9, 2 ties — a wash** |
| E | 9/9 | — |

The D result is the one to take seriously: on the independent rubric F3 does **not** beat
D, it ties it (4-3-2). D is the prompt that won the one fully human-ranked scenario, so
this is coherent rather than surprising. F3's clear, cross-rubric wins are over A and B;
against D the honest claim is parity, with F3 additionally carrying named resources that
D never produces (5 vs 0), which is the thing the annotator most often asked for.

---

## 10. F5 — flexible shape (the recommended prompt)

F3's fixed template was wrong for a chat tool. The pilots show providers using it
conversationally: pilot_2's provider asked narrow factual questions instead of pasting
a scenario, pilot_3 described typing *"agencies, please, more agencies"* as a follow-up,
and pilot_1's main complaint was that the tool *"seemed to repeat itself when I made
changes to the question... gave resource lists that they'd already mentioned."*

`version_f5.md` replaces the template with **request-type routing** — narrow question,
request for more of something, follow-up mid-conversation, request for wording, or open
situation (only the last gets the frame → moves → resources default). The content rules
(borrowable language, named resources, no technique labels, no padding) stay unconditional.

**F4 was a failed intermediate, and worth recording.** Loosening the shape let the model
drop the resource block on **all four** interpersonal scenarios (6–9 → 0 contacts), because
the routing text told it to drop a part it had nothing to put under. That is backwards: the
*"9 out of 10, not 10 out of 10"* complaint was made about a **family-conflict** scenario,
not a benefits lookup. F5 makes resources near-unconditional and names the interpersonal
case explicitly.

| ver | words | contacts | contacts on interpersonal (6/7/8/9) | borrowable | unwanted patterns |
|---|---|---|---|---|---|
| **F5** | 468 | 4 | **4 / 3 / 4 / 8** | 12 | 0/9 |
| F3 | 454 | 5 | 4 / 8 / 2 / 3 | 10 | 0/9 |
| F4 | 538 | 1 | **0 / 0 / 0 / 0** | 12 | 0/9 |
| B | 440 | 0 | 0 / 0 / 0 / 0 | 3 | technique 1/9, framing 1/9, punt 1/9 |
| D | 769 | 0 | 0 / 0 / 0 / 0 | 14 | technique 3/9, framing 2/9, punt 2/9 |

**Flexibility test** (`flexibility_test.json`) on the three request types the pilots
actually show, run through the real pipeline:

| request | F5 | F3 | B |
|---|---|---|---|
| narrow factual question | 148 w | 290 w | 206 w |
| "just give me a list" | 263 w | 364 w | 283 w |
| follow-up: "More agencies please." | 189 w | 345 w | 83 w |

Neither F5 nor F3 forced the Move/resource template onto a narrow request — F3 was less
rigid in practice than its prompt reads. But F5 scales down ~40% further on every request
type, and on the repetition test that pilot_1 actually complained about:

- **F5**: 3 resources in turn 1, 8 in the follow-up, **overlap 0** — nothing repeated.
- **F3**: repeated 211 and 988.
- **B**: did not answer at all. It replied *"Which location should I search near… and what
  type of 'agencies' do you mean?"* — a clarifying-question punt, on the exact request
  pilot_3 described making.

**Recommendation: F5.** Same profile as F3 on open scenarios, better on interpersonal
resources and borrowable language, and it actually behaves like a chat tool. The two
caveats from §9 stand unchanged: it still asserts verification dates nothing checks, and
no provider has seen any of this.

---

## 11. Frozen: F3 is production Version A. Three-judge treatment vs control.

**Frozen 2026-09-06.** `get_default_peer_copilot_system_prompt("cspnj")` in
`backend/app/submodules.py` now returns F3 verbatim; `debugging/data/version_a.md`
matches. The previous Version A is preserved as `version_a_legacy.md` and registered
as `A_legacy` in `versions.py` -- **every "A" entry in `output/responses.json`
predates the swap and is the legacy prompt's output, not the current one's.**

**Treatment F3 vs control B (vanilla), 9 scenarios x 5 samples x 2 orderings per
judge** (`three_judges.py`, 360 judge calls):

| judge | scenarios won | F3 vote share | 95% CI | position flips |
|---|---|---|---|---|
| **1 — naive**, no rubric | 5/9 (2 tie) | 62/90 = 69% | [59%, 78%] | 2 |
| **2 — SAMHSA + IPS** | 6/9 (2 tie) | 66/90 = 73% | [63%, 81%] | 2 |
| **3 — pilot-derived (v6)** | 8/9 | 82/90 = 91% | [83%, 95%] | 0 |
| *v5 cross-check* | 8/9 | 80/90 = 89% | [81%, 94%] | 0 |

**All four favour F3 over vanilla B**, and the two judges with no shared lineage with
F3 (1 and 2) clear the bar independently. The gradient is itself the result: the more
a judge knows about what these particular providers said they want, the larger F3's
margin. The rubric-based judges are also more stable (0 flips vs 2).

### scenario_8 — the finding

| judge | F3 votes |
|---|---|
| 1 naive | **0/10** |
| 2 SAMHSA + IPS | **0/10** |
| 3 pilot-derived | 10/10 |
| v5 | 10/10 |

Both independent judges prefer **B**, and their stated reason is that B *"centers
self-determination, validation, and collaborative planning… clearly maintains peer-role
boundaries — closely aligning with SAMHSA competencies and IPS principles of mutuality."*

B's text on this scenario is the one containing a header reading **"Validate + reflect"**
over *"It makes sense you'd feel frustrated,"* and a **"Key boundaries for the peer
provider"** section. That is exactly what the real CSPNJ provider rejected: *"Validation
or reflection — those are the things that we learn from the textbook, and we don't need
it. People will not expect that while using the AI."*

So on this scenario the default eval **and** the literature-grounded eval both select the
response a real provider ranked down, for the very property they ranked it down for. This
is the concrete form of the failure that started this project (shipping A because a judge
liked it), and it is an argument that neither Rung 0 nor a competency-framework judge is
sufficient on its own for a tool-usefulness question — competencies describe what peer
*support* should be, not what a peer worker wants from a *tool*.

### scenario_3 — a real F3 defect, not a judge artifact

Judge 1 0/10, Judge 3 2/10, v5 0/10 — three of four prefer B, and they agree on why:
F3 *"lacks the key DVRS contact"* while B gives *"the exact DVRS Paterson office info
alongside One-Stop and WIPA routing."* (Judge 2 is the lone dissenter, on mutuality
grounds.) This is the same failure as the earlier scenario_2 loss: on
employment/vocational scenarios F3 sometimes routes generically instead of landing the
specific local office. **This is the top thing to fix**, and it is independently
confirmed rather than a single judge's quirk.

### Caveat that has not changed
Judge 3 shares a value model and an author with F3's prompt, so its 91% is not
independent confirmation. And no provider has yet seen F3.

---

## 12. The scenario_3 "F3 defect" was a search rate-limit bug — correction

Section 11 called F3's scenario_3 loss a prompt defect ("routes generically instead of
landing the local office… top thing to fix"). That was wrong about the mechanism, and
the check that disproves it was already available: **`scenario_3` and `scenario_4` are
literal duplicates** (documented in `scenarios.py`). F3 gets the DVRS Paterson number on
scenario_4 and misses it on scenario_3 — identical input.

**Root cause, in F3's own words on the failing run:** *"Resources (verified via web
search today; DVRS Paterson details couldn't be verified due to a search limit error)."*

`web_search_tool` in `backend/app/tools.py` had no rate-limit handling. Brave's free tier
allows ~1 query/second; a single response makes 5–12 search calls and eval runs fire
several responses in parallel. Measured directly: **3 of 6 back-to-back calls returned
429**, while the same 6 spaced 1.2s apart all succeeded. On a 429 the tool returned the
*string* `"Search failed: …"` to the model, which F3 then honestly reported and — per its
own rule not to name unverified resources — withheld the number.

**Fix applied:** a process-wide throttle (`_brave_throttle`, one call per 1.2s) plus
retry-with-backoff on 429. 12/12 calls now succeed.

**Effect, same test, 6 runs each on scenario_3:**

| | DVRS number present | reports a search failure | tool calls |
|---|---|---|---|
| F3 before | 1/6 | 5/6 | 4–9 web searches |
| **F3 after** | **4/6** | **0/6** | 3–12 web searches |
| B before | 3/6 | 0/6 | **none** |
| B after | 2/6 | 0/6 | **none** |

After the fix F3 (4/6) beats B (2/6) on the exact lookup it was losing.

**The more important finding is about B.** B calls **zero tools** on this scenario — its
numbers come from parametric memory, not retrieval. So B's apparent advantage on resource
lookup was unverified recall, and it is silent about that either way: when it doesn't know,
it simply omits, with no signal to the provider. F3 searches, and when search failed it
said so. **The judges cannot tell those two behaviours apart** — they reward a confident
number regardless of provenance. Given both real providers said they verify every referral
before handing it over, that distinction matters more to them than to any judge here.

**Consequence for everything above:** every generation in sections 8–11 ran under a ~50%
silent search-failure rate. Comparisons stay internally fair (all versions carried the same
handicap, and B was unaffected since it doesn't search), but absolute resource counts
understate what the system can now do, and results that hinge on a live lookup — scenario_3
above all — should be regenerated before being reported.

**Also worth fixing in F3's prompt:** on a verification failure it currently withholds. Both
providers verify everything anyway (*"I would definitely look up each resource"*; *"if we
can just mark down, this is the information as of when"*), so giving the lead flagged as
unconfirmed is strictly more useful to them than giving nothing.

---

## 13. Verification-failure rule changed (F3 rev 2) — applied, effect not proven

The two verification rules in F3 contradicted each other. Line 33 said *"if a lookup
fails… still give the best real starting point you do know"*; line 35 said *"if you have
not confirmed it currently exists under that name, either verify it or leave it out."*
The model resolved toward line 35 — the more concrete instruction — and withheld.

Line 35's tail was replaced with a rule that separates the two cases it had conflated:

> Do not invent a program or portal name, and do not pass on one you only vaguely recall.
> But "I could not verify this right now" is not the same as "I do not think this exists":
> if you have a specific named office, program, or number and verification failed or was
> unavailable, give it and mark it — "DVRS Paterson, listed as 973-742-9226 — I couldn't
> confirm this today, worth a call to check." The provider verifies referrals before
> passing them on, so a flagged lead is useful to them and an omission is not.

Grounded in: pilot_1 *"I would definitely look up each resource… I always want to check"*
(verification burden rated 5/5); pilot_2 asking for a date stamp rather than omission
(*"if we can just mark down, this is the information as of when"*); pilot_3 pricing the
absence at *"9 out of 10 instead of 10 out of 10."*

Applied to `version_f3.md`, `version_a.md`, and `backend/app/submodules.py` (all three
verified byte-identical).

**Measured, 8 runs per condition under a forced TOTAL search blackout** (every
`web_search_tool` call returns a 429 string — the cleanest way to isolate the rule):

| | distinct phone numbers per run | mean | zero-resource runs | flags the failure |
|---|---|---|---|---|
| old rule | 1,1,2,2,2,3,3,3 | 2.12 | 0/8 | 5/8 |
| **new rule** | 0,2,2,3,4,4,5,5 | **3.12** | **1/8** | 6/8 |

Direction is right — about one extra reachable resource per response — but **exact
permutation test p = 0.222**, so at n=8 this is not a proven improvement, and the new rule
produced one zero-resource run the old rule never did. Flagging barely moved (5/8 → 6/8).

Keeping it on grounds of principle rather than measurement: it is better motivated by the
provider evidence, and the condition it addresses is now rare anyway since the 429 fix in
section 12. A representative blackout response now reads:

> **Resources (best starting points; I could not verify local DVRS/WIPA numbers today due
> to web lookup limits—please confirm)** — NJ DVRS statewide 1-866-871-8305, *"ask for the
> Paterson/Passaic County office"*; DRNJ 1-800-922-7233; NJ 2-1-1.

which is the intended behaviour: named, reachable, flagged, with a workaround.

**Note on provenance:** every number in sections 8–11 is for F3 rev 1. This edit is small
and its measured effect is within noise, but it is unvalidated against those results.

---

## 14. Three-judge study, re-run on the fixed pipeline (definitive)

Both arms regenerated after the Brave throttle fix (§12) and the verification-rule
change (§13), at 4 workers so the 1.2s throttle never queued. **F3 responses reporting a
search failure: 0/9, down from 5/6.** Rev-1 artefacts kept as
`responses_rev1_prebravefix.json` and `three_judges_results_rev1_prebravefix.json`.

| judge | scenarios won | F3 vote share | 95% CI | flips | *(before fix)* |
|---|---|---|---|---|---|
| **1 — naive**, no rubric | 7/9 (1 tie) | 77/90 = **86%** | [77%, 91%] | 1 | *69%* |
| **2 — SAMHSA + IPS** | 8/9 | 79/90 = **88%** | [79%, 93%] | 0 | *73%* |
| **3 — pilot-derived (v6)** | 9/9 | 90/90 = **100%** | [96%, 100%] | 0 | *91%* |
| *v5 cross-check* | 9/9 | 86/90 = **96%** | [89%, 98%] | 0 | *89%* |

Per scenario (F3 votes / 10):

| scenario | J1 naive | J2 SAMHSA+IPS | J3 pilot | v5 |
|---|---|---|---|---|
| 1 | 7 | 10 | 10 | 10 |
| 2 | 10 | 9 | 10 | 10 |
| **3** | **10** | **10** | **10** | **9** |
| 4–7, 9 | 10 | 10 | 10 | 9–10 |
| **8** | **0** | **0** | **10** | **10** |

**scenario_3 flipped from a loss to 10/10 on every judge** — confirming §12's diagnosis
that it was the search rate-limit bug, not a prompt defect. All four judges now favour F3
over vanilla B, and the two with no shared lineage with F3 do so at 86% and 88%.

**scenario_8 is unchanged at 0/10 for both independent judges**, and it is now the *only*
scenario where they prefer B. Fixing resource quality removed every other disagreement and
left exactly one standing — the values disagreement. Judges 1 and 2 prefer B there because
it *"centers self-determination, validation, and collaborative planning… maintains
peer-role boundaries,"* i.e. the labelled-technique content (**"Validate + reflect"** over
*"It makes sense you'd feel frustrated"*) that the real CSPNJ provider rejected in as many
words: *"those are the things that we learn from the textbook, and we don't need it."*

That isolation is the cleanest version of this project's central claim: once retrieval
quality is controlled for, the residual gap between a naive or competency-framework judge
and a provider-grounded one is entirely about whether coaching a trained peer in their own
craft counts as a feature or a cost.

**Caveats unchanged:** Judge 3 shares an author and value model with F3's prompt, so its
100% is not independent confirmation; 9 scenarios; and no provider has seen F3.
