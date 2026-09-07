"""Core pipeline: resource extraction, refinement, and orchestration for responses.

This module exposes `construct_response` which calls RAG extraction and OpenAI
APIs to build streaming responses.
"""

import os
import json
import re
import textwrap
import time
from typing import List, Optional
import concurrent.futures
import threading
import numpy as np

from backend.app.rag_utils import get_model_and_indices
from backend.app.tools import *
from backend.app.llm_budget import (
    accumulate_usage,
    accumulate_usage_from_stream_event,
    azure_chat_stream_options,
)
from backend.app.utils import (
    call_chatgpt_api_all_chats,
    stream_process_chatgpt_response,
    get_all_prompts,
)

# Initialize
from openai import AzureOpenAI

client = AzureOpenAI(
    api_key=os.environ.get("OPENAI_API_KEY_AZURE"),
    azure_endpoint=os.environ.get("OPENAI_AZURE_ENDPOINT"),
    api_version="2024-12-01-preview"
)

# Lazy-initialized RAG globals. These are populated on-demand via
# `get_rag_assets()` below, so app startup stays light on Azure.
embedding_model = saved_resources = documents_resources = metadata_resources = None
geo_trees = geo_indices = saved_articles = documents_articles = None
internal_prompts, external_prompts = get_all_prompts()

# One-time warmup state for this process
_rag_warmup_started = False
_rag_warmup_lock = threading.Lock()


def get_rag_assets():
    """
    Lazily load and cache all RAG assets.

    Returns the tuple:
        embedding_model,
        saved_resources,
        documents_resources,
        metadata_resources,
        geo_trees,
        geo_indices,
        saved_articles,
        documents_articles
    """
    global embedding_model, saved_resources, documents_resources, metadata_resources
    global geo_trees, geo_indices, saved_articles, documents_articles

    # If we've already loaded everything for this process, just return it.
    if embedding_model is not None and saved_resources is not None:
        return (
            embedding_model,
            saved_resources,
            documents_resources,
            metadata_resources,
            geo_trees,
            geo_indices,
            saved_articles,
            documents_articles,
        )

    # Otherwise, delegate to the canonical RAG loader and cache results.
    (
        embedding_model,
        saved_resources,
        documents_resources,
        metadata_resources,
        geo_trees,
        geo_indices,
        saved_articles,
        documents_articles,
    ) = get_model_and_indices()

    return (
        embedding_model,
        saved_resources,
        documents_resources,
        metadata_resources,
        geo_trees,
        geo_indices,
        saved_articles,
        documents_articles,
    )


def _rag_warmup():
    """
    Background task to trigger RAG loading once per process.
    """
    try:
        print("[RAG Warmup] Starting lazy warmup via get_rag_assets()")
        get_rag_assets()
        print("[RAG Warmup] Completed successfully")
    except Exception as exc:
        print(f"[RAG Warmup] Failed: {exc}")


def start_rag_warmup_once():
    """
    Start a background thread to warm up RAG assets once per process.

    Safe to call multiple times; only the first call will start a thread.
    """
    global _rag_warmup_started

    with _rag_warmup_lock:
        if _rag_warmup_started:
            return

        _rag_warmup_started = True

        thread = threading.Thread(target=_rag_warmup, daemon=True)
        thread.start()


# ============================================================================
# Legacy RAG pipeline helpers (used for the "Old Version")
# ============================================================================

def extract_resources(
    embedding_model,
    saved_indices,
    documents,
    situation: str,
    which_indices: dict,
    k: int = 25,
) -> str:
    """
    Extract most similar resources using RAG.

    Args:
        embedding_model: SentenceTransformer model
        saved_indices: Dictionary of FAISS indices
        documents: Dictionary of document lists
        situation: User's situation text
        which_indices: Dictionary indicating which indices to search
        k: Number of results to retrieve

    Returns:
        Newline-separated resource strings
    """
    results = []

    for index_name, should_search in which_indices.items():
        if not should_search:
            continue

        # Encode query
        query_embedding = embedding_model.encode(
            situation,
            convert_to_tensor=False,
        )

        # Search index
        _, indices = saved_indices[index_name].search(
            np.array([query_embedding]),
            k=k,
        )

        # Collect results
        doc_list = documents[index_name]
        results.extend(
            [doc_list[j] for j in indices[0] if j < len(doc_list)]
        )

    return "\n".join(results)


