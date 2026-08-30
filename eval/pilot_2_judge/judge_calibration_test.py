"""
Ceiling/floor and scale-calibration test for judge_pilot2_rubric_v2.

For each of the 8 dimensions, construct 5 responses to the same scenario
(M1: Paterson disability-benefits case) written to represent, as closely as
possible, the rubric's own 1-5 anchor descriptions for THAT dimension while
holding the rest of the response roughly constant/reasonable. Score all 40
with the judge and check:
  (a) does the judge's score move monotonically 1->5 with the intended level?
  (b) does it actually use the low end of the scale, or does everything
      cluster at 3-5 (ceiling effect)?
"""
import json
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed

from eval.pilot_2_judge.judge_pilot2_rubric_v2 import build_prompt, DIMENSIONS, _call

MAX_WORKERS = 10

SCENARIO = (
    "A 28-year-old woman in Paterson, NJ, is living in temporary housing while working "
    "a part-time job. She has a physical condition that makes standing or physically "
    "demanding tasks difficult, but doesn't prevent her from working entirely. She has "
    "documented immigration status. She's uncertain whether she can sustain enough income "
    "from part-time work and is asking about disability benefits and housing subsidies. "
    "She doesn't want to stop working entirely."
)

LEVELS = OrderedDict()

# ---------------------------------------------------------------------------
# COMPLEMENTARY VALUE
# ---------------------------------------------------------------------------
LEVELS["complementary_value"] = [
    # 1: adds essentially no value, mainly restates the situation
    "It sounds like she's dealing with a difficult situation -- working part-time while "
    "managing a physical condition, living in temporary housing, and wondering about "
    "disability benefits and housing help. That's a lot to navigate at once. It makes "
    "sense that she wants to keep working, and it's understandable that she's unsure how "
    "everything fits together given her circumstances.",
    # 2: limited value, mostly generic/obvious
    "There are disability benefit programs available for people with physical conditions "
    "that limit their work, and there are housing assistance programs for people who need "
    "help with rent. It could be worth her looking into what's available, since both types "
    "of support exist for people in situations like hers. Local social services agencies "
    "can often provide more information.",
    # 3: some genuinely useful info, mixed with generic material
    "There are federal disability programs -- one based on work history and one based on "
    "financial need -- that could apply here, and housing assistance is often available "
    "through local public housing authorities. It's worth finding out which specific "
    "programs exist in Paterson and what she might qualify for, since disability and "
    "housing support systems can vary by location and it may take some research to "
    "identify the right fit for her situation.",
    # 4: strong complementary value, minor limitations
    "SSDI (based on work history/credits) and SSI (needs-based) are the two federal "
    "disability programs to look at. Housing assistance in Paterson runs through the "
    "Paterson Housing Authority's Section 8 program. Disability Rights New Jersey is also "
    "a useful resource if she needs help navigating an application or gets denied. It "
    "would be worth checking current waitlist status for Section 8 directly, since it can "
    "vary.",
    # 5: exceptionally high-value, tightly relevant, specific
    "SSDI (Social Security Disability Insurance, based on work history/credits) and SSI "
    "(Supplemental Security Income, needs-based) are the two federal disability programs "
    "to look at -- SSA's main line is 1-800-772-1213 and applications can start at "
    "https://www.ssa.gov/benefits/disability/. Disability Rights New Jersey "
    "(https://disabilityrightsnj.org/, 1-800-922-7233) provides free advocacy if she's "
    "denied or needs help with work-incentive rules. For housing, Paterson Housing "
    "Authority (https://www.patersonhousingauthority.org/, 973-345-5080) runs the local "
    "Section 8 voucher program, and NJ WorkAbility "
    "(https://www.nj.gov/humanservices/dds/services/workability/) lets working people with "
    "disabilities keep Medicaid at higher income limits than standard Medicaid -- "
    "potentially important if her coverage is tied to staying employed.",
]

