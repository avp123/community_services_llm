"""
Controlled sensitivity test for judge_pilot2_rubric_v2: take a real response
that scored well across the board (M1/Version A), and construct 7 variants,
each degrading exactly one thing that dimension X is supposed to detect,
while leaving everything else as close to the baseline as possible. Score
baseline + all 7 variants and check whether the targeted dimension actually
drops, and whether other dimensions stay roughly stable (discriminant
validity) or get dragged down too (halo effect).
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

BASELINE = """A few things may be useful for her to know up front:

- Working part-time does not automatically disqualify someone from disability benefits or housing assistance.
- For federal disability programs, the key question is usually whether she can sustain "substantial gainful activity" consistently, not whether she can work at all.
- Immigration status matters for eligibility, but many documented statuses qualify for at least some benefits or housing programs.

For disability income, these are probably the main programs to look at:

- SSDI (Social Security Disability Insurance): based on prior work history and work credits. Someone age 28 may or may not have enough credits depending on how long she has worked.
- SSI (Supplemental Security Income): needs-based disability benefit for people with limited income/resources. SSI can sometimes fit younger workers with limited earnings.

A physical condition that limits standing, lifting, or physically demanding work can qualify if medical documentation shows it substantially limits reliable work capacity over time. SSA often looks closely at:
- whether she can maintain full-time work consistently,
- how symptoms affect attendance/endurance,
- whether seated or less physically demanding jobs are realistically available to her given experience and limitations.

Because she wants to continue working, it may help to know:
- SSI has work incentives, so people can work part-time and still potentially receive partial SSI.
- SSDI also allows some work activity under trial work and related rules.
- Medicaid eligibility can sometimes continue for working disabled beneficiaries through NJ programs.

A benefits planner can be especially valuable here because the interaction between wages, disability benefits, and housing subsidies gets complicated quickly.

Resources that may help:

- SSA field office serving Paterson area
  - Social Security Administration
  - Main number: 1-800-772-1213
  - SSI/SSDI applications can also start online: https://www.ssa.gov/benefits/disability/
  - Current as of today based on SSA national contact info.

- Disability Rights New Jersey
  - Provides disability benefits advocacy and legal information.
  - https://disabilityrightsnj.org/
  - Main phone: 1-800-922-7233
  - Particularly useful if she is denied initially or needs help understanding work incentives.

- NJ WorkAbility / Medicaid for Working Disabled
  - Allows some people with disabilities who are working to keep Medicaid with higher income limits than standard Medicaid.
  - https://www.nj.gov/humanservices/dds/services/workability/
  - This can matter a lot if medical coverage is tied to her ability to keep working.

For housing:

- Paterson Housing Authority
  - Public housing and Housing Choice Voucher (Section 8) programs.
  - https://www.patersonhousingauthority.org/
  - Phone: 973-345-5080
  - Waitlists may be long or periodically closed, so it's worth checking current status directly.

- New Jersey Community Development Corporation (NJCDC)
  - Paterson-based nonprofit connected to affordable housing/community support.
  - https://www.njcdc.org/
  - Phone: 973-413-1600
  - I could not verify specific housing program openings today, but they appear active and local.

Two important nuances that are easy to miss:
- If she applies for SSI, housing support from friends/family or temporary housing arrangements can affect benefit amounts, so it helps to document her actual contributions toward rent/food.
- Immigration category matters a lot. "Documented status" is not enough by itself to determine eligibility for SSI, Medicaid, or federal housing programs. Some lawful statuses qualify immediately; others have waiting periods or restrictions.

If you want, I can also help narrow down:
- likely SSI/SSDI eligibility based on work history and income,
- what immigration categories generally qualify for SSI/housing,
- or current Passaic County housing waitlists and supportive housing options."""

VARIANTS = OrderedDict()

RESOURCES_BLOCK = """Resources that may help:

- SSA field office serving Paterson area
  - Social Security Administration
  - Main number: 1-800-772-1213
  - SSI/SSDI applications can also start online: https://www.ssa.gov/benefits/disability/
  - Current as of today based on SSA national contact info.

