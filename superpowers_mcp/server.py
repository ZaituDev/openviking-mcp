"""
superpowers-mcp — MCP server exposing superpowers' write-contract tools.

Per OPENVIKING_WORKFLOW_ARCHITECTURE.md: superpowers decides HOW, then
builds. It reads decisions, marks them implemented, promotes implemented
decisions into architecture/domains/invariants (atomically, all 4 layers +
link), writes audits, and logs context usage.

Critically: query_decisions never implies authorization to implement.
The ask-first rule lives in the superpowers.md subagent system prompt —
this server only provides the query capability, it does not gate on
confirmation itself (an MCP tool has no way to know whether Zaid already
approved a given item in conversation).

Tools:
    query_decisions            — filter decisions by status
    mark_decision_implemented   — not-implemented -> implemented
    promote_decision            — implemented -> promoted, atomic 5-step write
    write_audit                 — point-in-time report to audits/
    log_context_used            — session.used() wrapper
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

#from mcp.server.fastmcp import FastMCP  # noqa: E402 (deprecated)
from fastmcp import FastMCP  # noqa: E402

from ov_client import OpenVikingClient, OpenVikingError  # noqa: E402
from runtime_session import RuntimeSessionError, resolve_runtime_session_id  # noqa: E402
from uri_guard import UriScopeError, guard_resource_uris  # noqa: E402
from decision_frontmatter import (  # noqa: E402
    VALID_STATUSES,
    get_status,
    with_status,
)

PROJECT_ROOT = "viking://resources/project"
DECISIONS_URI = f"{PROJECT_ROOT}/decisions"
ARCHITECTURE_URI = f"{PROJECT_ROOT}/architecture"
DOMAINS_URI = f"{PROJECT_ROOT}/domains"
INVARIANTS_URI = f"{PROJECT_ROOT}/invariants"
AUDITS_URI = f"{PROJECT_ROOT}/audits"

VALID_PROMOTION_TARGETS = ("architecture", "domains", "invariants")
VALID_AUDIT_CATEGORIES = ("architecture", "security", "implementation")

TARGET_URI_MAP = {
    "architecture": ARCHITECTURE_URI,
    "domains": DOMAINS_URI,
    "invariants": INVARIANTS_URI,
}

mcp = FastMCP("superpowers-mcp")


def _slugify(title: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in title)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:60] or "untitled"


@mcp.tool()
def query_decisions(status: str = "all", domain: str | None = None) -> dict[str, Any]:
    """List decisions filtered by lifecycle status.

    status: one of "not-implemented", "implemented", "promoted",
    "superseded", or "all" (default).

    This is a read-only query. Returning not-implemented decisions here
    is NOT authorization to implement them — per the ask-first rule,
    present the list and wait for User to choose before writing any code.
    """
    if status != "all" and status not in VALID_STATUSES:
        return {
            "error": (
                f"Invalid status '{status}'. Must be one of: "
                f"{', '.join(VALID_STATUSES)}, or 'all'."
            )
        }

    with OpenVikingClient() as client:
        query = domain if domain else "decision"
        try:
            results = client.find(query, target_uri=DECISIONS_URI, limit=50)
        except OpenVikingError as exc:
            return {"error": str(exc)}

        matches = results.get("resources", results.get("results", []))
        if not isinstance(matches, list):
            matches = []

        filtered = []
        for m in matches:
            uri = m.get("uri") if isinstance(m, dict) else None
            if not uri:
                continue
            try:
                content = client.read(uri)
            except OpenVikingError:
                continue
            dec_status = get_status(content)
            if status != "all" and dec_status != status:
                continue
            filtered.append(
                {
                    "uri": uri,
                    "status": dec_status,
                    "score": m.get("score") if isinstance(m, dict) else None,
                }
            )

    return {"status_filter": status, "domain_filter": domain, "decisions": filtered}


@mcp.tool()
def mark_decision_implemented(dec_uri: str) -> dict[str, Any]:
    """Flip a decision's status from not-implemented to implemented.

    This is the ONLY way that transition happens. Does not promote —
    promotion (writing architecture/domains/invariants) is a separate,
    later step via promote_decision. A decision can sit at 'implemented'
    indefinitely without being promoted; that is a valid state, not
    something requiring immediate action.
    """
    with OpenVikingClient() as client:
        try:
            content = client.read(dec_uri)
        except OpenVikingError as exc:
            return {"error": f"Could not read decision: {exc}"}

        current_status = get_status(content)
        if current_status != "not-implemented":
            return {
                "error": (
                    f"Decision at {dec_uri} has status '{current_status}', "
                    "not 'not-implemented'. Refusing to overwrite — only "
                    "a not-implemented decision can be marked implemented."
                )
            }

        updated = with_status(content, "implemented")
        try:
            client.write(dec_uri, updated, mode="replace")
        except OpenVikingError as exc:
            return {"error": f"Failed to update status: {exc}"}

    return {"uri": dec_uri, "status": "implemented"}


@mcp.tool()
def promote_decision(
    dec_uri: str,
    target: str,
    target_path: str,
    l2_content: str,
    overview_update: str,
    abstract_update: str,
) -> dict[str, Any]:
    """Promote an implemented decision into architecture/domains/invariants.

    Rejects the call outright unless dec_uri's status is exactly
    'implemented' — a not-implemented or already-promoted decision cannot
    be (re-)promoted through this tool.

    target: one of "architecture", "domains", "invariants".
    target_path: path within that tree, e.g. "governance/proposal-flow.md".

    Performs all 5 promotion steps atomically in one call:
        1. Write the L2 document at {target}/{target_path}.
        2. Update the parent directory's .overview.md.
        3. Update the parent directory's .abstract.md.
        4. link() the new/updated document back to dec_uri (reason: implements).
        5. Set dec_uri's status to 'promoted'.

    Returns a preview of what was written so this can be reviewed/confirmed
    rather than trusted silently.
    """
    if target not in VALID_PROMOTION_TARGETS:
        return {
            "error": (
                f"Invalid target '{target}'. Must be one of: "
                f"{', '.join(VALID_PROMOTION_TARGETS)}"
            )
        }

    with OpenVikingClient() as client:
        try:
            dec_content = client.read(dec_uri)
        except OpenVikingError as exc:
            return {"error": f"Could not read decision: {exc}"}

        current_status = get_status(dec_content)
        if current_status != "implemented":
            return {
                "error": (
                    f"Decision at {dec_uri} has status '{current_status}', "
                    "not 'implemented'. Only an implemented decision can "
                    "be promoted. Call mark_decision_implemented first if "
                    "the implementation is actually complete and verified."
                )
            }

        target_root = TARGET_URI_MAP[target]
        full_target_uri = f"{target_root}/{target_path.lstrip('/')}"
        parent_uri = full_target_uri.rsplit("/", 1)[0]
        overview_uri = f"{parent_uri}/.overview.md"
        abstract_uri = f"{parent_uri}/.abstract.md"

        # Step 1: L2
        try:
            client.write(full_target_uri, l2_content, mode="replace")
        except OpenVikingError as exc:
            return {"error": f"Failed to write L2 document: {exc}"}

        # Step 2: overview
        try:
            client.write(overview_uri, overview_update, mode="append")
        except OpenVikingError as exc:
            return {
                "error": f"L2 written but overview update failed: {exc}",
                "partial": {"l2_uri": full_target_uri},
            }

        # Step 3: abstract
        try:
            client.write(abstract_uri, abstract_update, mode="append")
        except OpenVikingError as exc:
            return {
                "error": f"L2/overview written but abstract update failed: {exc}",
                "partial": {"l2_uri": full_target_uri, "overview_uri": overview_uri},
            }

        # Step 4: record the relation
        try:
            relation = client.link(full_target_uri, [dec_uri], reason="implements")
        except OpenVikingError as exc:
            # The L2/overview/abstract writes already succeeded — a link
            # failure here shouldn't be reported as if promotion failed.
            relation = {"error": str(exc)}

        # Step 5: status -> promoted
        try:
            updated_dec = with_status(dec_content, "promoted")
            client.write(dec_uri, updated_dec, mode="replace")
        except OpenVikingError as exc:
            return {
                "error": f"Promotion content written but status update failed: {exc}",
                "partial": {
                    "l2_uri": full_target_uri,
                    "overview_uri": overview_uri,
                    "abstract_uri": abstract_uri,
                    "relation": relation,
                },
            }

    return {
        "dec_uri": dec_uri,
        "dec_status": "promoted",
        "l2_uri": full_target_uri,
        "overview_uri": overview_uri,
        "abstract_uri": abstract_uri,
        "relation": relation,
        "preview": {
            "l2_content": l2_content,
            "overview_update": overview_update,
            "abstract_update": abstract_update,
        },
    }


@mcp.tool()
def write_audit(
    category: str,
    title: str,
    content: str,
    related_invariant_uris: list[str] | None = None,
) -> dict[str, Any]:
    """Write a point-in-time audit report.

    category: one of "architecture", "security", "implementation".

    Audits are single-snapshot reports, not accumulated insight — recurring
    conclusions across multiple audits belong in agent/patterns memory
    (extracted automatically via session.commit()), not hand-written here.

    If related_invariant_uris is given, automatically links this audit to
    those invariants (reason: audits).
    """
    if category not in VALID_AUDIT_CATEGORIES:
        return {
            "error": (
                f"Invalid category '{category}'. Must be one of: "
                f"{', '.join(VALID_AUDIT_CATEGORIES)}"
            )
        }

    slug = _slugify(title)
    uri = f"{AUDITS_URI}/{category}/{slug}.md"

    with OpenVikingClient() as client:
        try:
            client.write(uri, f"# {title}\n\n{content}", mode="create")
        except OpenVikingError as exc:
            return {"error": str(exc)}

        relation = None
        if related_invariant_uris:
            try:
                relation = client.link(uri, related_invariant_uris, reason="audits")
            except OpenVikingError as exc:
                relation = {"error": str(exc)}

    return {"uri": uri, "category": category, "linked_invariants": relation}


@mcp.tool()
def log_context_used(
    context_uris: list[str], runtime_session_id: str | None = None
) -> dict[str, Any]:
    """Record decisions/invariants that materially influenced this work.

    Call immediately after retrieved context changes or constrains a plan,
    decision, implementation, or review. This can be correct on the first
    prompt: unlike reasoning search, usage logging has no warm-up period.
    Do not call merely because a resource was searched, listed, or read.

    runtime_session_id is reserved for the client integration; callers should omit it.
    """
    if not context_uris:
        return {"error": "context_uris cannot be empty."}

    try:
        guard_resource_uris(context_uris)
        session_id = resolve_runtime_session_id(runtime_session_id)
    except (UriScopeError, RuntimeSessionError) as exc:
        return {"error": str(exc)}

    with OpenVikingClient() as client:
        try:
            client.ensure_session(session_id)
            result = client.session_used(session_id, context_uris=context_uris)
        except OpenVikingError as exc:
            return {"error": str(exc)}

    return {"session_id": session_id, "logged": context_uris, "result": result}


if __name__ == "__main__":
    mcp.run()
