"""
Shared relation domain — Vocabulary, topology validation, and serialization/parsing.

Owns the canonical reciprocal relation pairs, directional category topology,
single-line serialization format ("<reason>, <desc>"), and split-once parsing
logic with explicit malformed error handling.
"""

from __future__ import annotations

import sys
from typing import Any

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    import types

    class _RequestError(Exception):
        pass

    sys.modules["httpx"] = types.SimpleNamespace(
        Client=object,
        RequestError=_RequestError,
    )

try:
    from ov_client import OpenVikingClient, OpenVikingError
except ImportError:  # pragma: no cover
    from shared.ov_client import OpenVikingClient, OpenVikingError

# Canonical reciprocal vocabulary
RECIPROCAL_PAIRS: dict[str, str] = {
    "produces": "produced_from",
    "produced_from": "produces",
    "supersedes": "superseded_by",
    "superseded_by": "supersedes",
    "promoted_to": "derived_from",
    "derived_from": "promoted_to",
    "composes": "part_of",
    "part_of": "composes",
    "enforces": "enforced_by",
    "enforced_by": "enforces",
    "references": "referenced_by",
    "referenced_by": "references",
}

# Stable error codes for parsing malformed relation entries
PARSE_ERROR_MISSING_DELIMITER = "MISSING_DELIMITER"
PARSE_ERROR_EMPTY_FIELD = "EMPTY_FIELD"
PARSE_ERROR_UNKNOWN_REASON = "UNKNOWN_REASON"
PARSE_ERROR_INVALID_CONTROL_CHARS = "INVALID_CONTROL_CHARS"

# URI path prefixes
PROJECT_PREFIX = "viking://resources/project/"
RESEARCH_PREFIX = "viking://resources/project/research/"
DECISIONS_PREFIX = "viking://resources/project/decisions/"
ARCHITECTURE_PREFIX = "viking://resources/project/architecture/"
DOMAINS_PREFIX = "viking://resources/project/domains/"
INVARIANTS_PREFIX = "viking://resources/project/invariants/"

CANONICAL_TOPOLOGY_RULES: dict[str, tuple[str, str]] = {
    "produces/produced_from": ("produces", "produced_from"),
    "supersedes/superseded_by": ("supersedes", "superseded_by"),
    "promoted_to/derived_from": ("promoted_to", "derived_from"),
    "composes/part_of": ("composes", "part_of"),
    "enforces/enforced_by": ("enforces", "enforced_by"),
    "references/referenced_by": ("references", "referenced_by"),
}


def validate_endpoint_uri(uri: str) -> None:
    """Validate that an endpoint URI is a concrete project Markdown resource.

    Must start with viking://resources/project/, end with .md, have a non-empty
    filename before .md, and contain no wildcards (*, ?), traversal (..),
    whitespace, or control characters.
    """
    if not isinstance(uri, str):
        raise ValueError(f"URI must be a string, got {type(uri).__name__}")

    if not uri.startswith(PROJECT_PREFIX):
        raise ValueError(f"URI '{uri}' must start with '{PROJECT_PREFIX}'")

    if not uri.endswith(".md"):
        raise ValueError(f"URI '{uri}' must end with '.md'")

    if "*" in uri or "?" in uri:
        raise ValueError(f"URI '{uri}' must not contain wildcards ('*' or '?')")

    if ".." in uri:
        raise ValueError(f"URI '{uri}' must not contain directory traversal ('..')")

    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in uri):
        raise ValueError(f"URI '{uri}' must not contain whitespace or control characters")

    # Path after viking://
    path_after_scheme = uri[len("viking://"):]
    if "//" in path_after_scheme:
        raise ValueError(f"URI '{uri}' contains empty path segments")

    filename = uri.rsplit("/", 1)[-1]
    if filename == ".md":
        raise ValueError(f"URI '{uri}' must have a filename before '.md'")


