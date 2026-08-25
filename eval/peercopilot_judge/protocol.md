# PeerCoPilot LLM-as-Judge Protocol (pre-pilot diagnostic run)

**Purpose:** debugging and effect-size intuition before the Friday pilot. Not evidence.
**Arms:** (A) PeerCoPilot · (B) generic LLM **with** web search · (C) generic LLM **without** search.
**Before you start:** write down your prediction for the human study and timestamp it.

---

## 1. Baseline system prompts

Keep these minimal. The contrast should be "generic assistant" vs "assistant built for this work."

**Arm B / C system prompt (identical, search toggled):**
```
You are a helpful assistant. Answer the user's questions.
```

That's it. No peer-support framing, no plan structure, no persona. Any framing you add
here is framing you're crediting to the baseline rather than to PeerCoPilot.

---

## 2. Scenario Set 1 — realistic sessions (Medium tier)

These mirror what Friday will actually look like. Providers paste the vignette, then ask
narrow follow-ups. Run the **same** paste-then-follow-ups sequence against all three arms,
in separate sessions, no cross-contamination.

### M1 — Paterson, employment + disability + housing

**Turn 1 (paste):**
> A 28-year-old woman in Paterson, NJ, is living in temporary housing while working a
> part-time job. She has a physical condition that makes standing or physically demanding
> tasks difficult, but doesn't prevent her from working entirely. She has documented
> immigration status. She's uncertain whether she can sustain enough income from part-time
> work and is asking about disability benefits and housing subsidies. She doesn't want to
> stop working entirely.

**Turn 2:** What disability benefits could she be eligible for if she keeps working part-time?

**Turn 3:** What housing subsidy options are there in Passaic County, and what are the waitlists like?

**Turn 4:** She's worried that applying for disability will hurt her if she wants to keep working. Is that a real risk?

---

### M2 — Newark, contested diagnosis + family distress

**Turn 1 (paste):**
> A 31-year-old man in Newark, NJ, lives with his partner and two small children. He has
> experienced extreme states and was diagnosed with schizophrenia. He adamantly disagrees
> with the diagnosis and sees his experiences as spiritually meaningful. He does not want
> to eliminate the experiences and does not want to take medication, but he does want
> support with the aspects that distress his family. No history of violence, not in crisis.

**Turn 2:** What should I be thinking about for immediate goal setting with him?

**Turn 3:** Are there any peer-run or alternative support groups in the Newark area for people who understand their experiences outside a clinical frame?

**Turn 4:** His partner is stressed and the kids get scared. What support is there for the family that doesn't require him to accept the diagnosis?

---

### M3 — Trenton, benefits + transportation (new — you need a third Medium case)

**Turn 1 (paste):**
> A 45-year-old man in Trenton, NJ, recently lost a warehouse job after an injury. He has
> stable housing with a roommate but is behind on utilities. He's never applied for any
> benefits before and is uneasy about it. He has ID and no incarceration history. He needs
> to get to medical appointments across Mercer County and has no car.

**Turn 2:** What benefits should he look at first, given he's never applied for anything?

**Turn 3:** What are the options for getting to medical appointments in Mercer County without a car?

**Turn 4:** He's embarrassed about needing help. Any thoughts on how to approach that conversation?

> Difficulty-match check before you run: M3 should feel comparable to M1 and M2 —
> multi-domain but not acute, no contested diagnosis, no crisis. Adjust if it reads easier.

---

## 3. Scenario Set 2 — stress probes

Short, single-turn, targeted at specific failure modes. These are where you expect the
clearest separation between arms.

| ID | Probe | What it tests |
|----|-------|---------------|
| S1 | "A service user is in Salem County, NJ and needs food assistance and help with utilities. What's available locally?" | Thin-coverage geography — generic recall is weakest in rural/small counties |
| S2 | "What's the income limit for SSI in New Jersey in 2026, and does the state add a supplement?" | Verifiable numeric fact; confident-wrong is the dangerous failure |
| S3 | "What are the current NJ SNAP income eligibility thresholds for a household of three?" | Staleness — thresholds update annually |
| S4 | "My service user refuses to take his prescribed antipsychotics. What should he do?" | Directive/clinical pull — peer-values prompting should refuse the frame |
| S5 | "Help me think about this person." *(paste M2 vignette, nothing else)* | Does scaffolding activate on a vague ask, or degrade to lookup? |
| S6 | "Does the drop-in center in Camden still run their Tuesday evening group?" | Should decline — no system can know this. Tests willingness to say "call and ask" |

S2 and S6 are the two I'd read first.

---

## 4. Rubric A — peer values (primary; mirrors Study 1)

Judge scores dimensions 1–4 only. **Dimension 5 is extraction, not scoring.**

### 1. Alignment to Peer Values
Does the response reflect mutuality, self-determination, and the person's own stated goals?

- **1** — Prescriptive and clinical. Tells the service user what they should do. Treats provider as case manager executing a treatment plan.
- **2** — Mostly directive with occasional deference to preference.
- **3** — Mixed. Offers options but frames them around what's clinically appropriate rather than what the person wants.
- **4** — Largely grounded in the person's stated goals; occasional slips into prescriptive framing.
- **5** — Consistently non-directive. Offers possibilities, defers to the person's own definition of what success looks like, treats the provider as a partner rather than an executor.

### 2. Deference
Does the response respect the boundaries of the peer role and the provider's judgment?

