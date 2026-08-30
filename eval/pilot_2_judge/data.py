"""
Pilot 2 conversations for 2026-08-28, filtered from eval/pilot_2_messages.csv.

Tool order for this session was reported as BAAB. Tool identity is not persisted
anywhere in the DB (construct_response's `version` argument is used to route the
request and then discarded — see backend/app/all_endpoints.py / submodules.py),
so this mapping is inferred from (a) chronological order + the stated BAAB
sequence and (b) is corroborated by response style: e1de23bc and 18d230ba use
generic headers/scripts/safety-note style (consistent with Version B / vanilla
GPT + search), while f1797c3d and 499d14d9 use the warm, non-directive,
peer-framing style (consistent with Version A / PeerCoPilot).

3917609a378aae5b2c8cbe9284127a0e is excluded: identical vignette to
18d230ba6418d51ce4a88c5efcb45679, submitted ~5 minutes earlier in the same
session — treated as an accidental duplicate/retry, not a fourth distinct unit.
"""

CONVERSATIONS = [
    {
        "conversation_id": "e1de23bc95fe763b2ea057c77931fef0",
        "order_index": 1,
        "tool": "B",
        "created_at": "2026-08-28 19:16:22.898735",
        "scenario": (
            "A 34-year-old woman in Paterson has a physical disability and works "
            "irregular part-time hours. She would like to find steadier work that "
            "accommodates her physical limitations. She is also concerned that "
            "earning more could affect the benefits she currently receives."
        ),
        "response": (
            "Here are the best next steps in/near Paterson to (1) find steadier "
            "disability-friendly work and (2) understand how increased earnings "
            "could affect benefits.\n\n"
            "## 1) Get job help + accommodations through Vocational Rehabilitation (DVRS)\n"
            "New Jersey Division of Vocational Rehabilitation Services (DVRS) - Passaic "
            "County (Paterson)\n"
            "- Address: 200 Memorial Dr, 1st Floor, Paterson, NJ 07505\n"
            "- Phone: 973-742-9226\n"
            "DVRS can help with career counseling, job placement, training, assistive "
            "technology, and workplace accommodations. Tell them you need steadier hours "
            "and work within specific physical limitations (lifting/standing/sitting "
            "tolerance, breaks, schedule flexibility, remote/hybrid).\n\n"
            "## 2) Get benefits counseling before you change hours/pay\n"
            "Because the impact is different depending on whether she receives SSI, "
            "SSDI, Medicaid/NJ FamilyCare, SNAP, housing assistance, etc., she should "
            "talk to a certified work-incentives counselor.\n\n"
            "SSA Ticket to Work Help Line (to connect to a WIPA benefits counselor in NJ)\n"
            "- Phone: 1-866-968-7842\n"
            "- TTY: 1-866-833-2967\n"
            "Ask for a referral to WIPA (Work Incentives Planning and Assistance) and "
            "request a written summary of how earnings would affect cash benefits and "
            "health coverage.\n\n"
            "### Important NJ-specific protection for health insurance while working\n"
            "NJ WorkAbility (Medicaid buy-in)\n"
            "- Official info: https://www.nj.gov/humanservices/dds/programs/njworkability/\n"
            "- Key point (as of Feb 1, 2024): NJ WorkAbility no longer has income limits "
            "(premiums may apply). This can be a major safety net if she's worried about "
            "losing Medicaid/NJ FamilyCare when earnings go up.\n\n"
            "## 3) Use disability-friendly job matching supports (statewide options)\n"
            "The Arc of New Jersey - Project HIRE (supported employment)\n"
            "- Program info: https://www.arcnj.org/programs/project-hire/project_hire.html\n"
            "They provide vocational assessment, job matching, on-site job coaching, and "
            "follow-along supports (often helpful for finding stable roles that fit "
            "limitations).\n\n"
            "## 4) Transportation backup (if commuting is a barrier)\n"
            "NJ TRANSIT Access Link (ADA paratransit)\n"
            "- Info: https://www.njtransit.com/accessibility/access-link-ada-paratransit\n"
            "- Certification phone: 973-491-4224 (select option #1 for Certification)\n"
            "If consistent transportation is part of getting steadier work, applying for "
            "Access Link can help.\n\n"
            "## What I need to tailor this (so you don't risk benefits)\n"
            "If you tell me:\n"
            "1) What benefits she gets (SSI or SSDI? Medicaid/NJ FamilyCare? SNAP? "
            "Section 8/public housing?)\n"
            "2) Rough monthly earnings now and desired hours/wage\n"
            "3) Main physical limitations (standing, lifting, sitting, use of hands, "
            "need for breaks, etc.)\n"
            "...I can suggest the best work paths (including remote/hybrid options) and "
            "the right benefits counseling questions to ask so she can increase income "
            "as safely as possible."
        ),
    },
    {
        "conversation_id": "f1797c3de1eb030be95317f836c31170",
        "order_index": 2,
        "tool": "A",
        "created_at": "2026-08-28 19:29:42.734111",
        "scenario": (
            "A 31-year-old man says his family keeps encouraging him to set goals like "
            "getting a full-time job, living independently, and becoming more socially "
            "active. He says those aren't the things he wants to focus on right now and "
            "feels that his family has a very different idea of what \u201cdoing well\u201d "
            "should look like. Recently retail job tried... no job at the moment. Have "
            "several friends but not in the town. Less social connection. Painting is "
            "his hobby."
        ),
        "response": (
            "It makes a lot of sense that he's feeling rubbed raw by this. When the "
            "people closest to you keep defining \u201cdoing well\u201d in a way that "
            "doesn't match where you're at, it can start to feel like you're being "
            "measured instead of understood.\n\n"
            "On the peer side, I'd stay really anchored in his version of a good life "
            "and help him put words to it. Not \u201cwhy don't you want those things,\u201d "
            "but \u201cwhat feels most important to you right now\u201d and \u201cwhat "
            "would a better next month look like for you.\u201d Sometimes folks aren't "
            "rejecting work/independence/socializing forever\u2014they're rejecting the "
            "pressure, the timeline, or the idea that those are the only markers that "
            "count.\n\n"
            "You've got a few strengths to build from without forcing the family's "
            "agenda: he took a shot at a retail job (that's effort and learning, even if "
            "it didn't stick), he has friends (even if they're not local), and painting "
            "already gives him meaning and routine. If \u201csocial connection\u201d is a "
            "value but the local piece is hard, you can lean into what's already "
            "real\u2014staying connected with those friends more intentionally, or "
            "finding one low-pressure, art-adjacent way to be around people (not \u201cbe "
            "more social,\u201d but \u201cbe around humans while doing something that "
            "matters to you\u201d).\n\n"
            "With the family piece, it can help to frame it as a values gap, not a "
            "motivation problem: \u201cThey're trying to help, but their picture of "
            "success isn't the same as yours.\u201d If he wants, you can support him in "
            "identifying one or two \u201cbridge goals\u201d that are true to him and "
            "legible to family\u2014small, concrete steps that don't betray his "
            "priorities (like a gentle routine, a short volunteer/art commitment, "
            "exploring a different kind of work than retail, or a plan to build local "
            "connection slowly).\n\n"
            "Mostly: you're helping him claim that his goals count, and that \u201cdoing "
            "well\u201d can include stability, meaning, and choice\u2014not just the usual "
            "adult milestones."
        ),
    },
    {
        "conversation_id": "499d14d9742f82e7af186d45ce4478a7",
        "order_index": 3,
        "tool": "A",
        "created_at": "2026-08-28 19:41:37.007972",
        "scenario": (
            "A 61-year-old woman in Camden is unemployed and has Medicaid but is "
            "struggling financially. She has heard she might qualify for SNAP or other "
            "assistance but does not know what programs she is eligible for or where to "
            "start. She also has difficulty getting to medical appointments because she "
            "does not have reliable transportation. Financial constraints is the biggest "
            "concern. Curious of Medicaid transportation options. She needs to see PCP "
            "for Medical routine check up."
        ),
        "response": (
            "It makes total sense she feels stuck here \u2014 when money is tight, even "
            "\u201cbasic\u201d stuff like getting to a routine PCP visit can turn into a "
            "whole barrier course. The good news is: having NJ FamilyCare (Medicaid) "
            "usually opens doors to both food help and rides to appointments.\n\n"
            "Based on what you shared (61, unemployed, on Medicaid), she's very likely "
            "to qualify for SNAP (food assistance), especially if income is low or $0 "
            "right now.\n\n"
            "For Medicaid transportation: NJ FamilyCare includes non-emergency medical "
            "transportation (often called NEMT) for covered appointments like a PCP "
            "checkup when someone doesn't have a reliable way to get there. The most "
            "practical \u201cwhere to start\u201d is usually to have her call the Member "
            "Services number on the back of her NJ FamilyCare/health plan card and ask "
            "specifically for \u201cnon-emergency medical transportation to my PCP.\u201d "
            "They'll tell her what they need (appointment info, pickup location, etc.) "
            "and how far ahead to schedule.\n\n"
            "If she needs a simple on-ramp for benefits (SNAP and more) without having "
            "to figure it all out alone, 2-1-1 is often the easiest first step in NJ: "
            "dial 211 (or visit nj211.org) and ask for \u201cSNAP application help in "
            "Camden\u201d and \u201cbenefits screening.\u201d\n\n"
            "A nearby local place that may be able to help with broader "
            "financial/benefits navigation in Camden is Camden County Council on "
            "Economic Opportunity (CCCOEO), 538 Broadway, Camden, NJ 08103, phone "
            "856-964-6887.\n\n"
            "If you want, tell me whether she has a managed care plan name on her "
            "Medicaid card (like Aetna, Amerigroup/Wellpoint, Horizon, UnitedHealthcare, "
            "etc.) and I can help narrow down the exact transportation contact path for "
            "that plan."
        ),
    },
    {
        "conversation_id": "18d230ba6418d51ce4a88c5efcb45679",
        "order_index": 4,
        "tool": "B",
        "created_at": "2026-08-28 19:49:00.358976",
        "scenario": (
            "A 25-year-old man has been doing better after a difficult period, but his "
            "parents repeatedly push him to return to therapy because they are worried "
            "about him. He doesn't want to go and feels his family doesn't trust him to "
            "make his own decisions."
        ),
        "response": (
            "He's an adult, so the core issues here are autonomy (his right to decide "
            "about treatment), family anxiety, and trust/communication. A good way to "
            "handle this is to validate their concern while setting a clear boundary and "
            "offering a concrete alternative that addresses safety.\n\n"
            "### What he can say (script)\n"
            "- Validate + assert autonomy: \u201cI know you're worried because the last "
            "period was scary. I'm doing better now, and I need you to respect that I "
            "decide whether I go to therapy.\u201d\n"
            "- Name the impact: \u201cWhen you keep pushing, it makes me feel like you "
            "don't trust me and it actually stresses me out.\u201d\n"
            "- Set a boundary + consequence: \u201cI'm not going back to therapy right "
            "now. If the topic comes up repeatedly, I'm going to end the "
            "conversation/leave the room.\u201d\n"
            "- Offer a reassurance plan (so it's not just \u2018no\u2019): \u201cWhat I "
            "can do is keep an eye on my mental health and tell you if things "
            "change.\u201d\n\n"
            "### A compromise that protects his independence\n"
            "If he's open to something less than \u201creturn to therapy\u201d:\n"
            "- A single check-in session (one appointment to assess how he's doing, not "
            "an open-ended commitment).\n"
            "- Coaching/skills group, periodic self-checks, or using a primary care "
            "doctor for mental health screening.\n"
            "- Agree on early warning signs (sleep changes, isolation, missing "
            "work/school, substance use increase, suicidal thoughts) and what action "
            "he'll take if they appear.\n\n"
            "Example:\n"
            "\u201cI'm not committing to weekly therapy. But if I start sleeping <5 "
            "hours for several nights, miss work, or feel unsafe, I will book an "
            "appointment within a week and tell you.\u201d\n\n"
            "### If parents won't drop it\n"
            "- Repeat calmly (broken-record technique): \u201cI hear you. My decision is "
            "no.\u201d\n"
            "- Reduce reassurance-seeking loops: avoid debating reasons endlessly\u2014"
            "debates invite more pressure.\n"
            "- Consider one joint family session (with a therapist) only to work on "
            "boundaries/communication, not to \u201ctreat him\u201d if he doesn't want "
            "that.\n\n"
            "### Safety note\n"
            "If there's any concern about self-harm, suicidal thoughts, inability to "
            "function, psychosis, or heavy substance use, then getting professional help "
            "promptly matters more than the autonomy discussion.\n\n"
            "If you tell me what the \u201cdifficult period\u201d involved (depression, "
            "panic, substance use, hospitalization, etc.), I can tailor a boundary + "
            "reassurance plan that fits the specific risks."
        ),
    },
]

EXCLUDED = {
    "3917609a378aae5b2c8cbe9284127a0e": (
        "Duplicate of 18d230ba6418d51ce4a88c5efcb45679 (identical vignette, ~5 min "
        "earlier in the same session) - treated as accidental retry, not a fourth unit."
    )
}
