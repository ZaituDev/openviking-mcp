"""
Shared frontmatter helpers for decisions/DEC-NNNN.md files.

Written once here so braining-mcp and superpowers-mcp never independently
reimplement the status enum or frontmatter shape and risk drifting apart.

Status lifecycle (see OPENVIKING_WORKFLOW_ARCHITECTURE.md):
    not-implemented -> implemented -> promoted
                     \\-> superseded (reachable from any prior state)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import frontmatter

DecisionStatus = Literal["not-implemented", "implemented", "promoted", "superseded"]

VALID_STATUSES: tuple[DecisionStatus, ...] = (
    "not-implemented",
    "implemented",
    "promoted",
    "superseded",
)

DECISION_TEMPLATE = """## Context

{context}

## Problem

{problem}

## Alternatives

{alternatives}

## Decision

{decision}

## Consequences

{consequences}
"""


def build_decision_markdown(
    dec_number: str,
    context: str,
    problem: str,
    alternatives: str,
    decision: str,
    consequences: str,
    status: DecisionStatus = "not-implemented",
    superseded_by: str | None = None,
) -> str:
    """Assemble a full DEC-NNNN.md file: frontmatter + required template
    sections. This is the ONLY place decision content gets assembled —
    tools call this rather than letting the model free-write the
    frontmatter, so a required field can never be silently omitted.
    """
    meta: dict[str, Any] = {
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if superseded_by:
        meta["superseded_by"] = superseded_by

    body = DECISION_TEMPLATE.format(
        context=context.strip(),
        problem=problem.strip(),
        alternatives=alternatives.strip(),
        decision=decision.strip(),
        consequences=consequences.strip(),
    )

    post = frontmatter.Post(f"# DEC-{dec_number}\n\n{body}", **meta)
    return frontmatter.dumps(post)


def parse_decision(content: str) -> tuple[dict[str, Any], str]:
    """Parse an existing DEC-NNNN.md's frontmatter + body."""
    post = frontmatter.loads(content)
    return dict(post.metadata), post.content


def get_status(content: str) -> DecisionStatus | None:
    meta, _ = parse_decision(content)
    status = meta.get("status")
    return status if status in VALID_STATUSES else None


def with_status(content: str, new_status: DecisionStatus, superseded_by: str | None = None) -> str:
    """Return a copy of a decision's content with status (and optionally
    superseded_by) updated, preserving everything else. Used by
    supersede_decision and mark_decision_implemented — never a raw string
    replace, so malformed frontmatter can't silently creep in.
    """
    post = frontmatter.loads(content)
    post.metadata["status"] = new_status
    if superseded_by:
        post.metadata["superseded_by"] = superseded_by
    return frontmatter.dumps(post)


def next_decision_number(existing_uris: list[str]) -> str:
    """Given existing decisions/DEC-NNNN.md URIs, suggest the next number.
    Zero-padded to 4 digits, matching DEC-0001 style used throughout the
    architecture doc.
    """
    max_num = 0
    for uri in existing_uris:
        name = uri.rsplit("/", 1)[-1]  # DEC-0012.md
        digits = "".join(ch for ch in name if ch.isdigit())
        if digits:
            max_num = max(max_num, int(digits))
    return f"{max_num + 1:04d}"