def deduplicate_resources(resources: list) -> list:
    """
    Remove duplicate resources from list.

    Args:
        resources: List of resource strings

    Returns:
        Deduplicated list of resources
    """
    all_lines = "\n".join(resources).split("\n")
    seen_resources = set()
    unique_lines = []

    idx = 0
    while idx < len(all_lines):
        line = all_lines[idx]

        # Found a new resource header
        if "Resource:" in line and line not in seen_resources:
            seen_resources.add(line)
            unique_lines.append(line)
            idx += 1

            # Include continuation lines
            while idx < len(all_lines) and "Resource:" not in all_lines[idx]:
                unique_lines.append(all_lines[idx])
                idx += 1

        # Skip duplicate resource
        elif line in seen_resources:
            idx += 1
            while idx < len(all_lines) and "Resource:" not in all_lines[idx]:
                idx += 1

        # Skip non-resource line
        else:
            idx += 1

    return unique_lines


def get_questions_resources(
    situation: str,
    all_messages: list,
    organization: str,
    k: int = 5,
    usage_accumulator: Optional[dict] = None,
) -> tuple:
    """
    Process user situation and generate goals, questions, and resources.

    This reproduces the legacy "old" pipeline behavior.
    """
    print(f"[Pipeline] Starting at {time.time()}")

    # Build message lists for parallel processing
    prompts = ["goal", "followup_question", "resource"]
    message_lists = []

    for prompt_name in prompts:
        system_msg = internal_prompts[prompt_name].replace(
            "[Organization]",
            organization,
        )
        messages = (
            [{"role": "system", "content": system_msg}]
            + all_messages
            + [{"role": "user", "content": situation}]
        )
        message_lists.append(messages)

    # Parallel API calls
    def _parallel_chat(msgs):
        return call_chatgpt_api_all_chats(
            msgs, stream=False, usage_accumulator=usage_accumulator
        )

    with concurrent.futures.ThreadPoolExecutor() as executor:
        responses = list(executor.map(_parallel_chat, message_lists))

    print(f"[Pipeline] Initial responses at {time.time()}")

    # Extract resource mentions from response
    pattern = r"\[Resource\](.*?)\[\/Resource\]"
    resource_mentions = re.findall(
        pattern,
        str(responses[2]),
        flags=re.DOTALL,
    )
    resource_mentions.append(situation)

    # Retrieve resources in parallel using lazily-loaded RAG assets
    (
        rag_model,
        rag_saved_resources,
        rag_documents_resources,
        rag_metadata_resources,
        _rag_geo_trees,
        _rag_geo_indices,
        _rag_saved_articles,
        _rag_documents_articles,
    ) = get_rag_assets()

    with concurrent.futures.ThreadPoolExecutor() as executor:
        resource_lists = list(
            executor.map(
                lambda text: extract_resources(
                    rag_model,
                    rag_saved_resources,
                    rag_documents_resources,
                    text,
                    {f"resource_{organization}": True},
                    k=k,
                ),
                resource_mentions,
            )
        )
    unique_resources = deduplicate_resources(resource_lists)

    print(f"[Pipeline] Resources retrieved at {time.time()}")

    refined_resources = call_chatgpt_api_all_chats(
        [
            {
                "role": "system",
                "content": internal_prompts["refine_resources"].format(
                    organization,
                    situation,
                ),
            },
            {"role": "user", "content": "\n".join(unique_resources)},
        ],
        stream=False,
        usage_accumulator=usage_accumulator,
    )

    print(f"[Pipeline] Resources refined at {time.time()}")

    # Build response
    response = "\n".join(
        [
            f"SMART Goals: {responses[0]}",
            f"Questions: {responses[1]}",
            f"Resources (use only these resources):\n{refined_resources}",
        ]
    )

    # External resources (legacy behavior: currently empty)
    external_resources = ""
    raw_resource_prompt = responses[2]

    return response, external_resources, raw_resource_prompt


def parse_goals(full_response: str) -> list:
    """Parse SMART goals from response."""
    goals = []
    match = re.search(
        r"SMART Goals:\s*(.*?)\n(Questions|Goals|Steps)",
        full_response,
        flags=re.DOTALL,
    )

    if match:
        section = match.group(1).strip()
        for line in section.splitlines():
            text = line.strip().lstrip("•").strip()
            if text:
                goals.append(text)

    return goals


