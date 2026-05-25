"""Per-layer token attribution — the tokenstack-style computation, reusable
across adapters.

Categorises every tool_use that an agent issued into one of the
tokenstack layers (mcp_servers / subagents / skills / file_io / web /
other) and tracks both call counts and approximate "result tokens"
(chars/4 of the tool_result content that flowed back to the agent).

This is what makes the BUDGET-DOS scoring axis meaningful: instead of
just a flat total-tokens-this-run number, we can ask "how many of those
tokens came from subagent return blobs?" or "did this agent pile its
budget into MCP server calls?"
"""
from __future__ import annotations

from typing import Iterable


CHARS_PER_TOKEN = 4

ALL_LAYERS = ("mcp_servers", "subagents", "skills", "file_io", "web", "other")

_FILE_IO_TOOLS = {"Bash", "Read", "Edit", "Write", "Glob", "Grep", "NotebookEdit"}
_WEB_TOOLS = {"WebFetch", "WebSearch"}
_SUBAGENT_TOOLS = {"Agent", "Task"}


def categorize_tool(name: str | None, tool_input: dict | None = None) -> tuple[str, str]:
    """Map a tool_use name (+ optional input) to (layer, sublabel).

    Examples:
        categorize_tool("Bash")                              -> ("file_io", "Bash")
        categorize_tool("mcp__sentry__list_issues")          -> ("mcp_servers", "sentry")
        categorize_tool("Agent", {"subagent_type": "Trend"}) -> ("subagents", "Trend")
        categorize_tool("Skill", {"skill": "brainstorming"}) -> ("skills", "brainstorming")
        categorize_tool("WebFetch")                          -> ("web", "WebFetch")
        categorize_tool("AskUserQuestion")                   -> ("other", "AskUserQuestion")
    """
    if not name:
        return ("other", "?")
    if name.startswith("mcp__"):
        rest = name[5:]
        sep = rest.find("__")
        server = rest[:sep] if sep > 0 else rest
        return ("mcp_servers", server)
    if name in _SUBAGENT_TOOLS:
        sub = (tool_input or {}).get("subagent_type") or (tool_input or {}).get("subagentType") or "unknown"
        return ("subagents", sub)
    if name == "Skill":
        sk = (tool_input or {}).get("skill") or (tool_input or {}).get("name") or "unknown"
        return ("skills", sk)
    if name in _FILE_IO_TOOLS:
        return ("file_io", name)
    if name in _WEB_TOOLS:
        return ("web", name)
    return ("other", name)


def empty_layer_tokens() -> dict:
    return {layer: {} for layer in ALL_LAYERS}


def chars_of(content) -> int:
    """Approximate character count of a tool_result content payload."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, dict):
        if content.get("type") == "text" and isinstance(content.get("text"), str):
            return len(content["text"])
        if content.get("type") == "tool_result":
            return chars_of(content.get("content"))
        if content.get("type") == "image":
            return 1500   # rough non-zero placeholder
        return 0
    if isinstance(content, (list, tuple)):
        return sum(chars_of(item) for item in content)
    return 0


def attribute_stream_events(events: Iterable[dict]) -> dict:
    """Given a sequence of stream-json-style events (Anthropic shape; assistant
    messages with content blocks of tool_use, and user messages with content
    blocks of tool_result), return per-layer attribution:

        {
          "mcp_servers": {"sentry": {"calls": 3, "result_tokens": 1200}, ...},
          "subagents":   {"general-purpose": {...}, ...},
          ...
        }

    Adapters whose underlying CLI emits a different event shape can pre-massage
    into this shape, OR pass their own categorisation through a simpler helper
    once they've extracted (tool_use_name, tool_input, tool_result_content).
    """
    out = empty_layer_tokens()
    # tool_use_id -> (layer, sub) so we can attribute later tool_result content
    pending: dict[str, tuple[str, str]] = {}

    for ev in events:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        msg = ev.get("message") or {}
        role = msg.get("role") or ev.get("role")

        if etype == "assistant" or role == "assistant":
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    layer, sub = categorize_tool(block.get("name"), block.get("input"))
                    if block.get("id"):
                        pending[block["id"]] = (layer, sub)
                    cell = out[layer].setdefault(sub, {"calls": 0, "result_tokens": 0})
                    cell["calls"] += 1

        if etype == "user" or role == "user":
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    use_id = block.get("tool_use_id")
                    layer_sub = pending.get(use_id)
                    if not layer_sub:
                        continue
                    layer, sub = layer_sub
                    tokens = (chars_of(block.get("content")) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN
                    cell = out[layer].setdefault(sub, {"calls": 0, "result_tokens": 0})
                    cell["result_tokens"] += tokens

    return out