def validate_topology(primary: str, secondary: str, reason_pair: str) -> tuple[str, str]:
    """Validate directional category topology between primary and secondary endpoints.

    Returns (primary_reason, secondary_reason) if the pair is topologically valid.
    Raises ValueError on any violation.
    """
    validate_endpoint_uri(primary)
    validate_endpoint_uri(secondary)

    if primary == secondary:
        raise ValueError("Primary and secondary endpoints cannot be identical")

    if reason_pair not in CANONICAL_TOPOLOGY_RULES:
        raise ValueError(
            f"Unknown or invalid reason_pair '{reason_pair}'. "
            f"Allowed pairs: {sorted(CANONICAL_TOPOLOGY_RULES.keys())}"
        )

    primary_reason, secondary_reason = CANONICAL_TOPOLOGY_RULES[reason_pair]

    if reason_pair == "produces/produced_from":
        if not primary.startswith(RESEARCH_PREFIX):
            raise ValueError(
                f"produces/produced_from primary must be under '{RESEARCH_PREFIX}', got '{primary}'"
            )
        if not secondary.startswith(DECISIONS_PREFIX):
            raise ValueError(
                f"produces/produced_from secondary must be under '{DECISIONS_PREFIX}', got '{secondary}'"
            )

    elif reason_pair == "supersedes/superseded_by":
        if not primary.startswith(DECISIONS_PREFIX):
            raise ValueError(
                f"supersedes/superseded_by primary must be under '{DECISIONS_PREFIX}', got '{primary}'"
            )
        if not secondary.startswith(DECISIONS_PREFIX):
            raise ValueError(
                f"supersedes/superseded_by secondary must be under '{DECISIONS_PREFIX}', got '{secondary}'"
            )

    elif reason_pair == "promoted_to/derived_from":
        if not primary.startswith(DECISIONS_PREFIX):
            raise ValueError(
                f"promoted_to/derived_from primary must be under '{DECISIONS_PREFIX}', got '{primary}'"
            )
        valid_secondary = (
            secondary.startswith(ARCHITECTURE_PREFIX)
            or secondary.startswith(DOMAINS_PREFIX)
            or secondary.startswith(INVARIANTS_PREFIX)
        )
        if not valid_secondary:
            raise ValueError(
                f"promoted_to/derived_from secondary must be under architecture/, domains/, or invariants/, got '{secondary}'"
            )

    elif reason_pair == "composes/part_of":
        if not primary.startswith(ARCHITECTURE_PREFIX):
            raise ValueError(
                f"composes/part_of primary must be under '{ARCHITECTURE_PREFIX}', got '{primary}'"
            )
        if not secondary.startswith(DOMAINS_PREFIX):
            raise ValueError(
                f"composes/part_of secondary must be under '{DOMAINS_PREFIX}', got '{secondary}'"
            )

    elif reason_pair == "enforces/enforced_by":
        if not primary.startswith(INVARIANTS_PREFIX):
            raise ValueError(
                f"enforces/enforced_by primary must be under '{INVARIANTS_PREFIX}', got '{primary}'"
            )
        if not secondary.startswith(DOMAINS_PREFIX):
            raise ValueError(
                f"enforces/enforced_by secondary must be under '{DOMAINS_PREFIX}', got '{secondary}'"
            )

    elif reason_pair == "references/referenced_by":
        # Any valid project Markdown resource to any other valid project Markdown resource
        pass

    return primary_reason, secondary_reason


def serialize_relation_reason(directional_reason: str, desc: str) -> str:
    """Serialize directional reason and description to the native OpenViking format.

    Format: "<directional_reason>, <trimmed_desc>"
    Raises ValueError if desc is empty after trim, contains newlines/tabs/control chars,
    or if directional_reason is unknown.
    """
    if not isinstance(directional_reason, str) or directional_reason not in RECIPROCAL_PAIRS:
        raise ValueError(f"Invalid or unknown directional reason '{directional_reason}'")

    if not isinstance(desc, str):
        raise ValueError(f"Description must be a string, got {type(desc).__name__}")

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in desc):
        raise ValueError("Description must not contain newlines, tabs, or control characters")

    trimmed_desc = desc.strip()
    if not trimmed_desc:
        raise ValueError("Description cannot be empty")

    return f"{directional_reason}, {trimmed_desc}"


