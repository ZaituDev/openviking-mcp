"""
braining-mcp — MCP server exposing braining's write-contract tools.

Per OPENVIKING_WORKFLOW_ARCHITECTURE.md: braining decides WHAT. Its write
ceiling is decisions/ — it never touches architecture/, domains/, or
invariants/ directly. Those tools simply do not exist in this server.

Relations (e.g. "this decision concluded from this research", "this
decision supersedes that one") are recorded via reciprocal relation
pairs (produces/produced_from, supersedes/superseded_by) with verified
topology and compensation.

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
from relation_domain import set_reciprocal_relation  # noqa: E402

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
    source_research: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Create a new decision. Always born with status: not-implemented —
    this tool cannot create a decision in any other status; implementation
    and promotion are superpowers' job, later.

    All five sections (context, problem, alternatives, decision,
    consequences) are required — an empty section is rejected rather than
    silently written as blank, since a decision missing its own reasoning
    defeats the point of recording it at all.

    If source_research is given, reciprocal produces/produced_from relations
    are established sequentially between each research document and the new
    decision.
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

    if source_research is not None and not isinstance(source_research, list):
        return {"error": "'source_research' must be a list of dicts with 'uri' and 'desc'."}

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

        linked_research: list[dict[str, str]] = []
        if source_research:
            for item in source_research:
                if (
                    not isinstance(item, dict)
                    or "uri" not in item
                    or "desc" not in item
                    or not isinstance(item.get("uri"), str)
                    or not isinstance(item.get("desc"), str)
                ):
                    return {
                        "error": (
                            f"Invalid source_research entry {item}: must be a dict with 'uri' and 'desc' strings. "
                            f"Decision created at {uri} with status 'not-implemented' was preserved."
                        ),
                        "uri": uri,
                        "dec_number": dec_number,
                        "status": "not-implemented",
                        "linked_research": linked_research,
                    }

                item_uri = item["uri"]
                item_desc = item["desc"]

                rel_res = set_reciprocal_relation(
                    client,
                    item_uri,
                    uri,
                    "produces/produced_from",
                    item_desc,
                )

                if not rel_res.get("ok"):
                    return {
                        "error": (
                            f"Failed to link research relation for '{item_uri}': {rel_res.get('error')}. "
                            f"Decision created at {uri} with status 'not-implemented' was preserved."
                        ),
                        "uri": uri,
                        "dec_number": dec_number,
                        "status": "not-implemented",
                        "linked_research": linked_research,
                    }

                linked_research.append({"uri": item_uri, "desc": item_desc})

    return {
        "uri": uri,
        "dec_number": dec_number,
        "status": "not-implemented",
        "linked_research": linked_research,
    }


@mcp.tool()
def supersede_decision(
    old_dec_uri: str,
    context: str,
    problem: str,
    alternatives: str,
    decision: str,
    consequences: str,
    relation_desc: str,
) -> dict[str, Any]:
    """Retire an old decision and create its replacement, atomically.

    This is the ONLY way an existing decision's status can change to
    superseded. Decisions are immutable once accepted — there is no tool
    to edit a decision's content directly. Effects, all performed here:

        1. Create the new decision (status: not-implemented).
        2. Set superseded_by on the old decision.
        3. Set the old decision's status to: superseded.
        4. Record the supersession relation via reciprocal supersedes/superseded_by
           relations between the new decision and old decision.

    old_dec_uri's current status does not matter — a decision can be
    superseded whether it was not-implemented, implemented, or promoted.
    If it was promoted, note that architecture/domains/invariants derived
    from it may now be stale; that is superpowers' audit to catch, not
    something this tool fixes automatically.
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

    if not isinstance(relation_desc, str):
        return {"error": f"'relation_desc' must be a string, got {type(relation_desc).__name__}."}

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in relation_desc):
        return {"error": "'relation_desc' must not contain newlines, tabs, or control characters."}

    if not relation_desc.strip():
        return {"error": "'relation_desc' is required and cannot be empty."}

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

        rel_res = set_reciprocal_relation(
            client,
            new_uri,
            old_dec_uri,
            "supersedes/superseded_by",
            relation_desc,
        )

        if not rel_res.get("ok"):
            return {
                "error": (
                    f"Decisions updated (new: {new_uri}, old: {old_dec_uri} superseded), "
                    f"but reciprocal relation linking failed: {rel_res.get('error')}"
                ),
                "new_uri": new_uri,
                "old_uri": old_dec_uri,
                "old_status": "superseded",
                "relation": rel_res,
            }

    return {
        "new_uri": new_uri,
        "old_uri": old_dec_uri,
        "old_status": "superseded",
        "relation": rel_res,
    }


if __name__ == "__main__":
    mcp.run()