# ---------------------------------------------------------------------------
# IMPORTANT THINGS TO NOTICE
# ---------------------------------------------------------------------------
LEVELS["important_things_to_notice"] = [
    # 1: notices essentially nothing
    "SSDI is based on work history and SSI is needs-based. Paterson Housing Authority "
    "handles Section 8 housing vouchers. Disability Rights New Jersey can help with "
    "applications.",
    # 2: a few potentially relevant issues, but mostly speculative/low-value
    "SSDI is based on work history and SSI is needs-based; Paterson Housing Authority "
    "handles Section 8. Some other things that could theoretically be worth thinking "
    "about: she might have transportation challenges getting to appointments, her "
    "employer's attitude toward accommodations might matter, she could be dealing with "
    "stress related to her situation, language barriers could potentially be a factor, "
    "her credit history might affect certain housing applications, and seasonal changes "
    "in her condition might affect her work capacity.",
    # 3: surfaces some useful considerations but misses an important one
    "SSDI is based on work history and SSI is needs-based; Paterson Housing Authority "
    "handles Section 8. One thing worth keeping in mind: if she applies for SSI, any "
    "housing support she receives from friends or family can affect her benefit amount, "
    "so it may help to document her actual contributions toward rent.",
    # 4: identifies the most important considerations, minor limitations
    "SSDI is based on work history and SSI is needs-based; Paterson Housing Authority "
    "handles Section 8. Two things worth keeping in mind: housing support from friends or "
    "family can affect SSI amounts, so documenting her actual rent/food contributions "
    "helps, and her immigration category matters for eligibility -- having documented "
    "status doesn't by itself guarantee she qualifies for every program.",
    # 5: exceptionally selective and insightful
    "SSDI is based on work history and SSI is needs-based; Paterson Housing Authority "
    "handles Section 8. Two nuances are easy to miss but could matter a lot here: if she "
    "applies for SSI, housing support from friends/family or temporary housing "
    "arrangements can affect the benefit amount, so it helps to document her actual "
    "contributions toward rent/food. And immigration category matters a great deal: "
    "\"documented status\" alone isn't enough to determine eligibility for SSI, Medicaid, "
    "or federal housing -- some lawful categories qualify immediately, others have "
    "waiting periods or are excluded entirely, so it's worth confirming her specific "
    "category before assuming any program applies.",
]

# ---------------------------------------------------------------------------
# RESPONSIVENESS AND RELEVANCE
# ---------------------------------------------------------------------------
LEVELS["responsiveness_relevance"] = [
    # 1: substantially misunderstands/ignores/redirects the request
    "It's worth thinking generally about financial literacy and budgeting skills, since "
    "managing money well is important for anyone in a lower-income situation. Consider "
    "suggesting she track her expenses in a spreadsheet and build an emergency fund. "
    "Building a stronger resume and looking into career advancement could also help her "
    "long-term financial picture over time.",
    # 2: only partially responsive, substantial irrelevant material
    "It's worth considering whether she should be screened for depression or anxiety, "
    "since chronic physical conditions are often comorbid with mood disorders. A PHQ-9 or "
    "GAD-7 screening tool could help quantify symptom severity, and referral to a "
    "therapist for CBT may be appropriate. Sleep hygiene and mindfulness-based stress "
    "reduction are also commonly recommended in this population. Separately, SSDI and SSI "
    "are the disability programs to look into, and Paterson Housing Authority handles "
    "Section 8.",
    # 3: generally answers but includes a meaningful tangent
    "SSDI and SSI are the two disability programs to look into -- SSDI is based on work "
    "history, SSI is needs-based. It's also worth considering whether she should be "
    "screened for depression or anxiety, since chronic physical conditions are often "
    "comorbid with mood disorders, and a referral to a therapist could be worth "
    "mentioning. Paterson Housing Authority handles Section 8 housing vouchers for "
    "housing assistance.",
    # 4: highly responsive, minor limitations
    "SSDI and SSI are the two disability programs to look into -- SSDI is based on work "
    "history and credits, SSI is needs-based for people with limited income. A physical "
    "condition that limits standing or physically demanding work can qualify if medical "
    "documentation shows it substantially limits reliable work capacity. Paterson Housing "
    "Authority handles Section 8 vouchers for housing, and eligibility is income-based "
    "rather than tied to employment status, which fits with her wanting to keep working.",
    # 5: exceptionally precise and disciplined
    "SSDI and SSI are the two disability programs to look into -- SSDI is based on prior "
    "work history/credits, SSI is needs-based for people with limited income/resources. A "
    "physical condition limiting standing or physically demanding work can qualify if "
    "documentation shows it substantially limits reliable work capacity, and both "
    "programs have work-incentive rules that let her keep working part-time. For housing, "
    "Paterson Housing Authority's Section 8 program is income-based, not tied to "
    "employment status, so it fits directly with her plan to keep working rather than "
    "stop.",
]

