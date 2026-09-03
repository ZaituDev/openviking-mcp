"""
retrieval-mcp — the shared discovery/verification layer used by both
braining and superpowers (and any future agent) to read the project's
resources/ tree, without either server re-implementing retrieval.

Two layers, per OPENVIKING_WORKFLOW_ARCHITECTURE.md's retrieval review:

    Discovery Layer   — "I need to find relevant knowledge, I don't know
                         the exact file."
        search_project_context   -> find() / search()

    Verification Layer — "I know what I need, give me exact truth."
        list_project_resources   -> ls()
        read_project_resource    -> abstract() / overview() / read()
        list_relations           -> get_relations()

Every tool here is READ-ONLY. This server owns no write ceiling and never
will — writes stay with braining_mcp (research/, decisions/) and
superpowers_mcp (architecture/, domains/, invariants/, audits/). Keeping
retrieval separate from either write-contract server means both can share
the exact same read path without either one gaining the other's write
authority by accident.

Scope: every URI accepted by a tool here is passed through
shared/uri_guard.py's guard_resource_uri[s]() before any OpenViking call
is made. Only viking://resources/* is reachable through this server —
viking://user/*, viking://agent/*, and anything else are out of bounds
for the agent, regardless of what OpenViking itself would allow.

No auto-mode: search_project_context takes an explicit mode, not a
heuristic escalation from find() to search(). Reasoning search performs
intent analysis/query expansion even early in a session; session history
adds value once completed turns have been captured. The caller chooses
that latency/quality tradeoff explicitly instead of this server guessing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

#from mcp.server.fastmcp import FastMCP  # noqa: E402 (deprecated)
from fastmcp import FastMCP  # noqa: E402

from ov_client import OpenVikingClient, OpenVikingError  # noqa: E402
from runtime_session import RuntimeSessionError, resolve_runtime_session_id  # noqa: E402
from uri_guard import UriScopeError, guard_resource_uri, guard_resource_uris  # noqa: E402

PROJECT_ROOT = "viking://resources/project"

mcp = FastMCP("retrieval-mcp")


# ── Discovery ────────────────────────────────────────────────────────────


@mcp.tool()
def search_project_context(
    query: str,
    mode: Literal["flash", "reasoning"] = "flash",
    target_uri: str | None = None,
    limit: int = 10,
    runtime_session_id: str | None = None,
) -> dict[str, Any]:
    """Semantic discovery across project knowledge — use when you don't
    know the exact file/URI, only roughly what you're looking for.

    mode="flash" (default): stateless single-shot semantic search
    (find()). Fast, no session needed. Use this unless you specifically
    need session-aware reranking.

    mode="reasoning": intent-analyzed search with query expansion and
    session-aware context (search()). It can help on a complex or ambiguous
    first prompt, but its session-history advantage begins after at least one
    completed turn has been captured and generally becomes more useful in the
    middle of a session.
    
    target_uri optionally restricts the search to a subtree (e.g. only
    viking://resources/project/decisions) — omit to search all of
    resources/. Always scoped: any target_uri outside
    viking://resources/ is rejected before any call is made.
    """
    try:
        if target_uri:
            guard_resource_uri(target_uri)
        else:
            target_uri = PROJECT_ROOT
    except UriScopeError as exc:
        return {"error": str(exc)}

    resolved_session_id = None
    if mode == "reasoning":
        try:
            resolved_session_id = resolve_runtime_session_id(runtime_session_id)
        except RuntimeSessionError as exc:
            return {"error": str(exc), "mode": mode, "query": query}

    with OpenVikingClient() as client:
        try:
            if mode == "reasoning":
                assert resolved_session_id is not None
                client.ensure_session(resolved_session_id)
                result = client.search(
                    query,
                    target_uri=target_uri,
                    session_id=resolved_session_id,
                    limit=limit,
                )
            else:
                result = client.find(query, target_uri=target_uri, limit=limit)
        except OpenVikingError as exc:
            return {"error": str(exc)}

    response = {"mode": mode, "query": query, "target_uri": target_uri, "result": result}
    if resolved_session_id:
        response["session_id"] = resolved_session_id
    return response


# ── Verification ─────────────────────────────────────────────────────────


@mcp.tool()
def list_project_resources(
    uri: str = PROJECT_ROOT,
    recursive: bool = True,
    verbose: bool = True,
) -> dict[str, Any]:
    """Deterministic inventory of the resources/ tree — use when you know
    the shape you want to enumerate (e.g. "what's in decisions/") rather
    than search for.

    uri defaults to the whole project resources root; pass a subpath to
    scope the listing. Always guarded to viking://resources/* regardless
    of what's passed.

    recursive=True (default) lists all subdirectories, not just the
    immediate level.

    verbose=True (default) returns full entries, including each entry's
    L0 abstract — OpenViking's ls() includes abstracts by default at no
    extra call cost (they're stored, not computed on demand). Set
    verbose=False to strip abstracts from the response when you only
    need the URI/path/isDir shape and want to save context — this is a
    client-side field strip, not a cheaper underlying call.
    """
    try:
        guard_resource_uri(uri)
    except UriScopeError as exc:
        return {"error": str(exc)}

    with OpenVikingClient() as client:
        try:
            entries = client.ls(uri, recursive=recursive)
        except OpenVikingError as exc:
            return {"error": str(exc)}

    if not verbose and isinstance(entries, list):
        entries = [
            {k: v for k, v in e.items() if k != "abstract"} if isinstance(e, dict) else e
            for e in entries
        ]

    return {"uri": uri, "recursive": recursive, "entries": entries}


@mcp.tool()
def read_project_resource(uri: str, detail: Literal["L0", "L1", "L2"] = "L1") -> dict[str, Any]:
    """Load knowledge from a specific, already-known URI at the
    appropriate detail layer. Use after list_project_resources or
    search_project_context has told you the URI you want — this tool
    doesn't discover anything, it just reads.

    detail:
        L0 -> abstract()  — one-line summary, cheapest
        L1 -> overview()  — a few paragraphs, default
        L2 -> read()      — full content, most expensive

    Always guarded to viking://resources/*.
    """
    try:
        guard_resource_uri(uri)
    except UriScopeError as exc:
        return {"error": str(exc)}

    with OpenVikingClient() as client:
        try:
            if detail == "L0":
                content = client.abstract(uri)
            elif detail == "L2":
                content = client.read(uri)
            else:
                content = client.overview(uri)
        except OpenVikingError as exc:
            return {"error": str(exc)}

    return {"uri": uri, "detail": detail, "content": content}


@mcp.tool()
def list_relations(uri: str) -> dict[str, Any]:
    """Graph traversal — what does this resource relate to, and how.

    Groups the raw {"uri", "reason"} entries by `reason` for readability.
    The three reasons in active use across the project are
    concluded_from, promoted_to, and superseded_by  — any other
    reason value found is passed through under its own key rather than
    dropped, since the grouping is presentational, not a filter.

    Always guarded to viking://resources/*.

    Example:
        list_relations("viking://resources/project/decisions/DEC-0024.md")
        ->
        {
          "concluded_from": ["viking://resources/project/research/debates/advisors.md"],
          "promoted_to": ["viking://resources/project/domains/governance/advisors.md"],
          "superseded_by": ["viking://resources/project/decisions/DEC-0031.md"]
        }
    """
    try:
        guard_resource_uri(uri)
    except UriScopeError as exc:
        return {"error": str(exc)}

    with OpenVikingClient() as client:
        try:
            raw = client.get_relations(uri)
        except OpenVikingError as exc:
            return {"error": str(exc)}

    grouped: dict[str, list[str]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        reason = entry.get("reason", "related")
        target = entry.get("uri", "")
        if target:
            grouped.setdefault(reason, []).append(target)

    return {"uri": uri, "relations": grouped}


if __name__ == "__main__":
    mcp.run()
