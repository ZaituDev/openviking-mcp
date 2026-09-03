"""
Shared relation domain — Vocabulary, topology validation, and serialization/parsing.

Owns the canonical reciprocal relation pairs, directional category topology,
single-line serialization format ("<reason>, <desc>"), and split-once parsing
logic with explicit malformed error handling.
"""

from __future__ import annotations

from typing import Any

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