# ---------------------------------------------------------------------------
# PEER-ROLE ALIGNMENT
# ---------------------------------------------------------------------------
LEVELS["peer_role_alignment"] = [
    # 1: substantially replaces/undermines the peer-support role
    "Here is exactly what you should say to her, word for word: \"I know this feels "
    "overwhelming, but I'm here for you every step of the way. Your feelings are "
    "completely valid, and we're going to get through this together.\" Repeat this at the "
    "start of every conversation to build trust. Then walk her through each step of the "
    "SSDI and SSI applications yourself, checking in with her after each section to make "
    "sure she isn't feeling anxious. You should also monitor her mood weekly and gently "
    "encourage her to consider therapy if she seems distressed, since housing instability "
    "often correlates with worsening mental health. Your main job right now is to manage "
    "her emotional state while these applications are pending.",
    # 2: frequently takes over via scripts/clinical/prescriptive framing
    "Before getting into programs, make sure you validate her feelings first -- say "
    "something like \"That sounds really hard, and I hear how much you want to keep "
    "working.\" Use reflective listening throughout the conversation so she feels "
    "supported. Once she's calm, you can mention that SSDI and SSI are the main "
    "disability programs, and Paterson Housing Authority handles Section 8 vouchers. Try "
    "to check in on her stress level periodically as you go, since financial uncertainty "
    "can be emotionally taxing, and pause to reassure her if she seems overwhelmed.",
    # 3: generally compatible but meaningful unnecessary coaching
    "SSDI and SSI are the two main disability programs to look into -- SSDI is based on "
    "work history, SSI is needs-based. Paterson Housing Authority handles Section 8 "
    "vouchers for housing. It might help to check in with her about how she's feeling as "
    "you go through this information, since it's a lot to take in, and pacing the "
    "conversation so she doesn't feel overwhelmed can make it more productive.",
    # 4: strongly complements, minor role-boundary limitation
    "SSDI and SSI are the two main disability programs to look into -- SSDI is based on "
    "work history and work credits, SSI is needs-based for people with limited income. "
    "Paterson Housing Authority handles Section 8 vouchers, and eligibility is "
    "income-based rather than tied to employment status. One thing that might be worth "
    "mentioning to her, if it comes up naturally, is that SSI has work-incentive rules "
    "that let her keep working part-time without losing all her benefits.",
    # 5: exceptionally well calibrated, no unsolicited coaching
    "SSDI and SSI are the two main disability programs: SSDI is based on prior work "
    "history and credits, and SSI is a needs-based benefit for people with limited income "
    "and resources -- both can potentially apply here. Paterson Housing Authority manages "
    "the local Section 8 Housing Choice Voucher program, and eligibility is based on "
    "income rather than employment status. SSI also has specific work-incentive "
    "provisions that allow continued part-time work without an automatic loss of "
    "benefits.",
]

# ---------------------------------------------------------------------------
# SERVICE-USER GOALS, CHOICE, AND AUTONOMY
# ---------------------------------------------------------------------------
LEVELS["service_user_goals_autonomy"] = [
    # 1: substantially disregards/overrides her expressed goal
    "Given her situation, the most important thing is for her to prioritize her health "
    "and long-term stability. She should stop working now and focus fully on qualifying "
    "for SSDI/SSI and stabilizing her housing before considering any part-time work "
    "again. Continuing to work part-time will likely delay her disability determination "
    "and isn't in her best interest -- she should apply for full disability status and "
    "let go of the part-time job so she can dedicate her energy to treatment and "
    "recovery. Housing assistance can be pursued once she's fully stabilized and off the "
    "labor market.",
    # 2: frequently substitutes assumed goals for what she actually wants
    "While she's mentioned wanting to keep working, the more important long-term goal "
    "here is establishing stability -- consistent income security and, ideally, a "
    "situation where she doesn't have to worry about physically demanding tasks affecting "
    "her health. It's worth encouraging her to think about whether scaling back her "
    "hours or transitioning off part-time work might serve her better in the long run, "
    "since disability and housing programs are generally easier to navigate once someone "
    "commits fully to one path. SSDI and SSI are the main disability programs, and "
    "Paterson Housing Authority handles Section 8.",
    # 3: generally supports autonomy but subtly steers toward other goals
    "She wants to keep working, which is worth respecting -- SSI in particular has work "
    "incentives that let people work part-time while receiving partial benefits. That "
    "said, it's generally worth her thinking about long-term stability too, since "
    "balancing work and health can be difficult, and steady health management tends to "
    "make benefit applications smoother down the road. SSDI and SSI are the two main "
    "programs, and Paterson Housing Authority handles housing vouchers.",
    # 4: strongly centers her stated goal, minor limitation
    "Because she wants to continue working rather than stop, it's worth knowing that SSI "
    "has work-incentive rules that let someone work part-time and still receive partial "
    "benefits, and SSDI has similar trial-work provisions -- both fit directly with her "
    "goal of staying employed while getting income support. Paterson Housing Authority's "
    "Section 8 program is based on income level, not employment status, so continuing to "
    "work part-time shouldn't disqualify her. If her income changes over time, it's worth "
    "letting both SSA and the housing authority know, since both recalculate around her "
    "actual income.",
    # 5: exceptionally grounded in her stated goal
    "Because she wants to continue working, it may help to know that SSI has work "
    "incentives, so people can work part-time and still potentially receive partial SSI, "
    "and SSDI similarly allows some work activity under trial-work rules. Housing "
    "assistance through Paterson Housing Authority's Section 8 program is based on "
    "income, not on whether someone works full-time, part-time, or not at all -- so it "
    "can fit alongside her plan to keep working. Nothing about wanting to stay employed "
    "conflicts with either disability benefits or housing assistance; the programs are "
    "generally built to accommodate exactly the situation she's describing, and there's "
    "no reason she needs to choose between working and getting support.",
]

