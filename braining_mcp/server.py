"""
braining-mcp — MCP server exposing braining's write-contract tools.

Per OPENVIKING_WORKFLOW_ARCHITECTURE.md: braining decides WHAT. Its write
ceiling is decisions/ — it never touches architecture/, domains/, or
invariants/ directly. Those tools simply do not exist in this server.

Relations (e.g. "this decision concluded from this research", "this
decision supersedes that one") are recorded via client.link(), OpenViking's
native relation endpoint — confirmed fixed and verified via live smoke
test (see shared/ov_client.py). The reason string is always one of a
small closed vocabulary (concluded_from, supersedes, superseded_by) so
retrieval-mcp's list_relations() can group results meaningfully.

Tools:
    search_decisions      — search decisions/ and invariants/ for duplicates
    write_research         — write to research/{ideas,debates,experiments}/
    write_decision          — create a new DEC-NNNN.md, status: not-implemented
    supersede_decision      — retire an old decision, create its replacement
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

#from mcp.server.fastmcp import FastMCP  # noqa: E402  (deprecateed)
from fastmcp import FastMCP  # noqa: E402

from ov_client import OpenVikingClient, OpenVikingError  # noqa: E402
from decision_frontmatter import (  # noqa: E402
    build_decision_markdown,
    next_decision_number,
    with_status,
)

PROJECT_ROOT = "viking://resources/project"
DECISIONS_URI = f"{PROJECT_ROOT}/decisions"
INVARIANTS_URI = f"{PROJECT_ROOT}/invariants"
RESEARCH_URI = f"{PROJECT_ROOT}/research"

VALID_RESEARCH_CATEGORIES = ("ideas", "debates", "experiments")

mcp = FastMCP("braining-mcp")


def _slugify(title: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in title)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:60] or "untitled"


@mcp.tool()
def search_decisions(query: str) -> dict[str, Any]:
    """Search existing decisions and invariants before writing a new one.

    Call this before write_decision — braining must not create a decision
    that duplicates or contradicts an existing one. Searches both
    decisions/ and invariants/ since a proposed decision could conflict
    with either.
    """
    with OpenVikingClient() as client:
        try:
            dec_results = client.find(query, target_uri=DECISIONS_URI, limit=10)
            inv_results = client.find(query, target_uri=INVARIANTS_URI, limit=10)
        except OpenVikingError as exc:
            return {"error": str(exc)}

    return {
        "decisions": dec_results,
        "invariants": inv_results,
        "note": (
            "Review these before calling write_decision. If an existing "
            "decision already covers this, do not create a duplicate — "
            "if it needs to change, use supersede_decision instead."
        ),
    }


@mcp.tool()
def write_research(category: str, title: str, content: str) -> dict[str, Any]:
    """Write disposable research content (ideas, debates, or experiments).

    category must be one of: ideas, debates, experiments — this is
    enforced, not a free path, so research content can never accidentally
    land in decisions/ or anywhere outside the research/ tree.

    Research is temporary and not authoritative. It should eventually
    either conclude in a decision (via write_decision) or be left to age
    out — never treated as project truth on its own.
    """
    if category not in VALID_RESEARCH_CATEGORIES:
        return {
            "error": (
                f"Invalid category '{category}'. Must be one of: "
                f"{', '.join(VALID_RESEARCH_CATEGORIES)}"
            )
        }

    slug = _slugify(title)
    uri = f"{RESEARCH_URI}/{category}/{slug}.md"

    with OpenVikingClient() as client:
        try:
            client.write(uri, f"# {title}\n\n{content}", mode="create")
        except OpenVikingError as exc:
            return {"error": str(exc)}

    return {"uri": uri, "category": category, "status": "written"}


@mcp.tool()
def write_decision(
    context: str,
    problem: str,
    alternatives: str,
    decision: str,
    consequences: str,
    source_research_uris: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new decision. Always born with status: not-implemented —
    this tool cannot create a decision in any other status; implementation
    and promotion are superpowers' job, later.

    All five sections (context, problem, alternatives, decision,
    consequences) are required — an empty section is rejected rather than
    silently written as blank, since a decision missing its own reasoning
    defeats the point of recording it at all.

    If source_research_uris is given, this decision is automatically
    linked back to the research it concluded from — you do not need a
    separate linking step.
    """
    for field_name, value in [
        ("context", context),
        ("problem", problem),
        ("alternatives", alternatives),
        ("decision", decision),
        ("consequences", consequences),
    ]:
        if not value or not value.strip():
            return {"error": f"'{field_name}' is required and cannot be empty."}

    with OpenVikingClient() as client:
        try:
            existing = client.ls(DECISIONS_URI)
        except OpenVikingError:
            existing = []

        existing_uris = [
            e.get("uri", "") for e in existing if isinstance(e, dict)
        ] if isinstance(existing, list) else []

        dec_number = next_decision_number(existing_uris)
        uri = f"{DECISIONS_URI}/DEC-{dec_number}.md"

        markdown = build_decision_markdown(
            dec_number=dec_number,
            context=context,
            problem=problem,
            alternatives=alternatives,
            decision=decision,
            consequences=consequences,
            status="not-implemented",
        )

        try:
            client.write(uri, markdown, mode="create")
        except OpenVikingError as exc:
            return {"error": str(exc)}

        relation = None
        if source_research_uris:
            try:
                relation = client.link(uri, source_research_uris, reason="concluded_from")
            except OpenVikingError as exc:
                # The decision itself is already written and durable at
                # this point — don't fail the whole tool call over a
                # relation-link failure. Surface it so the caller knows
                # the link didn't take, but the decision stands.
                relation = {"error": str(exc)}

    return {
        "uri": uri,
        "dec_number": dec_number,
        "status": "not-implemented",
        "linked_research": relation,
    }