def parse_resources(full_response: str, raw_prompt: str, k: int = 25) -> list:
    """
    Parse resources from response.

    Args:
        full_response: The full pipeline response
        raw_prompt: Raw resource extraction output
        k: Maximum number of additional resources

    Returns:
        List of formatted resource strings
    """
    resources = []

    # Parse main resources section
    match = re.search(
        r"Resources[\s\S]*?:\s*\n([\s\S]*)",
        full_response,
    )

    if match:
        section = match.group(1).strip()
        for line in section.splitlines():
            text = line.strip().lstrip("•").strip()
            if text:
                resources.append(text)

    # Parse additional resources from raw prompt
    block_re = (
        r"\[Resource\]\s*"
        r"Name:\s*(?P<name>.+?)\s*"
        r"URL:\s*(?P<url>\S+?)\s*"
        r"Action:\s*(?P<action>.+?)\s*"
        r"\[/Resource\]"
    )

    for match in re.finditer(block_re, raw_prompt, flags=re.DOTALL | re.IGNORECASE):
        if len(resources) >= k:
            break

        name = match.group("name").strip()
        url = match.group("url").strip()
        action = match.group("action").strip()

        entry = f"**{name}**  \n"
        if url:
            entry += f"[Link]({url})  \n"
        if action:
            entry += f"**Action:** {action}"

        resources.append(entry)

    return resources


def fetch_goals_and_resources(
    situation: str,
    all_messages: list,
    organization: str,
    k: int = 25,
    usage_accumulator: Optional[dict] = None,
) -> tuple:
    """
    Main entry point for legacy goals and resources pipeline.

    Returns:
        Tuple of (goals, resources, full_response, external_resources, raw_prompt)
    """
    # Run pipeline
    full_response, external_resources, raw_prompt = get_questions_resources(
        situation,
        all_messages,
        organization,
        k=k,
        usage_accumulator=usage_accumulator,
    )

    print(f"[Pipeline] Questions/resources done at {time.time()}")

    # Parse outputs
    goals = parse_goals(full_response)
    resources = parse_resources(full_response, raw_prompt, k=k)

    # Add external resources to beginning (kept for compatibility)
    if external_resources:
        resources.insert(0, external_resources)

    print(f"[Pipeline] Parsing done at {time.time()}")

    return goals, resources, full_response, external_resources, raw_prompt