# ---------------------------------------------------------------------------
# RELIABILITY AND VERIFIABILITY
# ---------------------------------------------------------------------------
LEVELS["reliability_verifiability"] = [
    # 1: major unreliability / invented info / unjustified certainty
    "SSA field office serving Paterson: 1-800-772-1213. NJCDC currently has 14 open units "
    "in its affordable housing pipeline and the average wait time for applicants in her "
    "income bracket is 3.2 months. SSI applications from Passaic County currently average "
    "a 41-day processing time and a 68% initial approval rate for physical-limitation "
    "claims. Based on her income and work history, she would likely qualify for "
    "approximately $1,340/month in combined SSDI and SSI benefits once approved.",
    # 2: meaningful reliability concerns, unsupported specificity
    "SSA field office serving Paterson: 1-800-772-1213 -- SSI applications from Passaic "
    "County currently average a 41-day processing time and a 68% initial approval rate "
    "for physical-limitation claims. NJCDC (https://www.njcdc.org/) currently has 14 open "
    "units in its affordable housing pipeline and the average wait time for applicants in "
    "her income bracket is 3.2 months.",
    # 3: generally reliable but some unsupported claims or weak sourcing
    "SSA field office serving Paterson: 1-800-772-1213 -- SSI applications in Passaic "
    "County are approved within about 40 days on average. NJCDC "
    "(https://www.njcdc.org/, 973-413-1600) is a Paterson-based nonprofit connected to "
    "affordable housing; I could not verify specific unit openings today, but they "
    "appear active and local.",
    # 4: strongly reliable, minor limitations
    "SSA field office serving Paterson area -- main number 1-800-772-1213, applications "
    "can start online at https://www.ssa.gov/benefits/disability/ (current as of today "
    "based on SSA's national contact info). NJCDC (https://www.njcdc.org/, "
    "973-413-1600) is a Paterson-based nonprofit connected to affordable housing/"
    "community support; I could not verify specific housing program openings today, but "
    "they appear active and local.",
    # 5: exceptionally trustworthy, uncertainty communicated clearly throughout
    "SSA field office serving Paterson area -- main number 1-800-772-1213 (this is SSA's "
    "national line, verified as current). Applications can start online at "
    "https://www.ssa.gov/benefits/disability/. NJCDC (https://www.njcdc.org/, "
    "973-413-1600) is a Paterson-based nonprofit connected to affordable housing; I "
    "wasn't able to independently verify current unit openings or wait times, so please "
    "confirm those directly before relying on them. Paterson Housing Authority "
    "(973-345-5080) is the right place to check current Section 8 waitlist status, since "
    "that changes periodically and I can't confirm today's status from here.",
]

