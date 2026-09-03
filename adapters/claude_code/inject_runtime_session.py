#!/usr/bin/env python3
"""Claude Code PreToolUse adapter for session-bound OpenViking MCP tools."""

from __future__ import annotations

import json
import sys
from typing import Any


def build_hook_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Inject the current parent Claude session as the shared OV session."""
    session_id = payload.get("session_id")
    tool_input = payload.get("tool_input")
    if not isinstance(session_id, str) or not session_id:
        return {}
    if not isinstance(tool_input, dict):
        return {}

    updated_input = dict(tool_input)
    updated_input["runtime_session_id"] = f"cc-{session_id}"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": updated_input,
        }
    }


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        output = build_hook_output(payload if isinstance(payload, dict) else {})
    except (json.JSONDecodeError, OSError):
        output = {}
    json.dump(output, sys.stdout, separators=(",", ":"))


if __name__ == "__main__":
    main()
