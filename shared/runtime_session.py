"""Resolve the exact OpenViking session for a session-bound MCP call.

The resolver deliberately has no "latest session" fallback.  "Latest" is
ambiguous as soon as two Claude Code processes are open and can silently log
usage against the wrong conversation.

Precedence is call-local adapter input, an explicit launcher override, then
Claude Code's process environment.  The call-local value is what keeps a
long-lived stdio MCP correct after /clear or an interactive /resume.
"""

from __future__ import annotations

import os


class RuntimeSessionError(RuntimeError):
    """Raised when a session-bound tool cannot identify its exact session."""


def _nonempty(value: str | None, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RuntimeSessionError(f"{source} must be a non-empty string.")
    if value != value.strip():
        raise RuntimeSessionError(f"{source} must not contain surrounding whitespace.")
    return value


def claude_openviking_session_id(claude_session_id: str) -> str:
    """Match the official OpenViking Claude plugin's parent-session mapping."""
    checked = _nonempty(claude_session_id, "Claude Code session_id")
    assert checked is not None
    return f"cc-{checked}"


def resolve_runtime_session_id(runtime_session_id: str | None = None) -> str:
    """Return one exact OpenViking session ID or fail closed.

    ``runtime_session_id`` is adapter-owned tool input.  A generic launcher can
    instead set ``OPENVIKING_SESSION_ID`` to an already-resolved OpenViking ID.
    Claude Code launchers get a safe fresh/resume fallback from
    ``CLAUDE_CODE_SESSION_ID``; a PreToolUse adapter must override that stale
    process value after an in-process session switch.
    """
    injected = _nonempty(runtime_session_id, "runtime_session_id")
    if injected:
        return injected

    configured = _nonempty(os.environ.get("OPENVIKING_SESSION_ID"), "OPENVIKING_SESSION_ID")
    if configured:
        return configured

    claude_session = _nonempty(
        os.environ.get("CLAUDE_CODE_SESSION_ID"), "CLAUDE_CODE_SESSION_ID"
    )
    if claude_session:
        return claude_openviking_session_id(claude_session)

    raise RuntimeSessionError(
        "No exact OpenViking session is available. Configure a client adapter "
        "to inject runtime_session_id, or launch this MCP with a per-session "
        "OPENVIKING_SESSION_ID. Refusing to guess a latest session."
    )