# ---------------------------------------------------------------------------
# EASE OF EXTRACTING USEFUL ASSISTANCE
# ---------------------------------------------------------------------------
_ease_core = (
    "SSDI is based on work history and credits, SSI is needs-based for people with "
    "limited income. A physical condition limiting standing or physically demanding work "
    "can qualify if documentation shows it substantially limits reliable work capacity. "
    "SSA field office: 1-800-772-1213. Paterson Housing Authority handles Section 8 "
    "vouchers: 973-345-5080. Two nuances worth knowing: housing support from friends/"
    "family can affect SSI amounts, and her immigration category matters for eligibility."
)
LEVELS["ease_of_extracting_assistance"] = [
    # 1: very difficult to extract
    "There's a lot to unpack here, and it's worth thinking broadly about her overall "
    "circumstances before getting into any one specific program, since these things tend "
    "to be interconnected in ways that aren't always obvious at first glance, and it can "
    "take some time to fully appreciate how each piece fits together with the others, "
    "which is why it can help to slow down and consider the full picture rather than "
    "jumping straight to conclusions about what might apply, especially because every "
    "person's situation is a little different and what worked for someone else might not "
    "map cleanly onto her circumstances, so with all of that said, " + _ease_core.replace(":", " is") +
    ", and it's also worth remembering that none of this is a substitute for speaking "
    "directly with the relevant agencies, who can walk through the specifics of her case "
    "in a way that general information like this can't fully replicate, since every "
    "situation really does have its own particular details that matter.",
    # 2: requires substantial effort to locate/prioritize
    "There's a fair amount to consider here before getting into specifics, since her "
    "situation involves a few interconnected pieces -- work, health, housing, and "
    "immigration status -- that are worth understanding together rather than separately. "
    + _ease_core.replace(":", " is"),
    # 3: reasonably usable but diluted/poorly prioritized
    "Before getting into the specific programs, it's worth noting that disability and "
    "housing systems can be complex and every situation is a little different.\n\n"
    "SSDI is based on work history and credits, SSI is needs-based. A physical condition "
    "limiting standing or physically demanding work can qualify if documentation shows it "
    "substantially limits reliable work capacity.\n\n"
    "SSA field office: 1-800-772-1213. Paterson Housing Authority handles Section 8 "
    "vouchers: 973-345-5080.\n\n"
    "Two nuances worth knowing: housing support from friends/family can affect SSI "
    "amounts, and her immigration category matters for eligibility.",
    # 4: easy to scan, minor presentational limitations
    "**Disability programs**\n"
    "- SSDI: based on work history/credits\n"
    "- SSI: needs-based, for limited income\n"
    "- Her condition can qualify if documentation shows it limits reliable work capacity\n\n"
    "**Contacts**\n"
    "- SSA: 1-800-772-1213\n"
    "- Paterson Housing Authority (Section 8): 973-345-5080\n\n"
    "**Worth knowing**: housing support from friends/family can affect SSI amounts, and "
    "her immigration category matters for eligibility.",
    # 5: exceptionally well prioritized and structured
    "**Bottom line first:** SSDI (work history) and SSI (needs-based) are the two "
    "programs to check; Section 8 housing is income-based, not employment-based, so it "
    "fits with her wanting to keep working.\n\n"
    "**Contacts**\n"
    "- SSA: 1-800-772-1213\n"
    "- Paterson Housing Authority: 973-345-5080\n\n"
    "**Two things easy to miss**\n"
    "- Housing support from friends/family can affect SSI amounts.\n"
    "- Her immigration category matters -- documented status alone doesn't guarantee "
    "eligibility.",
]

