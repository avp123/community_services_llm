"""
Response generation for the three experiment arms (protocol.md section 1).

Arm A: PeerCoPilot — full RAG + tools, exactly as run in production
        (backend.app.submodules.construct_response, version="new").
Arm B: PeerCoPilot's vanilla baseline, as run in production
        (backend.app.submodules.construct_response, version="vanilla") --
        generic system prompt, but as of 2026-08-30 the SAME tool access as
        Arm A (resources_tool, library_tool, directions_tool,
        calculator_tool, web_search_tool, check_eligibility), so an A/B
        comparison isolates the system prompt rather than being confounded
        by B having weaker tools.
Arm C: generic LLM, no tools (kept as a local reimplementation since there's
       no production "no tools at all" version to route through).
"""
import json
from typing import Dict, List

from backend.app.submodules import construct_response
from backend.app.tools import web_search_tool
from backend.app.utils import client

GENERIC_SYSTEM_PROMPT = "You are a helpful assistant. Answer the user's questions."

# Matches the model used for all three chat-completion call sites in
# backend/app/submodules.py, so the comparison isn't confounded by model choice.
RESPONSE_MODEL = "gpt-5-chat"

_WEB_SEARCH_TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search_tool",
            "description": (
                "Search the internet for nearby local services, addresses, hours, "
                "or other information."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]

_MAX_TOOL_ITERATIONS = 10


def _collect_sse_stream(generator) -> str:
    """Turn construct_response's 'data: ...\\n\\n' / '[DONE]' generator into plain text."""
    parts = []
    for raw in generator:
        if not raw.startswith("data:"):
            continue
        token = raw[len("data: "):].rstrip("\n")
        if token.strip() == "[DONE]":
            continue
        parts.append(token.replace("<br/>", "\n"))
    return "".join(parts).strip()


def run_arm_a(conversation_history: List[Dict], situation: str, organization: str = "cspnj") -> str:
    """Arm A: PeerCoPilot, as run in production (RAG + all tools)."""
    gen = construct_response(
        situation=situation,
        all_messages=conversation_history,
        model=RESPONSE_MODEL,
        organization=organization,
        version="new",
    )
    return _collect_sse_stream(gen)


def _run_generic(conversation_history: List[Dict], situation: str, with_search: bool) -> str:
    messages = [{"role": "system", "content": GENERIC_SYSTEM_PROMPT}]
    messages += conversation_history
    messages.append({"role": "user", "content": situation})

    if not with_search:
        response = client.chat.completions.create(
            model=RESPONSE_MODEL,
            messages=messages,
        )
        return (response.choices[0].message.content or "").strip()

    for _ in range(_MAX_TOOL_ITERATIONS):
        response = client.chat.completions.create(
            model=RESPONSE_MODEL,
            messages=messages,
            tools=_WEB_SEARCH_TOOL_SCHEMA,
            tool_choice="auto",
        )
        choice = response.choices[0]
        if choice.finish_reason != "tool_calls":
            return (choice.message.content or "").strip()

        messages.append(choice.message)
        for tool_call in choice.message.tool_calls:
            args = json.loads(tool_call.function.arguments)
            output = web_search_tool(query=args.get("query", ""))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": output,
                }
            )

    # Safety valve if the tool loop never converges.
    response = client.chat.completions.create(
        model=RESPONSE_MODEL,
        messages=messages + [{"role": "user", "content": "Please give your final answer now."}],
    )
    return (response.choices[0].message.content or "").strip()


def run_arm_b(conversation_history: List[Dict], situation: str, organization: str = "cspnj") -> str:
    """Arm B: PeerCoPilot's vanilla baseline, as run in production (same tools as Arm A)."""
    gen = construct_response(
        situation=situation,
        all_messages=conversation_history,
        model=RESPONSE_MODEL,
        organization=organization,
        version="vanilla",
    )
    return _collect_sse_stream(gen)


def run_arm_c(conversation_history: List[Dict], situation: str) -> str:
    """Arm C: generic LLM, no tools."""
    return _run_generic(conversation_history, situation, with_search=False)


ARM_RUNNERS = {
    "A": lambda history, situation, organization: run_arm_a(history, situation, organization),
    "B": lambda history, situation, organization: run_arm_b(history, situation, organization),
    "C": lambda history, situation, organization: run_arm_c(history, situation),
}