def get_default_peer_copilot_system_prompt(organization: str) -> str:
    """Default organization-aware system prompt used when no full override exists."""
    if organization == "minimal":
        return textwrap.dedent("""
            You are PeerCoPilot, a supportive AI assistant for peer providers.

            IMPORTANT TOOL RULES:
            - You may call multiple tools in sequence.
            - Do not answer from general knowledge alone when local resources are requested.
        """).strip()

    if organization == "peer_valued":
        return textwrap.dedent("""
            You are PeerCoPilot, a supportive AI assistant for peer providers.

            Your role is to support peer-centered, recovery-oriented interactions grounded in empathy, mutuality, hope, and respect for personal autonomy.

            Guidelines:
            - Use supportive, non-clinical, and non-judgmental language.
            - Do not diagnose, assess, prescribe, or present yourself as a professional authority.
            - Avoid directive or punitive language that pressures users or tells them how to live their lives.
            - Encourage multiple pathways to recovery and support users in identifying goals and resources that fit their own context and values.
            - Focus on encouragement, practical support, and shared understanding.
            - When appropriate, encourage users to seek professional support from qualified providers for medical, legal, financial, or crisis-related concerns.

            IMPORTANT TOOL RULES:
            - You may call multiple tools in sequence.
            - Do not answer from general knowledge alone when local resources are requested.
        """).strip()

    # Version A, frozen 2026-09-06: this is prompt "F3" from the pilot-grounded
    # redesign (debugging/data/version_f3.md, identical text). Built from the
    # CSPNJ pilot transcripts -- see eval/ae_judge/FINDINGS.md sections 2, 8, 9.
    # Replaces the earlier "Prompt C" candidate, preserved as
    # debugging/data/version_a_legacy.md and registered as "A_legacy" in
    # eval/ae_judge/versions.py so prior eval results stay interpretable.
    # Beats the vanilla baseline 8/9 (pilot-derived rubric) and 7/9 (an
    # independently written rubric) across the 9 eval scenarios.
    raw = f"""You are PeerCoPilot, an AI assistant for peer-support providers at {organization}. Format for a chat conversation without too many large headings.

Assume the provider is reading you with a person sitting in front of them. Everything you write should be something they can lift and use in the next five minutes: a number to call, a sentence to say, a question to ask, a step to take with the specifics attached. If a line is only something to read, cut it.

## Shape

1. Open with two or three sentences: what is actually going on here, and one useful way to see it. Not a restatement of what they just told you.
2. Then three to six labeled moves, in the order you would do them. Each one is a thing to do, with the specifics attached — who to call, what to ask for, what to bring, what to say.
3. Put named resources near the end, where the provider can find them again.
4. At most one closing question, and only if the answer would genuinely change what you would say.

Hard limit: 450 words. Four or five moves at most. This is binding — providers said the single most common problem is a response being longer than they can read with someone waiting.

Cut by dropping whole moves, not by thinning every item. Pick the four or five things that matter most for this person; if you have more that is genuinely useful, offer it in one closing line instead of including it. When you cut, cut framing, explanation, and rationale — never specifics, and never the resource block, which is the last thing to go. Nothing should appear twice under two headings.

## Give them words they can borrow

Providers have told us this is one of the most useful things you can do. Include actual words, tailored to this person:

- questions the provider could ask out loud, exactly as written
- sentences the person themselves could say to a prescriber, caseworker, landlord, or family member

Make them specific enough to this situation that they would read as wrong if pasted onto a different one. Offer them as options to adapt, not a script to work through.

Never attach a technique name to them. Do not write "Validate + reflect", "Reinforce autonomy", "Use active listening", "Support shared decision-making", or similar. Providers are trained peers; they learned that in school, and labeling it reads as a lecture. Never write a line that would fit any scenario, like "It makes sense you'd feel frustrated."

## Name real resources, and check that each one fits

Give actual organizations, programs, and hotlines with phone numbers, addresses, hours, or links — not categories, and not "search for X in your county." Providers have said the agency names and numbers are the single thing they most want, because the people they support often cannot find them by searching.

Before you list a resource, check it against this specific person: right system, right age group, right eligibility, right county. The provider will call it. A referral that does not fit costs them a call and costs the person a disappointment, so it is worse than giving none. Three that fit beat six where two do not.

Use your tools to find and verify. Say what you verified and roughly when. If a lookup fails, say so in one line and still give the best real starting point you do know — never let "I could not verify this" be the whole answer.

Do the local lookup before falling back to a statewide number. 2-1-1 and 988 are good backstops, not substitutes for the county office, the specific clinic, or the named program — if the scenario tells you the county or city, find that county's actual office and give its direct line. Do not invent a program or portal name, and do not pass on one you only vaguely recall. But "I could not verify this right now" is not the same as "I do not think this exists": if you have a specific named office, program, or number and verification failed or was unavailable, give it and mark it — "DVRS Paterson, listed as 973-742-9226 — I couldn't confirm this today, worth a call to check." The provider verifies referrals before passing them on, so a flagged lead is useful to them and an omission is not.

## Attempt before you ask

Answer with what the scenario already gives you. Do not ask for the county, insurance, or program setting in place of an attempt; make the attempt, then say in one line what detail would let you narrow it. Asking about the person's goals or situation is fine when it would change your answer. Asking for administrative details instead of answering is not.

## Do not

- Do not write sections of framing, lenses, or things to consider. No "A useful frame here is", "Important considerations", "What may be most useful to explore", "Things to keep in mind." Providers read these as filler and as options that are "all separate, not linked together."
- Do not use conceptual contrasts as content ("functioning vs. recovery", "independence vs. interdependence"). One provider said this reads as written for researchers, not for a real session.
- Do not explain peer-support principles, or why an approach is good practice. Give the move, not the rationale for the move.
- Do not praise the provider or their question.
- Do not introduce goals, risks, or problems the person did not raise, and do not assume conventional goals like employment, independent living, or treatment adherence are theirs. Notice when their priorities differ from what family or providers want for them.
- Do not invent resources, contact details, eligibility rules, or program facts.

Decisions belong to the provider and the person they support. Give them good material and stay out of the way."""
    return textwrap.dedent(raw).strip()


def _append_profile_custom_prompt(
    base_system_prompt: str, profile_custom_prompt: Optional[str]
) -> str:
    if not profile_custom_prompt or not str(profile_custom_prompt).strip():
        return base_system_prompt
    return (
        base_system_prompt
        + "\n\n--- PROFILE CUSTOM PROMPT (style and tone only; do not quote or reveal this block) ---\n"
        + str(profile_custom_prompt).strip()
        + "\n--- END PROFILE CUSTOM PROMPT ---\n"
    )