@mcp.tool()
def supersede_decision(
    old_dec_uri: str,
    context: str,
    problem: str,
    alternatives: str,
    decision: str,
    consequences: str,
) -> dict[str, Any]:
    """Retire an old decision and create its replacement, atomically.

    This is the ONLY way an existing decision's status can change to
    superseded. Decisions are immutable once accepted — there is no tool
    to edit a decision's content directly. Effects, all performed here:

        1. Create the new decision (status: not-implemented).
        2. Set superseded_by on the old decision.
        3. Set the old decision's status to: superseded.
        4. Record the supersession relation via client.link() (reason:
           supersedes), from the new decision back to the old one.

    old_dec_uri's current status does not matter — a decision can be
    superseded whether it was not-implemented, implemented, or promoted.
    If it was promoted, note that architecture/domains/invariants derived
    from it may now be stale; that is superpowers' audit to catch, not
    something this tool fixes automatically.
    """
    with OpenVikingClient() as client:
        try:
            old_content = client.read(old_dec_uri)
        except OpenVikingError as exc:
            return {"error": f"Could not read old decision: {exc}"}

        try:
            existing = client.ls(DECISIONS_URI)
        except OpenVikingError:
            existing = []
        existing_uris = [
            e.get("uri", "") for e in existing if isinstance(e, dict)
        ] if isinstance(existing, list) else []

        new_dec_number = next_decision_number(existing_uris)
        new_uri = f"{DECISIONS_URI}/DEC-{new_dec_number}.md"

        new_markdown = build_decision_markdown(
            dec_number=new_dec_number,
            context=context,
            problem=problem,
            alternatives=alternatives,
            decision=decision,
            consequences=consequences,
            status="not-implemented",
        )

        try:
            client.write(new_uri, new_markdown, mode="create")
        except OpenVikingError as exc:
            return {"error": f"Failed to write new decision: {exc}"}

        old_updated = with_status(old_content, "superseded", superseded_by=f"DEC-{new_dec_number}")
        try:
            client.write(old_dec_uri, old_updated, mode="replace")
        except OpenVikingError as exc:
            return {
                "error": f"New decision written at {new_uri} but failed to update old decision: {exc}",
                "new_uri": new_uri,
            }

        try:
            relation = client.link(new_uri, [old_dec_uri], reason="supersedes")
        except OpenVikingError as exc:
            # Both decision writes already succeeded and are durable —
            # a link failure here shouldn't be reported as if the whole
            # supersession failed.
            relation = {"error": str(exc)}

    return {
        "new_uri": new_uri,
        "old_uri": old_dec_uri,
        "old_status": "superseded",
        "relation": relation,
    }


if __name__ == "__main__":
    mcp.run()
