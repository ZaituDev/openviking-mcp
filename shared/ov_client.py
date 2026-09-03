"""
Shared OpenViking HTTP client for braining-mcp and superpowers-mcp.

Both servers talk to the same running openviking-server instance (see
openviking_lifecycle.zsh for how that server gets started/stopped). This
module owns the actual REST calls so neither server re-implements auth,
base-URL resolution, or error handling independently.

Kept intentionally thin: it wraps only the endpoints our tools actually
need, not a general-purpose OpenViking SDK.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

OV_BASE_URL = os.environ.get("OPENVIKING_SERVER_URL", "http://127.0.0.1:1933")
OV_ACCOUNT = os.environ.get("OPENVIKING_ACCOUNT", "")
OV_USER = os.environ.get("OPENVIKING_USER", "")

# In dev-mode auth (no root_api_key configured), no key is required at all.
# If the deployment is later switched to formal multi-tenant mode, a user
# key would need to be read here (e.g. from the same pass/gpg-backed env
# var pattern used for OPENVIKING_VLM_KEY / OPENVIKING_EMBED_KEY) and sent
# as X-API-Key. Left unset for now since this is a solo, local, dev-mode
# deployment per the architecture doc.
OV_API_KEY = os.environ.get("OPENVIKING_API_KEY") or os.environ.get(
    "OPENVIKING_BEARER_TOKEN"
)

# Sent as X-OpenViking-Agent on write-shaped calls. Lets OpenViking attribute
# writes to "braining" vs "superpowers" distinctly, separate from the
# claude-code-memory-plugin's own agentId (which stays at its default,
# since it only does passive background memory capture — see architecture
# doc's Cross-Type Relationships discussion).
OV_AGENT_ID = os.environ.get("OPENVIKING_AGENT_ID", "devclan-mcp")

# ── Relations ────────────────────────────────────────────────────────────
#
# OpenViking's native link()/relations endpoints were confirmed broken
# (100% failure rate) as of an earlier build. That bug is now fixed and
# verified via live smoke test (link() + a fresh GET /api/v1/relations
# both round-tripped correctly against real project URIs). The self-owned
# relations.md fallback that previously worked around this has been
# removed — link() and relations() below are the sole mechanism now.


class OpenVikingError(RuntimeError):
    """Raised when OpenViking returns an error or is unreachable.

    `code` holds the structured error code from OpenViking's response body
    (e.g. "NOT_FOUND", "ALREADY_EXISTS", "UNAVAILABLE") when available, so
    callers can branch on error type reliably instead of string-matching
    the human-readable message.
    """

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class OpenVikingClient:
    def __init__(self, base_url: str = OV_BASE_URL, timeout: float = 30.0, agent_id: str = OV_AGENT_ID):
        headers = {
            "Content-Type": "application/json",
            "X-OpenViking-Agent": agent_id,
        }
        if OV_API_KEY:
            headers["X-API-Key"] = OV_API_KEY
        if OV_ACCOUNT:
            headers["X-OpenViking-Account"] = OV_ACCOUNT
        if OV_USER:
            headers["X-OpenViking-User"] = OV_USER
        self._client = httpx.Client(base_url=base_url, headers=headers, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenVikingClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── internal ────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise OpenVikingError(
                f"Could not reach OpenViking server at {self._client.base_url} — "
                f"is openviking-server running? ({exc})"
            ) from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise OpenVikingError(
                f"OpenViking returned a non-JSON response (status {resp.status_code})"
            ) from exc

        if (
            resp.status_code >= 400
            or data.get("ok") is False
            or data.get("status") == "error"
        ):
            message = data.get("error") or data.get("message") or resp.text
            code = None
            if isinstance(message, dict):
                code = message.get("code")
                message = message.get("message", str(message))
            raise OpenVikingError(f"OpenViking error ({resp.status_code}): {message}", code=code)

        return data

    # ── filesystem / content ────────────────────────────────────────────

    def read(self, uri: str) -> str:
        """Read L2 content of a file. GET /api/v1/content/read"""
        data = self._request("GET", "/api/v1/content/read", params={"uri": uri})
        result = data.get("result", data)
        return result.get("content", "") if isinstance(result, dict) else str(result)

    def write(self, uri: str, content: str, mode: str = "replace") -> dict[str, Any]:
        """Write text content to a file. POST /api/v1/content/write

        mode: "replace" | "append" | "create" — per WriteContentRequest.
        """
        data = self._request(
            "POST",
            "/api/v1/content/write",
            json={"uri": uri, "content": content, "mode": mode},
        )
        return data.get("result", {})

    def mkdir(self, uri: str, description: str | None = None) -> dict[str, Any]:
        """POST /api/v1/fs/mkdir"""
        payload: dict[str, Any] = {"uri": uri}
        if description:
            payload["description"] = description
        data = self._request("POST", "/api/v1/fs/mkdir", json=payload)
        return data.get("result", {})

    def ls(self, uri: str, recursive: bool = False, simple: bool = False) -> list[dict[str, Any]]:
        """GET /api/v1/fs/ls — per the confirmed live OpenAPI schema.

        recursive: list all subdirectories, not just the immediate level.
        simple: return only a relative-path list, no per-entry metadata
        (isDir, abstract, etc). Leave False to get full entries, which
        include `abstract` by default — there is no separate "cheap"
        variant that omits it; abstracts are stored, not computed live.
        """
        params: dict[str, Any] = {"uri": uri}
        if recursive:
            params["recursive"] = True
        if simple:
            params["simple"] = True
        data = self._request("GET", "/api/v1/fs/ls", params=params)
        result = data.get("result", {})
        return result.get("entries", result) if isinstance(result, dict) else result

    def exists(self, uri: str) -> bool:
        """GET /api/v1/fs/stat — 4xx/error means the path doesn't exist."""
        try:
            self._request("GET", "/api/v1/fs/stat", params={"uri": uri})
            return True
        except OpenVikingError:
            return False

    # ── search ──────────────────────────────────────────────────────────

    def find(
        self,
        query: str,
        target_uri: str | list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """POST /api/v1/search/find — per FindRequest schema.

        Stateless semantic search, no session context. Use when the
        caller already knows roughly where to look (a known area of the
        resource tree) or just wants a fast single-shot query.
        """
        payload: dict[str, Any] = {"query": query, "limit": limit}
        if target_uri:
            payload["target_uri"] = target_uri
        data = self._request("POST", "/api/v1/search/find", json=payload)
        return data.get("result", {})

    def search(
        self,
        query: str,
        target_uri: str | list[str] | None = None,
        session_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """POST /api/v1/search/search — per SearchRequest schema.

        session_id is optional (confirmed via the live OpenAPI spec —
        SearchRequest.session_id is nullable, not required). Passing one
        enables session-aware reranking via IntentAnalyzer; omitting it
        still works, but the caller gets plain semantic search with none
        of the session-context benefit that would otherwise justify
        choosing this over find(). If you don't have a session_id, prefer
        find() instead of calling search() without one.
        """
        payload: dict[str, Any] = {"query": query, "limit": limit}
        if target_uri:
            payload["target_uri"] = target_uri
        if session_id:
            payload["session_id"] = session_id
        data = self._request("POST", "/api/v1/search/search", json=payload)
        return data.get("result", {})

    # ── content layers ──────────────────────────────────────────────────

    def abstract(self, uri: str) -> str:
        """GET /api/v1/content/abstract — read L0 abstract."""
        data = self._request("GET", "/api/v1/content/abstract", params={"uri": uri})
        result = data.get("result", data)
        return result.get("content", "") if isinstance(result, dict) else str(result)

    def overview(self, uri: str) -> str:
        """GET /api/v1/content/overview — read L1 overview."""
        data = self._request("GET", "/api/v1/content/overview", params={"uri": uri})
        result = data.get("result", data)
        return result.get("content", "") if isinstance(result, dict) else str(result)

    # ── relations ───────────────────────────────────────────────────────
    #
    # OpenViking's native link()/relations endpoints were confirmed broken
    # (100% failure rate) as of an earlier build. That bug is now fixed
    # and verified via live smoke test (link() + a fresh GET
    # /api/v1/relations both round-tripped correctly against real project
    # URIs, matching the confirmed live shape: a flat list of
    # {"uri": ..., "reason": ...} entries). The self-owned relations.md
    # fallback that previously worked around this has been removed.

    def link(self, from_uri: str, to_uris: str | list[str], reason: str = "") -> dict[str, Any]:
        """POST /api/v1/relations/link — per LinkRequest schema.

        `reason` should be one of a small closed vocabulary so
        list_relations() output stays meaningfully groupable —
        "concluded_from", "promoted_to", "superseded_by" are the three in
        active use across the project tree. Enforce the vocabulary here,
        at write time, rather than trying to normalize it on read.
        """
        data = self._request(
            "POST",
            "/api/v1/relations/link",
            json={"from_uri": from_uri, "to_uris": to_uris, "reason": reason},
        )
        return data.get("result", {})

    def get_relations(self, uri: str) -> list[dict[str, Any]]:
        """GET /api/v1/relations — per the confirmed live response shape:
        a flat list of {"uri": ..., "reason": ...} entries relating to
        the given uri. Grouping by reason (e.g. into concluded_from /
        promoted_to / superseded_by buckets) is a presentation concern —
        see list_relations() in braining_mcp/server.py.
        """
        data = self._request("GET", "/api/v1/relations", params={"uri": uri})
        result = data.get("result", data)
        return result if isinstance(result, list) else result.get("entries", [])

    # ── sessions (for log_context_used / session.used) ─────────────────

    def create_session(self, session_id: str | None = None) -> dict[str, Any]:
        """POST /api/v1/sessions — per CreateSessionRequest. session_id is
        optional; omit to let the server generate one."""
        payload: dict[str, Any] = {}
        if session_id:
            payload["session_id"] = session_id
        data = self._request("POST", "/api/v1/sessions", json=payload)
        return data.get("result", data)

    def get_session(
        self, session_id: str, auto_create: bool = False
    ) -> dict[str, Any]:
        """GET /api/v1/sessions/{id}, optionally creating that exact ID.

        ``auto_create`` is used before session-aware search and ``used()`` so
        those operations also work on the first turn, before the official
        memory plugin's Stop hook has added its first message.
        """
        encoded = quote(session_id, safe="")
        params = {"auto_create": "true"} if auto_create else None
        data = self._request("GET", f"/api/v1/sessions/{encoded}", params=params)
        return data.get("result", data)

    def ensure_session(self, session_id: str) -> dict[str, Any]:
        """Ensure the exact shared session exists without adding messages."""
        return self.get_session(session_id, auto_create=True)

    def session_used(
        self,
        session_id: str,
        context_uris: list[str] | None = None,
        skill: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/sessions/{session_id}/used — per UsedRequest.
        Accepts contexts and/or a skill usage record; at least one should
        be provided.
        """
        payload: dict[str, Any] = {}
        if context_uris:
            payload["contexts"] = context_uris
        if skill:
            payload["skill"] = skill
        encoded = quote(session_id, safe="")
        data = self._request("POST", f"/api/v1/sessions/{encoded}/used", json=payload)
        return data.get("result", {})
