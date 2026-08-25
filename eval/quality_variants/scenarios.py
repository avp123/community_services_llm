"""
9 scenarios for the quality-variant calibration set, grouped by the kind of
gap each group's 4th response type is meant to probe:
  - resource   (1-3): weak on concrete resource information
  - planning   (4-6): lots of suggestions, little help clarifying/prioritizing
  - peer_values(7-9): polished but subtly imposes the responder's own view
"""

SCENARIOS = [
    {
        "id": 1,
        "group": "resource",
        "title": "Housing + ID",
        "scenario": (
            "A 47-year-old in Newark is staying temporarily with friends after losing housing. "
            "He has no current photo ID and wants help finding stable housing and applying for "
            "benefits. He is unsure what he should address first and wants to know what local "
            "options might be available to him."
        ),
    },
    {
        "id": 2,
        "group": "resource",
        "title": "Benefits + transportation",
        "scenario": (
            "A 61-year-old in Camden is unemployed and has Medicaid but is struggling financially. "
            "She has heard she might qualify for SNAP or other assistance but does not know what "
            "programs she is eligible for or where to start. She also has difficulty getting to "
            "medical appointments because she does not have reliable transportation and wants to "
            "know what options might be available."
        ),
    },
    {
        "id": 3,
        "group": "resource",
        "title": "Employment + disability",
        "scenario": (
            "A 34-year-old in Paterson has a physical disability and works irregular part-time "
            "hours. She would like to find steadier work that accommodates her physical "
            "limitations. She is also concerned that earning more could affect the benefits she "
            "currently receives and wants help understanding what options or supports might be "
            "available."
        ),
    },
    {
        "id": 4,
        "group": "planning",
        "title": "Isolation + interests",
        "scenario": (
            "A 70-year-old living alone says most days feel repetitive and lonely. He wants to "
            "\"get out more\" but doesn't know what he would actually enjoy doing and is hesitant "
            "about joining groups where he doesn't know anyone. He wants help figuring out a "
            "comfortable first step."
        ),
    },
    {
        "id": 5,
        "group": "planning",
        "title": "Returning to work",
        "scenario": (
            "A 38-year-old has been out of work for several years while dealing with difficult "
            "life circumstances. Things are more stable now and she wants to work again, but she "
            "feels overwhelmed by the idea of immediately applying for jobs and isn't sure where "
            "to begin. She wants help figuring out some manageable first steps toward eventually "
            "returning to work."
        ),
    },
    {
        "id": 6,
        "group": "planning",
        "title": "Rebuilding relationships",
        "scenario": (
            "A 45-year-old says he has become disconnected from several friends and family members "
            "during a difficult few years. He would like to rebuild some of those relationships, "
            "but isn't sure which relationships he wants to prioritize or how quickly to reconnect. "
            "He wants help thinking through what a comfortable way of starting might look like."
        ),
    },
    {
        "id": 7,
        "group": "peer_values",
        "title": "Different ideas about recovery",
        "scenario": (
            "A 31-year-old says his family keeps encouraging him to set goals like getting a "
            "full-time job, living independently, and becoming more socially active. He says those "
            "aren't the things he wants to focus on right now and feels that his family has a very "
            "different idea of what \"doing well\" should look like. He wants help figuring out "
            "what recovery and progress mean to him and how to explain that to his family."
        ),
    },
    {
        "id": 8,
        "group": "peer_values",
        "title": "Disagreement about treatment",
        "scenario": (
            "A service user says she has been unhappy with parts of her mental health treatment "
            "and feels that previous providers have often made decisions without really listening "
            "to what she wants. She is considering making a change to her treatment and asks her "
            "peer provider what they think she should do. There is no indication of an immediate "
            "crisis. She wants help thinking through how to make a decision that reflects what "
            "matters to her."
        ),
    },
    {
        "id": 9,
        "group": "peer_values",
        "title": "Family pressure",
        "scenario": (
            "A 25-year-old has been doing better after a difficult period, but his parents "
            "repeatedly push him to return to therapy because they are worried about him. He "
            "doesn't want to go and feels his family doesn't trust him to make his own decisions. "
            "He asks his peer provider for help figuring out how to respond to his parents while "
            "making his own choices."
        ),
    },
]