def parse_relation_reason(raw_reason: str) -> dict[str, Any]:
    """Parse a native OpenViking relation reason string into a structured dict.

    Splits once on the first comma. Returns {"reason": reason, "desc": desc} if valid.
    Preserves all subsequent commas in desc.
    If malformed (missing delimiter, empty field, unknown reason, control chars),
    returns {"raw_reason": raw_reason, "parse_error": "<stable_code>"}.
    """
    if not isinstance(raw_reason, str):
        return {"raw_reason": str(raw_reason), "parse_error": PARSE_ERROR_MISSING_DELIMITER}

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_reason):
        return {"raw_reason": raw_reason, "parse_error": PARSE_ERROR_INVALID_CONTROL_CHARS}

    if "," not in raw_reason:
        return {"raw_reason": raw_reason, "parse_error": PARSE_ERROR_MISSING_DELIMITER}

    parts = raw_reason.split(",", 1)
    reason = parts[0].strip()
    desc = parts[1].strip()

    if not reason or not desc:
        return {"raw_reason": raw_reason, "parse_error": PARSE_ERROR_EMPTY_FIELD}

    if reason not in RECIPROCAL_PAIRS:
        return {"raw_reason": raw_reason, "parse_error": PARSE_ERROR_UNKNOWN_REASON}

    return {"reason": reason, "desc": desc}


def _relation_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("uri") or ""), str(item.get("reason") or ""))