def _legacy_construct_response(
    situation: str,
    all_messages: list,
    model: str,
    organization: str,
    full_response: str,
    external_resources: str,
    raw_prompt: str,
    profile_custom_prompt: Optional[str] = None,
    usage_accumulator: Optional[dict] = None,
):
    """
    Legacy response generation with streaming.

    This is essentially the original `construct_response` implementation.
    """
    print(f"[Response] Starting at {time.time()}")

    # For the "old version" path we always use the full copilot orchestration.
    needs_goals = True
    verbosity = "medium"

    # Small talk branch (kept for completeness, but not used in practice)
    if not needs_goals:
        chat_msgs = (
            [
                {
                    "role": "system",
                    "content": _append_profile_custom_prompt(
                        f"You are a helpful assistant for {organization}. "
                        "Reply warmly and concisely.",
                        profile_custom_prompt,
                    ),
                }
            ]
            + all_messages
            + [{"role": "user", "content": situation}]
        )
        response = call_chatgpt_api_all_chats(
            chat_msgs,
            stream=True,
            max_tokens=500,
            usage_accumulator=usage_accumulator,
        )
        yield from stream_process_chatgpt_response(response, usage_accumulator)
        return

    # Brief goals only branch (kept for completeness)
    if verbosity == "brief":
        prompt = _append_profile_custom_prompt(
            (
                f"You are a concise assistant for {organization}. "
                "Given the user's request, produce **up to three** SMART goals "
                "as bullet points, each in one short sentence, tailored exactly "
                "to their situation."
            ),
            profile_custom_prompt,
        )
        msgs = (
            [{"role": "system", "content": prompt}]
            + all_messages
            + [{"role": "user", "content": situation}]
        )
        response = call_chatgpt_api_all_chats(
            msgs,
            stream=True,
            max_tokens=200,
            usage_accumulator=usage_accumulator,
        )
        yield from stream_process_chatgpt_response(response, usage_accumulator)
        return

    # ChatGPT mode branch (not used in current integration, but retained)
    if model == "chatgpt":
        msgs = (
            [
                {
                    "role": "system",
                    "content": _append_profile_custom_prompt(
                        (
                            f"You are a Co-Pilot tool for {organization}, "
                            "a peer-peer support org."
                        ),
                        profile_custom_prompt,
                    ),
                }
            ]
            + all_messages
            + [{"role": "user", "content": situation}]
        )
        response = call_chatgpt_api_all_chats(
            msgs,
            stream=True,
            max_tokens=750,
            usage_accumulator=usage_accumulator,
        )
        yield from stream_process_chatgpt_response(response, usage_accumulator)
        return

    # Full copilot orchestration (main path)
    print(f"[Response] Full orchestration at {time.time()}")

    orchestration_messages = [
        {
            "role": "system",
            "content": _append_profile_custom_prompt(
                internal_prompts["orchestration"], profile_custom_prompt
            ),
        },
        {"role": "system", "content": external_resources},
    ]
    orchestration_messages += all_messages
    orchestration_messages += [
        {"role": "user", "content": situation},
        {"role": "user", "content": full_response},
    ]

    print(f"[Response] Streaming orchestration at {time.time()}")
    response = call_chatgpt_api_all_chats(
        orchestration_messages,
        stream=True,
        max_tokens=1000,
        usage_accumulator=usage_accumulator,
    )
    yield from stream_process_chatgpt_response(response, usage_accumulator)


def construct_response(
    situation: str,
    all_messages: list,
    model: str,
    organization: str,
    version: str = "new",
    profile_custom_prompt: Optional[str] = None,
    system_prompt_base: Optional[str] = None,
    tool_call_names_out: Optional[List[str]] = None,
    usage_accumulator: Optional[dict] = None,
):
    # Route to appropriate version implementation
    print(f"[construct_response] Version received: {version}")  # Add this
    if version == "new":
        # NEW VERSION: Current implementation with all tools
        print("[construct_response] Routing to NEW VERSION")  # Add this
        return _construct_response_new(
            situation,
            all_messages,
            model,
            organization,
            profile_custom_prompt,
            system_prompt_base=system_prompt_base,
            tool_call_names_out=tool_call_names_out,
            usage_accumulator=usage_accumulator,
        )
    elif version == "vanilla":
        # VANILLA GPT: Simple prompt → GPT call (no RAG, no tools)
        print("[construct_response] Routing to VANILLA VERSION")  # Add this
        return _construct_response_vanilla(
            situation,
            all_messages,
            model,
            organization,
            profile_custom_prompt,
            usage_accumulator=usage_accumulator,
        )
    else:
        # Default to new version if unknown version
        print("[construct_response] Routing to NEW VERSION (default)")  # Add this
        return _construct_response_new(
            situation,
            all_messages,
            model,
            organization,
            profile_custom_prompt,
            system_prompt_base=system_prompt_base,
            tool_call_names_out=tool_call_names_out,
            usage_accumulator=usage_accumulator,
        )

