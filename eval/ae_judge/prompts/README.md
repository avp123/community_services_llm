# Prompts

Copies of the system prompts used in this evaluation. **Source of truth is
`debugging/data/`** — these are copies for convenience, and `versions.py` still reads
from there. The sha256 prefixes below are of the source files at copy time; if a copy
and its source diverge, the source wins.


The treatment is also inlined in `backend/app/submodules.py::get_default_peer_copilot_system_prompt`, verified byte-identical.


| file | source | sha256 | what it is |
|---|---|---|---|
| `treatment.md` | `debugging/data/version_f3.md` | `96d31691dd91` | Treatment. Frozen 2026-09-06 as production Version A. |
| `baseline.md` | `debugging/data/version_b.md` | `1d702d3cb723` | Control. Vanilla assistant prompt. |
| `variant_direction_options.md` | `debugging/data/version_f3_v1_options.md` | `571e750fd693` | Axis DIRECTION inverted: unordered options, no recommendation. |
| `variant_locality_generic.md` | `debugging/data/version_f3_v2_generic.md` | `095cba826323` | Axis LOCALITY inverted: generic categories, no named agencies or numbers. |
| `variant_role_supportive.md` | `debugging/data/version_f3_v3_supportive.md` | `448f8b36a3ad` | Axis ROLE inverted: no administrative logistics. Resource section held identical to treatment. |
| `variant_language_techniques.md` | `debugging/data/version_f3_v4_techniques.md` | `1c7350b82148` | Axis LANGUAGE inverted: named techniques instead of borrowable sentences. |
| `legacy_production_version_a.md` | `debugging/data/version_a_legacy.md` | `473f06968b81` | The production prompt before 2026-09-06. Kept so older eval results stay interpretable. |

## Axis scenarios

The four new scenarios written for the axis contrast pairs:

| file | source |
|---|---|
| `scenario_axis_direction.md` | `debugging/data/axis_direction.md` |
| `scenario_axis_locality.md` | `debugging/data/axis_locality.md` |
| `scenario_axis_role.md` | `debugging/data/axis_role.md` |
| `scenario_axis_language.md` | `debugging/data/axis_language.md` |

## Axis design

Each variant is the treatment with exactly ONE section replaced; every other line is
byte-identical, so any difference in the generated responses is attributable to that
axis alone.


| axis | treatment (arm A) | variant (arm B) |
|---|---|---|
| direction | ordered recommendation | unordered options |
| locality | named NJ agencies + numbers | generic categories |
| role | practical logistics | purely supportive |
| language | borrowable sentences | named techniques |
