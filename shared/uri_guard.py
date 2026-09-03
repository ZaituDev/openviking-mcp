"""
Shared URI scoping guard for retrieval-mcp (and any other server that
accepts an agent-supplied URI as a tool argument).

Every retrieval tool takes a URI from the agent. Nothing stops an agent
from passing viking://user/memories, viking://agent/skills, or any other
tree outside resources/ — those exist and are readable via the same
underlying endpoints. This guard is the single place that decision is
enforced, so every tool gets it by construction rather than by each tool
author remembering to check.

Deliberately strict: only viking://resources/ (and its subpaths) are
allowed. Read access to resources/ is fine for any of braining's or
superpowers' retrieval needs — there is no legitimate reason a retrieval
tool call needs to reach into user/ or agent/ trees.
"""

from __future__ import annotations

ALLOWED_PREFIX = "viking://resources/"


class UriScopeError(ValueError):
    """Raised when an agent-supplied URI falls outside viking://resources/."""


def guard_resource_uri(uri: str) -> str:
    """Return uri unchanged if it's inside viking://resources/, else raise
    UriScopeError. Call this at the top of every retrieval tool, before
    any OpenViking call is made — reject before any network round trip.
    """
    if not isinstance(uri, str) or not uri.startswith(ALLOWED_PREFIX):
        raise UriScopeError(
            f"URI '{uri}' is outside the allowed scope. Only URIs under "
            f"'{ALLOWED_PREFIX}' are permitted for retrieval tools."
        )
    return uri


def guard_resource_uris(uris: str | list[str]) -> str | list[str]:
    """Same as guard_resource_uri but accepts either a single URI or a
    list of URIs (find/search's target_uri can be either shape).
    """
    if isinstance(uris, str):
        return guard_resource_uri(uris)
    return [guard_resource_uri(u) for u in uris]