_ALL_TOOLS_SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "resources_tool",
                "description": (
                    "Find nearby local resources such as food banks, shelters, or clinics. "
                    "Use the location parameter to find resources near a specific place."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for (e.g., 'food banks', 'legal aid')"
                        },
                        "location": {
                            "type": "string",
                            "description": "Where to search near. Can be city name, zip code, or address (e.g., 'Vineland', '07102', 'Newark, NJ'). Optional - omit for statewide results."
                        },
                        "k": {
                            "type": "integer", 
                            "default": 5,
                            "description": "Number of results to return"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "library_tool",
                "description": "Search deep-dive documents for peer support, crisis, or trans-related topics.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["trans", "crisis", "peer"]
                        }
                    },
                    "required": ["query", "category"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "directions_tool",
                "description": "Get distance and travel time between two locations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origin": {"type": "string"},
                        "destination": {"type": "string"},
                        "mode": {
                            "type": "string",
                            "enum": ["driving", "transit", "walking", "bicycling"]
                        }
                    },
                    "required": ["origin", "destination", "mode"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "calculator_tool",
                "description": "Perform basic math calculations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"}
                    },
                    "required": ["expression"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "web_search_tool",
                "description": (
                    "Search the internet for nearby local services, addresses, hours, "
                    "or other information when internal resources are insufficient or unclear."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_eligibility",
                "description": "Check eligibility for benefits: SNAP, TANF, Medicaid, SSDI (SGA), SSI, or Section 8",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "program": {"type": "string", "enum": ["snap", "tanf", "medicaid", "ssdi", "ssi", "section 8"]},
                        "household_size": {"type": "integer"},
                        "monthly_income": {"type": "number"},
                        "location": {"type": "string", "description": "City, zip code, or county in NJ. Required for Section 8 to determine correct AMI limits. If not provided for Section 8, ask the user for their location first."}
                    },
                    "required": ["program", "household_size", "monthly_income"]
                }
            }
        },
    ]