def _compare_relation_lists(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    return sorted(_relation_key(item) for item in a) == sorted(_relation_key(item) for item in b)


def snapshot_relations(
    client: OpenVikingClient, primary: str, secondary: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Get all relations on primary pointing to secondary, and secondary pointing to primary.

    Validates that primary and secondary are valid endpoint URIs and distinct.
    Returns (primary_to_secondary_links, secondary_to_primary_links).
    """
    validate_endpoint_uri(primary)
    validate_endpoint_uri(secondary)
    if primary == secondary:
        raise ValueError("Primary and secondary endpoints cannot be identical")

    primary_relations = client.get_relations(primary) or []
    secondary_relations = client.get_relations(secondary) or []

    primary_links = [
        entry
        for entry in primary_relations
        if isinstance(entry, dict) and entry.get("uri") == secondary
    ]
    secondary_links = [
        entry
        for entry in secondary_relations
        if isinstance(entry, dict) and entry.get("uri") == primary
    ]
    return primary_links, secondary_links


def set_reciprocal_relation(
    client: OpenVikingClient,
    primary: str,
    secondary: str,
    reason_pair: str,
    desc: str,
) -> dict[str, Any]:
    """Atomically configure a verified reciprocal relation pair with compensation.

    - Validates endpoint URIs and topology, serializes directional reasons.
    - Validates endpoints exist as files (not directories) via stat_resource.
    - Takes pre-call snapshot of existing links between primary and secondary.
    - If exact reciprocal pair already exists without drift, returns {"ok": True, "changed": False}.
    - Removes existing drift, links both directions, and verifies read-back.
    - If any link or verification fails, compensates by restoring pre-call snapshot.
    - If compensation succeeds, returns {"ok": False, "changed": False, "state_restored": True, "error": ...}.
    - If compensation fails, returns {"ok": False, "changed": True, "state_restored": False, "error": ..., "recovery": ...}.
    """
    try:
        primary_reason, secondary_reason = validate_topology(primary, secondary, reason_pair)
        serialized_primary = serialize_relation_reason(primary_reason, desc)
        serialized_secondary = serialize_relation_reason(secondary_reason, desc)
    except ValueError as exc:
        return {"ok": False, "changed": False, "error": str(exc)}

    for endpoint in (primary, secondary):
        try:
            stat = client.stat_resource(endpoint)
        except OpenVikingError as exc:
            return {
                "ok": False,
                "changed": False,
                "error": f"Endpoint '{endpoint}' does not exist or stat failed: {exc}",
            }
        if stat.get("isDir") is True or stat.get("is_dir") is True:
            return {
                "ok": False,
                "changed": False,
                "error": f"Endpoint '{endpoint}' is a directory, must be a file",
            }

    try:
        pre_primary_links, pre_secondary_links = snapshot_relations(client, primary, secondary)
    except Exception as exc:
        return {"ok": False, "changed": False, "error": f"Failed to snapshot relations: {exc}"}

    desired_primary = [{"uri": secondary, "reason": serialized_primary}]
    desired_secondary = [{"uri": primary, "reason": serialized_secondary}]

    if _compare_relation_lists(pre_primary_links, desired_primary) and _compare_relation_lists(
        pre_secondary_links, desired_secondary
    ):
        return {"ok": True, "changed": False}

    primary_linked = False
    secondary_linked = False
    error_reason: str | None = None

    try:
        # Unlink existing drift between primary and secondary
        if pre_primary_links:
            client.unlink(primary, secondary)
        if pre_secondary_links:
            client.unlink(secondary, primary)

        # Link primary -> secondary
        client.link(primary, secondary, serialized_primary)
        primary_linked = True

        # Link secondary -> primary
        client.link(secondary, primary, serialized_secondary)
        secondary_linked = True

        # Verify read-back
        post_primary, post_secondary = snapshot_relations(client, primary, secondary)
        if not _compare_relation_lists(post_primary, desired_primary):
            raise OpenVikingError(
                f"Verification failed on primary endpoint: expected {desired_primary}, got {post_primary}"
            )
        if not _compare_relation_lists(post_secondary, desired_secondary):
            raise OpenVikingError(
                f"Verification failed on secondary endpoint: expected {desired_secondary}, got {post_secondary}"
            )

        return {"ok": True, "changed": True}

    except Exception as exc:
        error_reason = str(exc)

    # Compensation on failure: restore exact pre-call snapshot
    try:
        curr_p, curr_s = snapshot_relations(client, primary, secondary)

        # Restore primary
        if not _compare_relation_lists(curr_p, pre_primary_links):
            if curr_p:
                client.unlink(primary, secondary)
            for entry in pre_primary_links:
                reason = entry.get("reason") or ""
                client.link(primary, secondary, reason)

        # Restore secondary
        if not _compare_relation_lists(curr_s, pre_secondary_links):
            if curr_s:
                client.unlink(secondary, primary)
            for entry in pre_secondary_links:
                reason = entry.get("reason") or ""
                client.link(secondary, primary, reason)

        restored_p, restored_s = snapshot_relations(client, primary, secondary)
        if not _compare_relation_lists(
            restored_p, pre_primary_links
        ) or not _compare_relation_lists(restored_s, pre_secondary_links):
            raise OpenVikingError(
                f"Restored relation state mismatch: primary={restored_p} (expected {pre_primary_links}), "
                f"secondary={restored_s} (expected {pre_secondary_links})"
            )

        return {
            "ok": False,
            "changed": False,
            "state_restored": True,
            "error": error_reason,
        }

    except Exception as comp_exc:
        try:
            now_p, now_s = snapshot_relations(client, primary, secondary)
        except Exception:
            now_p, now_s = [], []

        return {
            "ok": False,
            "changed": True,
            "state_restored": False,
            "error": f"{error_reason}; compensation failed: {comp_exc}",
            "recovery": {
                "primary_failed": not primary_linked
                or not _compare_relation_lists(now_p, desired_primary),
                "secondary_failed": not secondary_linked
                or not _compare_relation_lists(now_s, desired_secondary),
                "current_state": {"primary": now_p, "secondary": now_s},
                "pre_call_state": {
                    "primary": pre_primary_links,
                    "secondary": pre_secondary_links,
                },
                "desired_state": {"primary": desired_primary, "secondary": desired_secondary},
                "attempted_compensation": "restore_snapshot",
            },
        }


def remove_reciprocal_relation(
    client: OpenVikingClient,
    primary: str,
    secondary: str,
) -> dict[str, Any]:
    """Remove reciprocal relations between primary and secondary endpoints.

    Validates endpoint URI syntax.
    Snapshots existing links between them.
    If neither direction has any links, returns {"ok": True, "changed": False}.
    Otherwise unlinks both directions and verifies.
    If unlinking or verification fails, compensates by restoring the snapshot.
    """
    try:
        validate_endpoint_uri(primary)
        validate_endpoint_uri(secondary)
        if primary == secondary:
            raise ValueError("Primary and secondary endpoints cannot be identical")
    except ValueError as exc:
        return {"ok": False, "changed": False, "error": str(exc)}

    try:
        pre_primary_links, pre_secondary_links = snapshot_relations(client, primary, secondary)
    except Exception as exc:
        return {"ok": False, "changed": False, "error": f"Failed to snapshot relations: {exc}"}

    # If neither direction has any link between primary and secondary
    if not pre_primary_links and not pre_secondary_links:
        return {"ok": True, "changed": False}

    error_reason: str | None = None
    try:
        if pre_primary_links:
            client.unlink(primary, secondary)
        if pre_secondary_links:
            client.unlink(secondary, primary)

        # Verify both directions have 0 links between each other
        post_primary, post_secondary = snapshot_relations(client, primary, secondary)
        if post_primary or post_secondary:
            raise OpenVikingError(
                f"Verification failed: links still present between endpoints after remove: "
                f"primary={post_primary}, secondary={post_secondary}"
            )

        return {"ok": True, "changed": True}

    except Exception as exc:
        error_reason = str(exc)

    # Compensation on failure: restore snapshot
    try:
        curr_p, curr_s = snapshot_relations(client, primary, secondary)

        # Restore primary
        if not _compare_relation_lists(curr_p, pre_primary_links):
            if curr_p:
                client.unlink(primary, secondary)
            for entry in pre_primary_links:
                reason = entry.get("reason") or ""
                client.link(primary, secondary, reason)

        # Restore secondary
        if not _compare_relation_lists(curr_s, pre_secondary_links):
            if curr_s:
                client.unlink(secondary, primary)
            for entry in pre_secondary_links:
                reason = entry.get("reason") or ""
                client.link(secondary, primary, reason)

        restored_p, restored_s = snapshot_relations(client, primary, secondary)
        if not _compare_relation_lists(
            restored_p, pre_primary_links
        ) or not _compare_relation_lists(restored_s, pre_secondary_links):
            raise OpenVikingError("Verification of restored state failed after remove rollback")

        return {
            "ok": False,
            "changed": False,
            "state_restored": True,
            "error": error_reason,
        }

    except Exception as comp_exc:
        try:
            now_p, now_s = snapshot_relations(client, primary, secondary)
        except Exception:
            now_p, now_s = [], []

        return {
            "ok": False,
            "changed": True,
            "state_restored": False,
            "error": f"{error_reason}; compensation failed: {comp_exc}",
            "recovery": {
                "primary_failed": bool(now_p),
                "secondary_failed": bool(now_s),
                "current_state": {"primary": now_p, "secondary": now_s},
                "pre_call_state": {
                    "primary": pre_primary_links,
                    "secondary": pre_secondary_links,
                },
                "desired_state": {"primary": [], "secondary": []},
                "attempted_compensation": "restore_snapshot",
            },
        }
