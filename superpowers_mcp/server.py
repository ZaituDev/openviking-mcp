"""
superpowers-mcp — MCP server exposing superpowers' write-contract tools.

Per OPENVIKING_WORKFLOW_ARCHITECTURE.md: superpowers decides HOW, then
builds. It reads decisions, marks them implemented, promotes implemented
decisions into architecture/domains/invariants via staged status-gated mutations,
writes audits, and logs context usage.

Critically: query_decisions never implies authorization to implement.
The ask-first rule lives in the superpowers.md subagent system prompt —
this server only provides the query capability, it does not gate on
confirmation itself (an MCP tool has no way to know whether Zaid already
approved a given item in conversation).

Tools:
    query_decisions            — filter decisions by status
    mark_decision_implemented   — not-implemented -> implemented
    promote_decision            — staged status-gated promotion mutations
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
from relation_domain import (  # noqa: E402
    remove_reciprocal_relation,
    set_reciprocal_relation,
)
from l2_editor import apply_section_edit  # noqa: E402

PROJECT_ROOT = "viking://resources/project"
DECISIONS_URI = f"{PROJECT_ROOT}/decisions"
ARCHITECTURE_URI = f"{PROJECT_ROOT}/architecture"
DOMAINS_URI = f"{PROJECT_ROOT}/domains"
INVARIANTS_URI = f"{PROJECT_ROOT}/invariants"
AUDITS_URI = f"{PROJECT_ROOT}/audits"

VALID_PROMOTION_TARGETS = ("architecture", "domains", "invariants")
VALID_AUDIT_CATEGORIES = ("architecture", "security", "implementation")
VALID_PROMOTION_ACTIONS = ("edit_l2", "set_relation", "remove_relation", "finalize")
PROMOTION_REASON_PAIRS = (
    "promoted_to/derived_from",
    "composes/part_of",
    "enforces/enforced_by",
    "references/referenced_by",
)

TARGET_URI_MAP = {
    "architecture": ARCHITECTURE_URI,
    "domains": DOMAINS_URI,
    "invariants": INVARIANTS_URI,
}


def _validate_decision_uri(dec_uri: str) -> str | None:
    if not isinstance(dec_uri, str):
        return f"dec_uri must be a string, got {type(dec_uri).__name__}"
    if not dec_uri.startswith(f"{DECISIONS_URI}/"):
        return f"dec_uri '{dec_uri}' must start with '{DECISIONS_URI}/'"
    if not dec_uri.endswith(".md"):
        return f"dec_uri '{dec_uri}' must end with '.md'"
    if "*" in dec_uri or "?" in dec_uri:
        return f"dec_uri '{dec_uri}' must not contain wildcards ('*' or '?')"
    if ".." in dec_uri:
        return f"dec_uri '{dec_uri}' must not contain directory traversal ('..')"
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in dec_uri):
        return f"dec_uri '{dec_uri}' must not contain whitespace or control characters"
    path_after_scheme = dec_uri[len("viking://"):]
    if "//" in path_after_scheme:
        return f"dec_uri '{dec_uri}' contains empty path segments"
    filename = dec_uri.rsplit("/", 1)[-1]
    if filename == ".md":
        return f"dec_uri '{dec_uri}' has empty filename"
    return None


def _validate_target_path(target_path: str) -> str | None:
    if not isinstance(target_path, str):
        return f"target_path must be a string, got {type(target_path).__name__}"
    if target_path.startswith("/") or target_path.startswith("viking://"):
        return f"target_path '{target_path}' must be a relative path without leading slash"
    if not target_path.endswith(".md"):
        return f"target_path '{target_path}' must end with '.md'"
    if target_path == ".overview.md" or target_path.endswith("/.overview.md"):
        return f"target_path '{target_path}' cannot be .overview.md"
    if target_path == ".abstract.md" or target_path.endswith("/.abstract.md"):
        return f"target_path '{target_path}' cannot be .abstract.md"
    if "*" in target_path or "?" in target_path:
        return f"target_path '{target_path}' must not contain wildcards ('*' or '?')"
    if ".." in target_path:
        return f"target_path '{target_path}' must not contain directory traversal ('..')"
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in target_path):
        return f"target_path '{target_path}' must not contain whitespace or control characters"
    if "//" in target_path:
        return f"target_path '{target_path}' contains empty path segments"
    filename = target_path.rsplit("/", 1)[-1]
    if filename == ".md":
        return f"target_path '{target_path}' has empty filename"
    return None

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
    action: str,
    target: str | None = None,
    target_path: str | None = None,
    write_mode: str | None = None,
    content: str | None = None,
    section: str | None = None,
    primary: str | None = None,
    secondary: str | None = None,
    reason_pair: str | None = None,
    desc: str | None = None,
) -> dict[str, Any]:
    """Execute a staged promotion action authorized by an implemented decision.

    action: one of "edit_l2", "set_relation", "remove_relation", "finalize".

    Actions:
        edit_l2:
            Update or create a living-truth L2 document under architecture/,
            domains/, or invariants/.
            Requires: target, target_path, write_mode ("create" | "replace" | "edit"),
            and content. When write_mode is "edit", section is required.
        set_relation:
            Create verified reciprocal relations between two endpoints.
            Requires: primary, secondary, reason_pair, desc.
        remove_relation:
            Remove reciprocal relations between two endpoints.
            Requires: primary, secondary.
        finalize:
            Mark the decision as promoted once all staged edits and relations
            are verified. Requires no action-specific parameters.
    """
    if action not in VALID_PROMOTION_ACTIONS:
        return {
            "ok": False,
            "action": action,
            "dec_uri": dec_uri,
            "changed": False,
            "error": {
                "code": "INVALID_ACTION",
                "message": (
                    f"Unknown action '{action}'. Must be one of: "
                    f"{', '.join(VALID_PROMOTION_ACTIONS)}"
                ),
            },
        }

    # Action-specific field enforcement
    if action == "edit_l2":
        if any(f is not None for f in (primary, secondary, reason_pair, desc)):
            return {
                "ok": False,
                "action": "edit_l2",
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "INVALID_ACTION_FIELDS",
                    "message": "Action 'edit_l2' forbids relation fields (primary, secondary, reason_pair, desc)",
                },
            }
        if any(f is None for f in (target, target_path, write_mode, content)):
            return {
                "ok": False,
                "action": "edit_l2",
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "INVALID_ACTION_FIELDS",
                    "message": "Action 'edit_l2' requires target, target_path, write_mode, and content",
                },
            }
        if write_mode == "edit":
            if section is None:
                return {
                    "ok": False,
                    "action": "edit_l2",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "INVALID_ACTION_FIELDS",
                        "message": "Action 'edit_l2' with write_mode='edit' requires section",
                    },
                }
        else:
            if section is not None:
                return {
                    "ok": False,
                    "action": "edit_l2",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "INVALID_ACTION_FIELDS",
                        "message": f"Action 'edit_l2' with write_mode='{write_mode}' forbids section",
                    },
                }

    elif action == "set_relation":
        if any(f is not None for f in (target, target_path, write_mode, content, section)):
            return {
                "ok": False,
                "action": "set_relation",
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "INVALID_ACTION_FIELDS",
                    "message": "Action 'set_relation' forbids L2 content fields (target, target_path, write_mode, content, section)",
                },
            }
        if any(f is None for f in (primary, secondary, reason_pair, desc)):
            return {
                "ok": False,
                "action": "set_relation",
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "INVALID_ACTION_FIELDS",
                    "message": "Action 'set_relation' requires primary, secondary, reason_pair, and desc",
                },
            }
        if not isinstance(primary, str) or not isinstance(secondary, str) or not isinstance(reason_pair, str) or not isinstance(desc, str):
            return {
                "ok": False,
                "action": "set_relation",
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "INVALID_ACTION_FIELDS",
                    "message": "Action 'set_relation' requires primary, secondary, reason_pair, and desc to be strings",
                },
            }

    elif action == "remove_relation":
        if any(f is not None for f in (target, target_path, write_mode, content, section, reason_pair, desc)):
            return {
                "ok": False,
                "action": "remove_relation",
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "INVALID_ACTION_FIELDS",
                    "message": "Action 'remove_relation' accepts only primary and secondary",
                },
            }
        if any(f is None for f in (primary, secondary)):
            return {
                "ok": False,
                "action": "remove_relation",
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "INVALID_ACTION_FIELDS",
                    "message": "Action 'remove_relation' requires primary and secondary",
                },
            }
        if not isinstance(primary, str) or not isinstance(secondary, str):
            return {
                "ok": False,
                "action": "remove_relation",
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "INVALID_ACTION_FIELDS",
                    "message": "Action 'remove_relation' requires primary and secondary to be strings",
                },
            }

    elif action == "finalize":
        if any(f is not None for f in (target, target_path, write_mode, content, section, primary, secondary, reason_pair, desc)):
            return {
                "ok": False,
                "action": "finalize",
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "INVALID_ACTION_FIELDS",
                    "message": "Action 'finalize' accepts no extra parameters",
                },
            }

    # Validate dec_uri format
    dec_err = _validate_decision_uri(dec_uri)
    if dec_err:
        return {
            "ok": False,
            "action": action,
            "dec_uri": dec_uri,
            "changed": False,
            "error": {
                "code": "INVALID_DECISION_URI",
                "message": dec_err,
            },
        }

    with OpenVikingClient() as client:
        # Read and authorize dec_uri
        try:
            dec_content = client.read(dec_uri)
        except OpenVikingError as exc:
            return {
                "ok": False,
                "action": action,
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "DECISION_NOT_FOUND",
                    "message": f"Could not read decision at {dec_uri}: {exc}",
                },
            }

        current_status = get_status(dec_content)
        if current_status != "implemented":
            return {
                "ok": False,
                "action": action,
                "dec_uri": dec_uri,
                "changed": False,
                "error": {
                    "code": "LIFECYCLE_CONFLICT",
                    "message": (
                        f"Decision at {dec_uri} has status '{current_status}', not 'implemented'. "
                        "Only an implemented decision can authorize promotion actions."
                    ),
                },
            }

        # Dispatch action
        if action == "edit_l2":
            if target not in VALID_PROMOTION_TARGETS:
                return {
                    "ok": False,
                    "action": "edit_l2",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "INVALID_TARGET",
                        "message": f"Invalid target '{target}'. Must be one of: {', '.join(VALID_PROMOTION_TARGETS)}",
                    },
                }

            path_err = _validate_target_path(target_path)  # type: ignore[arg-type]
            if path_err:
                return {
                    "ok": False,
                    "action": "edit_l2",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "INVALID_TARGET_PATH",
                        "message": path_err,
                    },
                }

            if write_mode not in ("create", "replace", "edit"):
                return {
                    "ok": False,
                    "action": "edit_l2",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "INVALID_WRITE_MODE",
                        "message": f"Invalid write_mode '{write_mode}'. Must be one of: create, replace, edit",
                    },
                }

            full_target_uri = f"{PROJECT_ROOT}/{target}/{target_path}"

            if write_mode == "create":
                if not content or not content.strip():
                    return {
                        "ok": False,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": False,
                        "error": {
                            "code": "INVALID_CONTENT",
                            "message": "Content cannot be blank for write_mode='create'",
                        },
                    }

                try:
                    stat = client.stat_resource(full_target_uri)
                    exists = True
                except OpenVikingError:
                    exists = False

                if exists:
                    return {
                        "ok": False,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": False,
                        "error": {
                            "code": "TARGET_EXISTS",
                            "message": f"Target '{full_target_uri}' already exists, cannot create",
                        },
                    }

                try:
                    client.write(full_target_uri, content, mode="create")
                except OpenVikingError as exc:
                    return {
                        "ok": False,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": False,
                        "error": {
                            "code": "BACKEND_FAILURE",
                            "message": f"Failed to create L2 document: {exc}",
                        },
                    }

                # Verify read-back
                try:
                    read_back = client.read(full_target_uri)
                    if read_back != content:
                        raise OpenVikingError(f"Read-back content mismatch for '{full_target_uri}'")
                    return {
                        "ok": True,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": True,
                        "result": {
                            "uri": full_target_uri,
                            "target": target,
                            "target_path": target_path,
                            "write_mode": "create",
                        },
                    }
                except Exception as exc:
                    try:
                        client.delete_resource(full_target_uri)
                        return {
                            "ok": False,
                            "action": "edit_l2",
                            "dec_uri": dec_uri,
                            "changed": False,
                            "state_restored": True,
                            "error": {
                                "code": "VERIFICATION_FAILURE",
                                "message": f"Write verification failed, deleted new file: {exc}",
                            },
                        }
                    except Exception as del_exc:
                        return {
                            "ok": False,
                            "action": "edit_l2",
                            "dec_uri": dec_uri,
                            "changed": True,
                            "state_restored": False,
                            "error": {
                                "code": "COMPENSATION_FAILURE",
                                "message": f"Write verification failed ({exc}); cleanup failed: {del_exc}",
                            },
                            "recovery": {
                                "attempted_compensation": "delete_resource",
                                "target_uri": full_target_uri,
                            },
                        }

            elif write_mode == "replace":
                if not content or not content.strip():
                    return {
                        "ok": False,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": False,
                        "error": {
                            "code": "INVALID_CONTENT",
                            "message": "Content cannot be blank for write_mode='replace'",
                        },
                    }

                try:
                    existing_content = client.read(full_target_uri)
                except OpenVikingError as exc:
                    return {
                        "ok": False,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": False,
                        "error": {
                            "code": "TARGET_NOT_FOUND",
                            "message": f"Target '{full_target_uri}' does not exist: {exc}",
                        },
                    }

                if existing_content == content:
                    return {
                        "ok": True,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": False,
                        "result": {
                            "uri": full_target_uri,
                            "target": target,
                            "target_path": target_path,
                            "write_mode": "replace",
                        },
                    }

                try:
                    client.write(full_target_uri, content, mode="replace")
                    read_back = client.read(full_target_uri)
                    if read_back != content:
                        raise OpenVikingError(f"Read-back content mismatch for '{full_target_uri}'")
                    return {
                        "ok": True,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": True,
                        "result": {
                            "uri": full_target_uri,
                            "target": target,
                            "target_path": target_path,
                            "write_mode": "replace",
                        },
                    }
                except Exception as exc:
                    try:
                        client.write(full_target_uri, existing_content, mode="replace")
                        restored = client.read(full_target_uri)
                        if restored != existing_content:
                            raise OpenVikingError("Restored content mismatch")
                        return {
                            "ok": False,
                            "action": "edit_l2",
                            "dec_uri": dec_uri,
                            "changed": False,
                            "state_restored": True,
                            "error": {
                                "code": "VERIFICATION_FAILURE",
                                "message": f"Write verification failed ({exc}); restored previous content",
                            },
                        }
                    except Exception as rest_exc:
                        return {
                            "ok": False,
                            "action": "edit_l2",
                            "dec_uri": dec_uri,
                            "changed": True,
                            "state_restored": False,
                            "error": {
                                "code": "COMPENSATION_FAILURE",
                                "message": f"Write failed ({exc}); restore failed: {rest_exc}",
                            },
                            "recovery": {
                                "attempted_compensation": "restore_content",
                                "target_uri": full_target_uri,
                            },
                        }

            elif write_mode == "edit":
                try:
                    existing_content = client.read(full_target_uri)
                except OpenVikingError as exc:
                    return {
                        "ok": False,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": False,
                        "error": {
                            "code": "TARGET_NOT_FOUND",
                            "message": f"Target '{full_target_uri}' does not exist: {exc}",
                        },
                    }

                try:
                    desired_content = apply_section_edit(existing_content, section, content)  # type: ignore[arg-type]
                except ValueError as exc:
                    return {
                        "ok": False,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": False,
                        "error": {
                            "code": "INVALID_SECTION",
                            "message": str(exc),
                        },
                    }

                if desired_content == existing_content:
                    return {
                        "ok": True,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": False,
                        "result": {
                            "uri": full_target_uri,
                            "target": target,
                            "target_path": target_path,
                            "write_mode": "edit",
                            "section": section,
                        },
                    }

                try:
                    client.write(full_target_uri, desired_content, mode="replace")
                    read_back = client.read(full_target_uri)
                    if read_back != desired_content:
                        raise OpenVikingError(f"Read-back content mismatch for '{full_target_uri}'")
                    return {
                        "ok": True,
                        "action": "edit_l2",
                        "dec_uri": dec_uri,
                        "changed": True,
                        "result": {
                            "uri": full_target_uri,
                            "target": target,
                            "target_path": target_path,
                            "write_mode": "edit",
                            "section": section,
                        },
                    }
                except Exception as exc:
                    try:
                        client.write(full_target_uri, existing_content, mode="replace")
                        restored = client.read(full_target_uri)
                        if restored != existing_content:
                            raise OpenVikingError("Restored content mismatch")
                        return {
                            "ok": False,
                            "action": "edit_l2",
                            "dec_uri": dec_uri,
                            "changed": False,
                            "state_restored": True,
                            "error": {
                                "code": "VERIFICATION_FAILURE",
                                "message": f"Write verification failed ({exc}); restored previous content",
                            },
                        }
                    except Exception as rest_exc:
                        return {
                            "ok": False,
                            "action": "edit_l2",
                            "dec_uri": dec_uri,
                            "changed": True,
                            "state_restored": False,
                            "error": {
                                "code": "COMPENSATION_FAILURE",
                                "message": f"Write failed ({exc}); restore failed: {rest_exc}",
                            },
                            "recovery": {
                                "attempted_compensation": "restore_content",
                                "target_uri": full_target_uri,
                            },
                        }

        elif action == "set_relation":
            if reason_pair not in PROMOTION_REASON_PAIRS:
                return {
                    "ok": False,
                    "action": "set_relation",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "INVALID_REASON_PAIR",
                        "message": (
                            f"Reason pair '{reason_pair}' is not permitted in promote_decision. "
                            f"Must be one of: {', '.join(PROMOTION_REASON_PAIRS)}"
                        ),
                    },
                }

            if reason_pair == "promoted_to/derived_from" and primary != dec_uri:
                return {
                    "ok": False,
                    "action": "set_relation",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "INVALID_RELATION_PRIMARY",
                        "message": (
                            f"For reason_pair 'promoted_to/derived_from', primary must equal dec_uri "
                            f"('{dec_uri}'), got '{primary}'"
                        ),
                    },
                }

            rel_res = set_reciprocal_relation(client, primary, secondary, reason_pair, desc)  # type: ignore[arg-type]
            if rel_res["ok"]:
                return {
                    "ok": True,
                    "action": "set_relation",
                    "dec_uri": dec_uri,
                    "changed": rel_res.get("changed", False),
                    "result": {
                        "primary": primary,
                        "secondary": secondary,
                        "reason_pair": reason_pair,
                        "desc": desc,
                    },
                }

            err_msg = rel_res.get("error", "Failed to set reciprocal relation")
            code = "RELATION_FAILED"
            if rel_res.get("recovery") or rel_res.get("state_restored") is False:
                code = "COMPENSATION_FAILURE"
            elif "Verification failed" in str(err_msg):
                code = "VERIFICATION_FAILURE"
            elif "does not exist" in str(err_msg) or "stat failed" in str(err_msg):
                code = "ENDPOINT_NOT_FOUND"
            elif (
                "must be under" in str(err_msg)
                or "endpoints cannot be identical" in str(err_msg)
                or "Invalid topology" in str(err_msg)
            ):
                code = "INVALID_TOPOLOGY"
            elif (
                "is a directory" in str(err_msg)
                or "must start with" in str(err_msg)
                or "must end with" in str(err_msg)
                or "must be a string" in str(err_msg)
                or "wildcards" in str(err_msg)
                or "traversal" in str(err_msg)
                or "empty path segments" in str(err_msg)
            ):
                code = "INVALID_ENDPOINT_URI"
            elif "Description" in str(err_msg) or "desc" in str(err_msg).lower():
                code = "INVALID_DESCRIPTION"

            set_resp: dict[str, Any] = {
                "ok": False,
                "action": "set_relation",
                "dec_uri": dec_uri,
                "changed": rel_res.get("changed", False),
                "error": {
                    "code": code,
                    "message": str(err_msg),
                },
            }
            if "state_restored" in rel_res:
                set_resp["state_restored"] = rel_res["state_restored"]
            if "recovery" in rel_res:
                set_resp["recovery"] = rel_res["recovery"]
            return set_resp

        elif action == "remove_relation":
            if not isinstance(primary, str) or not isinstance(secondary, str):
                return {
                    "ok": False,
                    "action": "remove_relation",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "INVALID_ACTION_FIELDS",
                        "message": "Action 'remove_relation' requires primary and secondary to be strings",
                    },
                }

            is_dec_primary = primary.startswith(f"{PROJECT_ROOT}/decisions/")
            is_dec_secondary = secondary.startswith(f"{PROJECT_ROOT}/decisions/")
            if (is_dec_primary or is_dec_secondary) and primary != dec_uri:
                return {
                    "ok": False,
                    "action": "remove_relation",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "INVALID_RELATION_PRIMARY",
                        "message": (
                            f"If relation involves a decision URI, primary must equal dec_uri "
                            f"('{dec_uri}'), got primary='{primary}', secondary='{secondary}'"
                        ),
                    },
                }

            rel_res = remove_reciprocal_relation(client, primary, secondary)  # type: ignore[arg-type]
            if rel_res["ok"]:
                return {
                    "ok": True,
                    "action": "remove_relation",
                    "dec_uri": dec_uri,
                    "changed": rel_res.get("changed", False),
                    "result": {
                        "primary": primary,
                        "secondary": secondary,
                    },
                }

            err_msg = rel_res.get("error", "Failed to remove reciprocal relation")
            code = "RELATION_FAILED"
            if rel_res.get("recovery") or rel_res.get("state_restored") is False:
                code = "COMPENSATION_FAILURE"
            elif "Verification failed" in str(err_msg):
                code = "VERIFICATION_FAILURE"
            elif "must start with" in str(err_msg) or "must end with" in str(err_msg):
                code = "INVALID_ENDPOINT_URI"

            rem_resp: dict[str, Any] = {
                "ok": False,
                "action": "remove_relation",
                "dec_uri": dec_uri,
                "changed": rel_res.get("changed", False),
                "error": {
                    "code": code,
                    "message": str(err_msg),
                },
            }
            if "state_restored" in rel_res:
                rem_resp["state_restored"] = rel_res["state_restored"]
            if "recovery" in rel_res:
                rem_resp["recovery"] = rel_res["recovery"]
            return rem_resp

        elif action == "finalize":
            try:
                fresh_content = client.read(dec_uri)
            except OpenVikingError as exc:
                return {
                    "ok": False,
                    "action": "finalize",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "DECISION_NOT_FOUND",
                        "message": f"Could not read decision at {dec_uri}: {exc}",
                    },
                }

            fresh_status = get_status(fresh_content)
            if fresh_status != "implemented":
                return {
                    "ok": False,
                    "action": "finalize",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "LIFECYCLE_CONFLICT",
                        "message": (
                            f"Decision at {dec_uri} has status '{fresh_status}', not 'implemented'. "
                            "Only an implemented decision can be finalized."
                        ),
                    },
                }

            updated_content = with_status(fresh_content, "promoted")
            try:
                client.write(dec_uri, updated_content, mode="replace")
            except OpenVikingError as exc:
                return {
                    "ok": False,
                    "action": "finalize",
                    "dec_uri": dec_uri,
                    "changed": False,
                    "error": {
                        "code": "BACKEND_FAILURE",
                        "message": f"Failed to write promoted status: {exc}",
                    },
                }

            try:
                read_back = client.read(dec_uri)
                if get_status(read_back) != "promoted":
                    raise OpenVikingError("Read-back status is not 'promoted'")
                return {
                    "ok": True,
                    "action": "finalize",
                    "dec_uri": dec_uri,
                    "changed": True,
                    "result": {
                        "uri": dec_uri,
                        "status": "promoted",
                    },
                }
            except Exception as exc:
                try:
                    client.write(dec_uri, fresh_content, mode="replace")
                    restored = client.read(dec_uri)
                    if get_status(restored) != "implemented":
                        raise OpenVikingError("Restored status mismatch")
                    return {
                        "ok": False,
                        "action": "finalize",
                        "dec_uri": dec_uri,
                        "changed": False,
                        "state_restored": True,
                        "error": {
                            "code": "VERIFICATION_FAILURE",
                            "message": f"Finalize verification failed ({exc}); restored status to implemented",
                        },
                    }
                except Exception as rest_exc:
                    return {
                        "ok": False,
                        "action": "finalize",
                        "dec_uri": dec_uri,
                        "changed": True,
                        "state_restored": False,
                        "error": {
                            "code": "COMPENSATION_FAILURE",
                            "message": f"Finalize verification failed ({exc}); restore failed: {rest_exc}",
                        },
                        "recovery": {
                            "attempted_compensation": "restore_status",
                            "dec_uri": dec_uri,
                        },
                    }

    return {"ok": False, "action": action, "dec_uri": dec_uri, "changed": False, "error": {"code": "INVALID_ACTION", "message": "Unknown action"}}


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