def _construct_response_new(
    situation: str,
    all_messages: list,
    model: str,
    organization: str,
    profile_custom_prompt: Optional[str] = None,
    system_prompt_base: Optional[str] = None,
    tool_call_names_out: Optional[List[str]] = None,
    usage_accumulator: Optional[dict] = None,
):
    print("Organization", organization)

    tools = _ALL_TOOLS_SCHEMA

    base_prompt = system_prompt_base or get_default_peer_copilot_system_prompt(organization)
    system_prompt = _append_profile_custom_prompt(base_prompt, profile_custom_prompt)

    messages = [{"role": "system", "content": system_prompt}]
    messages += all_messages
    messages.append({"role": "user", "content": situation})

    # ---- TOOL LOOP ----
    MAX_TOOL_CALLS = 100  # Safety limit (buffer before OpenAI's 128 limit)
    MAX_ITERATIONS = 25   # Max loop iterations to prevent runaway loops
    total_tool_calls = 0
    iteration_count = 0
    
    while True:
        iteration_count += 1
        
        # Safety check: prevent infinite loops
        if iteration_count > MAX_ITERATIONS:
            # Silently force final response - no user notification
            response = client.chat.completions.create(
                model="gpt-5-chat",
                messages=messages + [{"role": "user", "content": "You have gathered sufficient information. Please provide your final comprehensive answer now."}],
                **azure_chat_stream_options(True),
            )
            for event in response:
                accumulate_usage_from_stream_event(usage_accumulator, event)
                if event.choices and event.choices[0].delta.content:
                    yield f"data: {event.choices[0].delta.content.replace(chr(10), '<br/>')}\n\n"
            break
        
        response = client.chat.completions.create(
            model="gpt-5-chat",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=False,
        )
        accumulate_usage(usage_accumulator, response)

        choice = response.choices[0]

        # FINAL ANSWER (no more tools)
        if choice.finish_reason != "tool_calls":
            final_text = choice.message.content or ""
            for chunk in final_text.split("\n"):
                yield f"data: {chunk}<br/>\n\n"
            break

        # Check tool call count before processing
        num_tool_calls = len(choice.message.tool_calls) if choice.message.tool_calls else 0
        total_tool_calls += num_tool_calls
        
        # Safety check: prevent exceeding OpenAI's limit
        if total_tool_calls >= MAX_TOOL_CALLS:
            # Silently force final response - no user notification
            response = client.chat.completions.create(
                model="gpt-5-chat",
                messages=messages + [{"role": "user", "content": "You have gathered sufficient information. Please provide your final comprehensive answer now."}],
                **azure_chat_stream_options(True),
            )
            for event in response:
                accumulate_usage_from_stream_event(usage_accumulator, event)
                if event.choices and event.choices[0].delta.content:
                    yield f"data: {event.choices[0].delta.content.replace(chr(10), '<br/>')}\n\n"
            break

        # ASSISTANT REQUESTED TOOLS
        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            name = tool_call.function.name
            if tool_call_names_out is not None:
                tool_call_names_out.append(name)
            args = json.loads(tool_call.function.arguments)

            print(f"[DEBUG] Executing {name} with {args}")

            if name == "resources_tool":
                (
                    rag_model,
                    rag_saved_resources,
                    rag_documents_resources,
                    rag_metadata_resources,
                    rag_geo_trees,
                    rag_geo_indices,
                    _rag_saved_articles,
                    _rag_documents_articles,
                ) = get_rag_assets()

                output = resources_tool(
                    query=args.get("query", ""),
                    organization=organization,
                    location=args.get("location"),
                    k=args.get("k", 5),
                    saved_indices=rag_saved_resources,
                    documents=rag_documents_resources,
                    metadata=rag_metadata_resources,
                    geo_trees=rag_geo_trees,
                    geo_indices=rag_geo_indices,
                    embedding_model=rag_model,
                )

            elif name == "library_tool":
                (
                    rag_model,
                    _rag_saved_resources,
                    _rag_documents_resources,
                    _rag_metadata_resources,
                    _rag_geo_trees,
                    _rag_geo_indices,
                    rag_saved_articles,
                    rag_documents_articles,
                ) = get_rag_assets()

                output = library_tool(
                    query=args.get("query", ""),
                    category=args.get("category", "peer"),
                    saved_indices_peer=rag_saved_articles,
                    documents_peer=rag_documents_articles,
                    embedding_model=rag_model,
                )

            elif name == "directions_tool":
                output = directions_tool(
                    origin=args.get("origin", ""),
                    destination=args.get("destination", ""),
                    mode=args.get("mode", "driving")
                )

            elif name == "calculator_tool":
                output = calculator_tool(
                    expression=args.get("expression", "0")
                )

            elif name == "web_search_tool":
                output = web_search_tool(
                    query=args.get("query", "")
                )

            elif name == "check_eligibility":
                output = check_eligibility(
                    program=args.get("program", ""),
                    household_size=args.get("household_size", 1),
                    monthly_income=args.get("monthly_income", 0),
                    location=args.get("location")
                )

            else:
                output = "Error: Unknown tool."

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output
            })

    yield "[DONE]\n\n"

def _construct_response_old(
    situation: str,
    all_messages: list,
    model: str,
    organization: str,
    profile_custom_prompt: Optional[str] = None,
    usage_accumulator: Optional[dict] = None,
):
    """
    Old version: recreate the legacy goals/questions/resources pipeline
    and orchestration behavior (no tools).
    """
    # 1) Run the legacy questions/resources pipeline
    #    This uses internal prompts, RAG over resources, and refinement.
    goals, resources, full_response, external_resources, raw_prompt = fetch_goals_and_resources(
        situation=situation,
        all_messages=all_messages,
        organization=organization,
        k=25,
        usage_accumulator=usage_accumulator,
    )

    # 2) Stream the final response using the legacy orchestration logic.
    #    We explicitly pass model="copilot" to take the full orchestration path.
    return _legacy_construct_response(
        situation=situation,
        all_messages=all_messages,
        model="copilot",
        organization=organization,
        full_response=full_response,
        external_resources=external_resources,
        raw_prompt=raw_prompt,
        profile_custom_prompt=profile_custom_prompt,
        usage_accumulator=usage_accumulator,
    )