- Disability Rights New Jersey
  - Provides disability benefits advocacy and legal information.
  - https://disabilityrightsnj.org/
  - Main phone: 1-800-922-7233
  - Particularly useful if she is denied initially or needs help understanding work incentives.

- NJ WorkAbility / Medicaid for Working Disabled
  - Allows some people with disabilities who are working to keep Medicaid with higher income limits than standard Medicaid.
  - https://www.nj.gov/humanservices/dds/services/workability/
  - This can matter a lot if medical coverage is tied to her ability to keep working.

For housing:

- Paterson Housing Authority
  - Public housing and Housing Choice Voucher (Section 8) programs.
  - https://www.patersonhousingauthority.org/
  - Phone: 973-345-5080
  - Waitlists may be long or periodically closed, so it's worth checking current status directly.

- New Jersey Community Development Corporation (NJCDC)
  - Paterson-based nonprofit connected to affordable housing/community support.
  - https://www.njcdc.org/
  - Phone: 973-413-1600
  - I could not verify specific housing program openings today, but they appear active and local."""

# 1. Complementary Value down: strip the specific resources/programs/contacts,
# replace with generic restatement of what the provider already said.
GENERIC_RESTATEMENT = (
    "In general, there are disability benefit programs and housing assistance programs "
    "that people in her kind of situation can look into. It's worth checking what disability "
    "benefits she might qualify for, and separately looking into what housing assistance "
    "might be available, since housing and income are both things you mentioned being "
    "uncertain about. There are usually organizations in most areas that help people "
    "navigate systems like this."
)
VARIANTS["complementary_value_down"] = BASELINE.replace(RESOURCES_BLOCK, GENERIC_RESTATEMENT)

# 2. Important Things to Notice down: replace the 2 sharp, consequential
# nuances with a long, unprioritized, speculative list.
ORIGINAL_NUANCES = """Two important nuances that are easy to miss:
- If she applies for SSI, housing support from friends/family or temporary housing arrangements can affect benefit amounts, so it helps to document her actual contributions toward rent/food.
- Immigration category matters a lot. "Documented status" is not enough by itself to determine eligibility for SSI, Medicaid, or federal housing programs. Some lawful statuses qualify immediately; others have waiting periods or restrictions."""

SPECULATIVE_LIST = """Some other things that could theoretically be worth thinking about:
- She might have transportation challenges getting to appointments.
- She could have caregiving responsibilities that affect her schedule.
- Her employer's attitude toward accommodations might matter.
- She might be dealing with stress or anxiety related to her situation.
- Language barriers could potentially be a factor for some applicants.
- Her credit history might affect certain housing applications.
- She could have other family members who also need support.
- Seasonal changes in her condition might affect her work capacity.
- Access to reliable internet could affect her ability to apply online.
- She might not have a permanent mailing address, which can complicate paperwork.
- Her part-time employer might not offer benefits like health insurance.
- She could be unaware of local nonprofit case management services."""
VARIANTS["important_things_to_notice_down"] = BASELINE.replace(ORIGINAL_NUANCES, SPECULATIVE_LIST)

# 3. Responsiveness/Relevance down: insert an unrelated clinical tangent that
# doesn't answer what was actually asked (disability benefits + housing).
CLINICAL_TANGENT = (
    "Separately, it's worth considering whether she should be screened for depression or "
    "anxiety, since chronic physical conditions are often comorbid with mood disorders in the "
    "clinical literature. A PHQ-9 or GAD-7 screening tool could help quantify symptom severity, "
    "and if she scores above clinical thresholds, a referral to a licensed therapist for "
    "cognitive behavioral therapy may be appropriate, potentially in combination with a "
    "psychiatric medication evaluation. Sleep hygiene and stress-reduction techniques such as "
    "mindfulness-based stress reduction (MBSR) are also commonly recommended in this population.\n\n"
    "A physical condition that limits standing, lifting, or physically demanding work can qualify"
)
VARIANTS["responsiveness_relevance_down"] = BASELINE.replace(
    "A physical condition that limits standing, lifting, or physically demanding work can qualify",
    CLINICAL_TANGENT,
)

# 4. Peer-Role Alignment down: add unsolicited scripts / how-to-do-peer-support
# coaching that the provider did not ask for.
COACHING_INSERT = (
    'When you sit down with her, here is exactly how to approach the conversation: start by '
    'saying "I hear you, and I want you to know your feelings are completely valid." Then make '
    'sure to use active listening techniques: nod, maintain eye contact, and reflect her '
    'words back to her before moving into problem-solving. You might say, "It sounds like '
    'you are feeling uncertain about whether you can make ends meet, and that is a really hard '
    'place to be." Only after she feels fully heard should you introduce any of the following '
    'information, and make sure to check in frequently by asking "How does that feel to hear?" '
    'after each new piece of information.\n\n'
    'A benefits planner can be especially valuable here'
)
VARIANTS["peer_role_alignment_down"] = BASELINE.replace(
    "A benefits planner can be especially valuable here",
    COACHING_INSERT,
)

# 5. Autonomy down: replace her stated goal (keep working, don't want to stop)
# with the AI imposing "stability" / "treatment adherence" as the goal.
GOAL_OVERRIDE = (
    "Given her situation, the most important priority should really be establishing "
    "long-term stability. She should strongly consider whether continuing to work "
    "right now is really the wisest choice, or whether she would be better served by focusing "
    "on stabilizing her health first. Adhering consistently to any treatment or medical "
    "recommendations she receives will matter a great deal for her long-term outcomes, even if "
    "that means scaling back work in the short term. It may help to know:"
)
VARIANTS["service_user_goals_autonomy_down"] = BASELINE.replace(
    "Because she wants to continue working, it may help to know:",
    GOAL_OVERRIDE,
)

# 6. Reliability/Verifiability down: replace hedged/verifiable-sounding claims
# with confident, plausible-sounding invented statistics.
v6 = BASELINE.replace(
    "  - I could not verify specific housing program openings today, but they appear active and local.",
    "  - As of this month, NJCDC has 14 open units in its affordable housing pipeline and the average wait time for applicants in her income bracket is 3.2 months.",
)
v6 = v6.replace(
    "  - Current as of today based on SSA national contact info.",
    "  - SSI applications from Passaic County currently average a 41-day processing time and a 68% initial approval rate for physical-limitation claims.",
)
VARIANTS["reliability_verifiability_down"] = v6

# 7. Ease of Extraction down: same content, but with headers/bullets removed
# and the useful information buried in dense, unbroken paragraphs.
def _flatten(text: str) -> str:
    lines = [l.strip("- ").strip() for l in text.split("\n") if l.strip()]
    return " ".join(lines)

VARIANTS["ease_of_extracting_assistance_down"] = (
    "There's a lot to unpack here, and it's worth thinking broadly about her overall "
    "circumstances before getting into any one specific program, since these things tend "
    "to be interconnected in ways that aren't always obvious at first glance, and it can "
    "take some time to fully appreciate how each piece fits together with the others. "
    + _flatten(BASELINE)
)


def main():
    jobs = OrderedDict()
    jobs["BASELINE"] = BASELINE
    jobs.update(VARIANTS)

    results = OrderedDict()
    lock = threading.Lock()
    out_path = os.path.join(os.path.dirname(__file__), "output", "sensitivity_results.json")

    def _run(name):
        return name, _call(build_prompt({"scenario": SCENARIO, "response": jobs[name]}))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_run, name): name for name in jobs}
        for i, future in enumerate(as_completed(futures), start=1):
            name, result = future.result()
            with lock:
                results[name] = result
                # preserve intended order in the file even though completion order varies
                ordered = OrderedDict((k, results[k]) for k in jobs if k in results)
                with open(out_path, "w") as f:
                    json.dump(ordered, f, indent=2)
            print(f"[sensitivity] ({i}/{len(jobs)}) {name} done")

    results = OrderedDict((k, results[k]) for k in jobs)

    print("\n=== Scores: BASELINE vs each targeted-degradation variant ===")
    header = "variant".ljust(34) + "".join(d[:10].ljust(11) for d in DIMENSIONS)
    print(header)
    for name, r in results.items():
        row = name.ljust(34) + "".join(str(r[d]["score"]).ljust(11) for d in DIMENSIONS)
        print(row)


if __name__ == "__main__":
    main()