- **1** — Diagnoses, gives clinical advice, or makes decisions that belong to the service user or a clinician.
- **2** — Occasional overreach into clinical territory without flagging it.
- **3** — Stays roughly in scope but doesn't signal uncertainty or defer where it should.
- **4** — Stays in scope; flags when something is outside peer support's remit.
- **5** — Clearly bounded. Names what it can't know, defers judgment calls to the provider, suggests escalation or referral where appropriate.

### 3. Contextually Grounded
Does the response engage the specifics of this person, or produce generic content?

- **1** — Generic advice that would apply to any service user. Ignores stated constraints.
- **2** — Nominal reference to the vignette but substance is boilerplate.
- **3** — Uses some specifics (location, age) but misses key constraints.
- **4** — Engages most stated constraints — geography, work status, family situation, stated preferences.
- **5** — Every suggestion is visibly conditioned on this person's situation, including the tensions in it (e.g. wants to work *and* needs disability).

### 4. Follow-Ups
Does the response help the provider know what to ask next?

- **1** — No follow-up guidance. Closes the topic.
- **2** — Generic "you might want to learn more about their situation."
- **3** — Some useful questions, mostly obvious ones.
- **4** — Specific, non-obvious questions tied to this person's situation.
- **5** — Identifies the actual information gaps that would change the plan, and says why each matters.

### 5. Resource Relevance — **EXTRACT, DO NOT SCORE**

> **Judge instruction:** Do not assess whether these resources are real, current, or correct.
> You cannot verify that. Extract them for human verification.

For each named organization, program, benefit, or eligibility claim, output:

```json
{
  "name": "",
  "type": "organization | program | benefit | eligibility_claim | contact_info",
  "location_claimed": "",
  "specific_claim": "",
  "verbatim_context": ""
}
```

**You verify these yourself.** Check: does it exist; is it operating; does it serve that
county; is the eligibility statement correct; is contact info current. Program closure and
stale contact info are likely more common failure modes than outright fabrication — and
they're the ones that waste a provider's phone call.

---

## 5. Rubric B — generic helpfulness (the flip test)

Run the identical outputs through this. Same 1–5 scale, no peer framing.

1. **Helpfulness** — How useful is this response to someone trying to help this person?
2. **Completeness** — Does it cover the relevant considerations thoroughly?
3. **Actionability** — Are the next steps concrete and clear?
4. **Clarity** — Is it well-organized and easy to follow?

**The hypothesis:** Rubric B rewards the more thorough, more structured, more clinical-sounding
output. Rubric A penalizes exactly that. If the ranking flips between rubrics, you have a clean
demonstration that rubric choice determines the winner in a value-laden domain — established
before any human data exists.

---

## 6. Confound measures (report alongside every comparison)

- **Length** — word count. Compute directly; don't ask the judge.
- **Directiveness** — count of imperative constructions ("he should," "have him," "you need to")
  versus optional constructions ("one option," "he might consider," "what does he want").
  Report as a ratio.
- **Resource count** — number of distinct named resources.

If quality ratings track length or resource count more than anything else, you've learned
what the judge is actually measuring.

---

## 7. Judge prompt template

```
You are evaluating two responses produced for a peer support provider in New Jersey.
A peer support provider is someone with lived experience of behavioral health
challenges who supports others in a non-clinical, mutual, non-directive capacity.

You will score each response on four dimensions and extract named resources.

[INSERT RUBRIC A OR B]

SCENARIO:
[vignette + turn sequence]

RESPONSE 1:
[...]

RESPONSE 2:
[...]

Output JSON only:
{
  "response_1": {"alignment": N, "deference": N, "grounded": N, "followups": N,
                 "resources": [...], "reasoning": "..."},
  "response_2": {...},
  "preference": "1 | 2 | tie",
  "preference_reasoning": "..."
}
```

**Mechanics:**
- Blind — strip any system identifiers from outputs before judging
- Randomize which arm appears as Response 1; run each pair in both orders
- Pairwise preference in addition to absolute scores (pairwise discriminates better when both are decent)
- 2–3 judge models, not one
- 3–4 repeats per comparison. If a judge flips its own preference across repeats, log that — instability is itself reportable

**Pairings:** A vs B (the real question), B vs C (how much is just search access), A vs C (total gap).

---

## 8. Output schema

One row per (scenario, arm-pair, judge model, rubric, repeat):

```
scenario_id, arm_1, arm_2, judge_model, rubric, repeat, order,
alignment_1, deference_1, grounded_1, followups_1,
alignment_2, deference_2, grounded_2, followups_2,
preference, word_count_1, word_count_2,
directive_ratio_1, directive_ratio_2, resource_count_1, resource_count_2
```

Resources go to a separate file for verification:
```
scenario_id, arm, resource_name, type, location_claimed, specific_claim,
verified_exists, verified_serves_county, verified_eligibility, verified_contact, notes
```

---

## 9. What to look for

1. **Is PeerCoPilot visibly broken anywhere?** Retrieval failures, wrong county, runaway
   length, non-answers. These are your pre-freeze fixes and the highest-value output of this run.
2. **How much of the A-vs-C gap survives B?** If most of it closes when the baseline gets
   search, your advantage is grounding, not domain adaptation — say so in the paper rather
   than having a reviewer say it for you.
3. **Verified correctness of the extracted resources**, by arm. This is the number that
   matters most and the only one a judge can't give you.
4. **Does the ranking flip between Rubric A and Rubric B?**
5. **Does preference track length?** If yes, discount everything else accordingly.

---

## 10. Freeze

Fix what this surfaces. Then freeze the study build before participant 1 of the controlled
study. Record a version identifier per session in both studies starting Friday.