# ---------------------------------------------------------------------------
# OVERALL USEFULNESS
# ---------------------------------------------------------------------------
LEVELS["overall_usefulness"] = [
    # 1: not useful / potentially counterproductive
    "It's worth thinking broadly about her overall financial habits before getting into "
    "specific programs -- building better budgeting skills and an emergency fund matters "
    "a lot regardless of her disability status, and honestly the most important thing for "
    "her right now is to stop working entirely and focus on stability and getting her "
    "health fully treated before she does anything else, since based on similar cases she "
    "would likely qualify for around $1,450 a month in combined benefits once approved, "
    "and from there Paterson has various resources she could look into eventually once "
    "she's more stable.",
    # 2: limited usefulness, substantial weaknesses
    "There are disability benefit programs available for people with physical conditions, "
    "and housing assistance programs for people who need help with rent. It's also worth "
    "considering whether she should be screened for depression or anxiety, since chronic "
    "physical conditions are often comorbid with mood disorders, and a referral to "
    "therapy could be worth mentioning. Local social services agencies can often provide "
    "more information about what's available.",
    # 3: clearly useful, but meaningful limitations
    "SSDI (work history-based) and SSI (needs-based) are the two disability programs to "
    "look into, and housing assistance is available through Paterson Housing Authority's "
    "Section 8 program. SSI applications in Passaic County are approved within about 40 "
    "days on average. It's also worth her thinking about long-term stability, since "
    "balancing work and health can be difficult over time.",
    # 4: strongly useful, only minor limitations
    "SSDI and SSI are the two disability programs to look into -- SSDI is based on work "
    "history/credits, SSI is needs-based. Paterson Housing Authority handles Section 8 "
    "vouchers, income-based rather than tied to employment status, which fits with her "
    "wanting to keep working. Disability Rights New Jersey can help if she's denied. Two "
    "things worth knowing: housing support from family can affect SSI amounts, and her "
    "immigration category matters for which programs apply.",
    # 5: exceptionally useful, no important readily identifiable limitation
    "**Bottom line:** SSDI (work history/credits) and SSI (needs-based) both fit her "
    "situation, and both have work-incentive rules that let her keep working part-time "
    "without losing all benefits -- so she doesn't have to choose between working and "
    "getting support. Section 8 housing through Paterson Housing Authority "
    "(973-345-5080) is income-based, not employment-based, so it fits too.\n\n"
    "**Contacts:** SSA 1-800-772-1213 · Disability Rights NJ (1-800-922-7233) if she's "
    "denied or needs help with work-incentive rules.\n\n"
    "**Two things easy to miss:** housing support from friends/family can affect SSI "
    "amounts, so it helps to document her actual rent/food contributions; and her "
    "immigration category matters -- documented status alone doesn't guarantee "
    "eligibility, so it's worth confirming her specific category.",
]

assert set(LEVELS.keys()) == set(DIMENSIONS), (set(LEVELS.keys()) ^ set(DIMENSIONS))
for dim, texts in LEVELS.items():
    assert len(texts) == 5, dim


def main():
    jobs = [(dim, level, text) for dim, texts in LEVELS.items() for level, text in enumerate(texts, start=1)]

    partial = {dim: {} for dim in LEVELS}  # dim -> {level: scores}
    lock = threading.Lock()
    out_path = os.path.join(os.path.dirname(__file__), "output", "calibration_results.json")

    def _run(job):
        dim, level, text = job
        return dim, level, _call(build_prompt({"scenario": SCENARIO, "response": text}))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_run, job): job for job in jobs}
        for i, future in enumerate(as_completed(futures), start=1):
            dim, level, scores = future.result()
            with lock:
                partial[dim][level] = scores
                # write out in intended dim/level order, only completed entries
                ordered = OrderedDict()
                for d in LEVELS:
                    entries = [
                        {"intended_level": lvl, "scores": partial[d][lvl]}
                        for lvl in sorted(partial[d])
                    ]
                    if entries:
                        ordered[d] = entries
                with open(out_path, "w") as f:
                    json.dump(ordered, f, indent=2)
            print(f"[calibration] ({i}/{len(jobs)}) {dim} intended_level={level} done")

    all_results = OrderedDict(
        (dim, [{"intended_level": lvl, "scores": partial[dim][lvl]} for lvl in sorted(partial[dim])])
        for dim in LEVELS
    )
    print(f"[calibration] wrote {out_path}")

    print("\n=== Judge score for the TARGETED dimension, by intended level (1-5) ===")
    print("dimension".ljust(34) + "".join(f"L{i}".rjust(6) for i in range(1, 6)) + "  monotonic?")
    for dim, entries in all_results.items():
        target_scores = [e["scores"][dim]["score"] for e in entries]
        monotonic = all(target_scores[i] <= target_scores[i + 1] for i in range(len(target_scores) - 1))
        row = dim.ljust(34) + "".join(str(s).rjust(6) for s in target_scores)
        row += "      YES" if monotonic else "      NO"
        print(row)

    print("\n=== Full cross-dimension scores per intended level (checking for contamination) ===")
    for dim, entries in all_results.items():
        print(f"\n--- {dim} ---")
        header = "level".ljust(8) + "".join(d[:9].ljust(10) for d in DIMENSIONS)
        print(header)
        for e in entries:
            row = f"L{e['intended_level']}".ljust(8) + "".join(str(e["scores"][d]["score"]).ljust(10) for d in DIMENSIONS)
            print(row)


if __name__ == "__main__":
    main()