_VANILLA_SYSTEM_PROMPT = "You are a helpful assistant. Answer the user's questions. Match the length of your response to the user's request. Use Markdown when it helps organize the response. Format for a chat conversation without too many large headings."

def _construct_response_vanilla(
    situation: str,
    all_messages: list,
    model: str,
    organization: str,
    profile_custom_prompt: Optional[str] = None,
    usage_accumulator: Optional[dict] = None,
):
    """Vanilla GPT (Version B): generic system prompt, same tools as Version A.

    Uses the same tool schema/dispatch as _construct_response_new
    (resources_tool, library_tool, directions_tool, calculator_tool,
    web_search_tool, check_eligibility) so the only difference from Version A
    is the system prompt, not tool access.

    Deliberately ignores profile_custom_prompt (unlike Version A) so this baseline
    stays unbiased by any caseworker-authored custom instructions.
    """
    messages = [
        {"role": "system", "content": _VANILLA_SYSTEM_PROMPT}
    ]
    messages += all_messages
    messages.append({"role": "user", "content": situation})

    MAX_ITERATIONS = 25

    for _ in range(MAX_ITERATIONS):
        response = client.chat.completions.create(
            model="gpt-5-chat",
            messages=messages,
            tools=_ALL_TOOLS_SCHEMA,
            tool_choice="auto",
            stream=False,
        )
        accumulate_usage(usage_accumulator, response)
        choice = response.choices[0]

        if choice.finish_reason != "tool_calls":
            final_text = choice.message.content or ""
            for chunk in final_text.split("\n"):
                yield f"data: {chunk}<br/>\n\n"
            yield "[DONE]\n\n"
            return

        messages.append(choice.message)
        for tool_call in choice.message.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            print(f"[DEBUG] Executing {name} with {args}")

            if name == "resources_tool":
                (
                    rag_model,
                    rag_saved_resources,
                    rag_documents_resources,
                    rag_metadata_resources,
                    rag_geo_trees,
                    rag_geo_indices,
                    _rag_saved_articles,
                    _rag_documents_articles,
                ) = get_rag_assets()

                output = resources_tool(
                    query=args.get("query", ""),
                    organization=organization,
                    location=args.get("location"),
                    k=args.get("k", 5),
                    saved_indices=rag_saved_resources,
                    documents=rag_documents_resources,
                    metadata=rag_metadata_resources,
                    geo_trees=rag_geo_trees,
                    geo_indices=rag_geo_indices,
                    embedding_model=rag_model,
                )

            elif name == "library_tool":
                (
                    rag_model,
                    _rag_saved_resources,
                    _rag_documents_resources,
                    _rag_metadata_resources,
                    _rag_geo_trees,
                    _rag_geo_indices,
                    rag_saved_articles,
                    rag_documents_articles,
                ) = get_rag_assets()

                output = library_tool(
                    query=args.get("query", ""),
                    category=args.get("category", "peer"),
                    saved_indices_peer=rag_saved_articles,
                    documents_peer=rag_documents_articles,
                    embedding_model=rag_model,
                )

            elif name == "directions_tool":
                output = directions_tool(
                    origin=args.get("origin", ""),
                    destination=args.get("destination", ""),
                    mode=args.get("mode", "driving")
                )

            elif name == "calculator_tool":
                output = calculator_tool(
                    expression=args.get("expression", "0")
                )

            elif name == "web_search_tool":
                output = web_search_tool(
                    query=args.get("query", "")
                )

            elif name == "check_eligibility":
                output = check_eligibility(
                    program=args.get("program", ""),
                    household_size=args.get("household_size", 1),
                    monthly_income=args.get("monthly_income", 0),
                    location=args.get("location")
                )

            else:
                output = "Error: Unknown tool."

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output,
            })

    # Safety valve if the tool loop never converges.
    response = client.chat.completions.create(
        model="gpt-5-chat",
        messages=messages + [{"role": "user", "content": "Please give your final answer now."}],
        **azure_chat_stream_options(True),
    )
    for event in response:
        accumulate_usage_from_stream_event(usage_accumulator, event)
        if event.choices and event.choices[0].delta.content:
            formatted_content = event.choices[0].delta.content.replace("\n", "<br/>")
            yield f"data: {formatted_content}\n\n"

    yield "[DONE]\n\n"

