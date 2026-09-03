# Living Truth & Staged Promotion Relations Design Specification

This document provides the authoritative specification for reciprocal relations, living-truth mutations, staged decision promotion, and graph retrieval across the devClan OpenViking MCP servers (`braining_mcp`, `superpowers_mcp`, and `retrieval_mcp`).

---

## 1. Reciprocal Relation Reason Vocabulary

OpenViking relations form an explicit, verified bidirectional graph. Relations are always established in reciprocal pairs between two distinct, concrete Markdown endpoints under `viking://resources/project/`.

### Canonical Vocabulary Pairs (6 Pairs)

| Canonical Reason Pair | Primary Direction | Secondary Direction | Valid Endpoint Topology |
| :--- | :--- | :--- | :--- |
| `produces/produced_from` | `produces` | `produced_from` | Research (`research/`) ⇄ Decision (`decisions/`) |
| `supersedes/superseded_by` | `supersedes` | `superseded_by` | Decision (`decisions/`) ⇄ Decision (`decisions/`) |
| `promoted_to/derived_from` | `promoted_to` | `derived_from` | Decision (`decisions/`) ⇄ Living Truth (`architecture/`, `domains/`, `invariants/`) |
| `composes/part_of` | `composes` | `part_of` | Architecture (`architecture/`) ⇄ Domain (`domains/`) |
| `enforces/enforced_by` | `enforces` | `enforced_by` | Invariant (`invariants/`) ⇄ Domain (`domains/`) |
| `references/referenced_by` | `references` | `referenced_by` | Any project Markdown resource ⇄ Any project Markdown resource |

### Directional Semantic Map

- **`produces` ⇄ `produced_from`**: A research document (idea, debate, or experiment) produces a concrete decision; conversely, the decision is produced from that research inquiry.
- **`supersedes` ⇄ `superseded_by`**: A newer decision supersedes an older decision; the retired decision is superseded by the new decision.
- **`promoted_to` ⇄ `derived_from`**: An implemented decision is promoted to living-truth architecture, domain rules, or invariants; the living truth is derived from that authoritative decision.
- **`composes` ⇄ `part_of`**: High-level architecture composes specific domain concepts; the domain concept is part of that architectural subsystem.
- **`enforces` ⇄ `enforced_by`**: An invariant rule enforces domain behaviors; the domain is enforced by that invariant constraint.
- **`references` ⇄ `referenced_by`**: General cross-cutting informational reference between any two project resources.

### Relational Topology Graph

```
                   Research (research/)
                            ⇄
                 produces / produced_from
                            ⇄
                   Decision (decisions/)
        ⇄                                        ⇄
supersedes /                             promoted_to /
superseded_by                            derived_from
        ⇄                                 /      |      \
    Decision                             ▼       ▼       ▼
                               Architecture   Domains   Invariants
                                    (architecture/) (domains/) (invariants/)
                                         ⇄               ⇄
                                     composes /      enforces /
                                     part_of         enforced_by
```

### Endpoint URI Constraints

Every endpoint participating in a relation must satisfy strict path validation:
- Must begin with `viking://resources/project/`.
- Must terminate with `.md` with a non-empty filename (e.g., `.../DEC-0001.md`, not `.../.md`).
- Must not contain wildcards (`*`, `?`), directory traversal (`..`), or consecutive empty slashes (`//`).
- Must not contain whitespace or ASCII control characters (< 32, 127).
- Primary and secondary endpoints cannot be identical.
- Both endpoints must exist as durable files (verified via `stat_resource`; directory endpoints are rejected).

---

## 2. Storage Format & Serialization

Relations are natively stored in OpenViking via the standard `POST /api/v1/relations` endpoint using the single `reason` string field.

### Format Convention

```text
<directional_reason>, <trimmed description>
```

When creating a reciprocal relation between endpoint $A$ (primary) and endpoint $B$ (secondary) with reason pair `P/S` and description `D`:
- On endpoint $A$, pointing to $B$: stored reason is `P, D`
- On endpoint $B$, pointing to $A$: stored reason is `S, D`

### Serialization Rules

- **Directional Reason**: Must exactly match one of the 12 canonical directional reasons (`produces`, `produced_from`, `supersedes`, `superseded_by`, `promoted_to`, `derived_from`, `composes`, `part_of`, `enforces`, `enforced_by`, `references`, `referenced_by`).
- **Delimiter**: A comma followed by a single space (`, `).
- **Description**: Must be non-empty after trimming leading and trailing whitespace.
- **Forbidden Characters in Description**: Must not contain newlines, carriage returns, tabs, or ASCII control characters. Subsequent commas inside the description are valid and preserved verbatim.

---

## 3. Parsing Rules & Malformed Entry Handling

The parsing rule splits once on the first comma:

```text
before first comma  -> reason
after first comma   -> desc
```

### Parsing Logic

Given raw relation string `raw_reason`:
1. If `raw_reason` contains control characters (newlines, tabs, ASCII < 32 or 127), fail with parse error `INVALID_CONTROL_CHARS`.
2. If `raw_reason` contains no comma delimiter, fail with parse error `MISSING_DELIMITER`.
3. Split once on the first comma: `parts = raw_reason.split(",", 1)`.
4. Strip whitespace from both components: `reason = parts[0].strip()`, `desc = parts[1].strip()`.
5. If `reason` or `desc` is empty, fail with parse error `EMPTY_FIELD`.
6. If `reason` is not present in the canonical reciprocal vocabulary, fail with parse error `UNKNOWN_REASON`.
7. Return valid parsed dict: `{"reason": reason, "desc": desc}`.

### Tolerant Handling for Retrieval

When `retrieval_mcp.list_relations` encounters relation entries:
- **Valid Entries**: Serialized as `{"uri": uri, "reason": reason, "desc": desc}`.
- **Malformed Entries**: Returned explicitly with `{"uri": uri, "raw_reason": raw_reason, "parse_error": "<ERROR_CODE>"}`. Legacy or malformed records never crash the retrieval layer or get silently dropped.

---

## 4. Reciprocal Transactions & Fault Tolerance

Relation mutations must maintain reciprocal consistency across both endpoints. OpenViking native endpoints operate on single-link calls (`link` and `unlink`), so reciprocal transactions provide application-level consistency with snapshotting, verification, and exact-state compensation.

### Transaction Lifecycle for `set_reciprocal_relation`

```
1. Syntax & Topology Validation
   ├── Validate primary & secondary URIs
   └── Validate directional reason pair against category topology
2. Existence Check
   ├── stat_resource(primary)   -> verify file exists and is not directory
   └── stat_resource(secondary) -> verify file exists and is not directory
3. Pre-call Snapshot
   ├── Snapshot existing links on primary pointing to secondary
   └── Snapshot existing links on secondary pointing to primary
4. Idempotency Check
   └── If exact reciprocal pair already exists without drift:
       return {"ok": True, "changed": False}
5. Drift Removal
   ├── unlink(primary, secondary) if drift exists
   └── unlink(secondary, primary) if drift exists
6. Reciprocal Link
   ├── link(primary, secondary, primary_reason_str)
   └── link(secondary, primary, secondary_reason_str)
7. Read-back Verification
   ├── Read relations on primary, verify desired link present
   └── Read relations on secondary, verify desired link present
8. Compensation (on any failure in steps 5-7)
   ├── Attempt to restore exact pre-call snapshot on both endpoints
   ├── If compensation succeeds:
   │   return {"ok": False, "changed": False, "state_restored": True, "error": ...}
   └── If compensation fails:
       return {"ok": False, "changed": True, "state_restored": False, "error": ..., "recovery": ...}
```

### Transaction Lifecycle for `remove_reciprocal_relation`

1. Validate URI syntax on both endpoints.
2. Snapshot existing links between primary and secondary.
3. If no links exist between the endpoints in either direction, return `{"ok": True, "changed": False}`.
4. Execute `unlink(primary, secondary)` and `unlink(secondary, primary)`.
5. Read-back verify that no links remain between the endpoints.
6. If unlinking or verification fails, compensate by re-linking the pre-call snapshot links.

---

## 5. Staged Decision Promotion (`promote_decision`)

Promotion is the process of translating an implemented decision into living-truth documents (`architecture/`, `domains/`, `invariants/`) and connecting them via reciprocal relations.

Staged promotion operates through discrete, agent-driven, verified mutations.

### Lifecycle Gating

- A decision begins at status `not-implemented` (via `write_decision`).
- When implementation code and tests are completed, the decision is transitioned to `implemented` via `mark_decision_implemented`.
- **`promote_decision` requires `dec_uri` status to be `implemented`**. Decisions in `not-implemented`, `promoted`, or `superseded` status are strictly rejected with an `INVALID_STATUS` error code.

### Action Matrix & Parameter Rules

`promote_decision(dec_uri, action, ...)` accepts exactly one of four actions:

| Action | Allowed Parameters | Forbidden Parameters | Purpose |
| :--- | :--- | :--- | :--- |
| `edit_l2` | `target`, `target_path`, `write_mode`, `content`, `section` (only if `write_mode="edit"`) | `primary`, `secondary`, `reason_pair`, `desc` | Write living-truth Markdown under `architecture/`, `domains/`, or `invariants/`. |
| `set_relation` | `primary`, `secondary`, `reason_pair`, `desc` | `target`, `target_path`, `write_mode`, `content`, `section` | Establish verified reciprocal relations between two endpoints. |
| `remove_relation` | `primary`, `secondary` | `target`, `target_path`, `write_mode`, `content`, `section`, `reason_pair`, `desc` | Remove reciprocal relations between two endpoints. |
| `finalize` | None (only `dec_uri` and `action`) | All optional parameters | Mark decision status as `promoted`. |

### Action Details

#### 1. `edit_l2`
- **Target Category**: Must be one of `architecture`, `domains`, or `invariants`.
- **Target Path**: Must be a relative path ending in `.md` (e.g., `auth/session-token.md`). Auto-generated index or summary files are explicitly rejected.
- **Write Modes**:
  - `create`: Target must not already exist. Writes content and verifies read-back. If verification fails, deletes the file as compensation.
  - `replace`: Target must already exist. Overwrites entire content and verifies read-back. If verification fails, restores original content.
  - `edit`: Target must already exist. Requires `section` parameter matching an existing markdown heading (`#`, `##`, `###`). Replaces the section content, preserving surrounding sections, and verifies read-back. If verification fails, restores original content.

#### 2. `set_relation`
- Requires `primary`, `secondary`, `reason_pair`, and `desc`.
- `reason_pair` must be one of:
  - `promoted_to/derived_from`
  - `composes/part_of`
  - `enforces/enforced_by`
  - `references/referenced_by`
- Enforces category topology and verifies reciprocal read-back with automatic snapshot compensation.

#### 3. `remove_relation`
- Requires `primary` and `secondary`.
- Removes links in both directions, verifies emptiness, with automatic snapshot compensation on failure.

#### 4. `finalize`
- Transitions the decision frontmatter status from `implemented` to `promoted`.
- Verifies read-back. If verification fails, restores status to `implemented`.

### Standardized Response Envelope

Every action returns a uniform dictionary shape:

```json
{
  "ok": true,
  "action": "edit_l2",
  "dec_uri": "viking://resources/project/decisions/DEC-0042.md",
  "changed": true,
  "result": {
    "uri": "viking://resources/project/architecture/storage.md",
    "target": "architecture",
    "target_path": "storage.md",
    "write_mode": "create"
  }
}
```

On failure with successful compensation:
```json
{
  "ok": false,
  "action": "edit_l2",
  "dec_uri": "viking://resources/project/decisions/DEC-0042.md",
  "changed": false,
  "state_restored": true,
  "error": {
    "code": "VERIFICATION_FAILURE",
    "message": "Read-back verification mismatch; restored original state"
  }
}
```

On failure where compensation also failed:
```json
{
  "ok": false,
  "action": "set_relation",
  "dec_uri": "viking://resources/project/decisions/DEC-0042.md",
  "changed": true,
  "state_restored": false,
  "error": {
    "code": "COMPENSATION_FAILURE",
    "message": "Linking failed and compensation failed"
  },
  "recovery": {
    "attempted_compensation": "restore_snapshot",
    "primary_failed": false,
    "secondary_failed": true,
    "current_state": { ... },
    "pre_call_state": { ... },
    "desired_state": { ... }
  }
}
```

---

## 6. First-Party Writers

First-party MCP tools establish relations or enforce boundaries according to their authoritative domains:

### `write_decision` (`braining_mcp`)
- **Signature**: `write_decision(context, problem, alternatives, decision, consequences, source_research=None)`
- Creates a new decision document at `viking://resources/project/decisions/DEC-NNNN.md` with status `not-implemented`.
- **`source_research`**: Optional list of dictionaries: `[{"uri": "viking://resources/project/research/ideas/auth.md", "desc": "initial design exploration"}]`.
- If provided, establishes reciprocal `produces/produced_from` relations sequentially.
- **Fault Handling**: If any relation linking fails, the newly created decision is preserved, and the error response details `linked_research` completed before the failure.

### `supersede_decision` (`braining_mcp`)
- **Signature**: `supersede_decision(old_dec_uri, context, problem, alternatives, decision, consequences, relation_desc)`
- Requires `relation_desc` string describing the supersession reason.
- Atomically creates the replacement decision (`not-implemented`), flips `old_dec_uri` status to `superseded`, and sets reciprocal `supersedes/superseded_by` relations using `relation_desc`.

### `write_audit` (`superpowers_mcp`)
- **Signature**: `write_audit(category, title, content)`
- Valid categories: `architecture`, `security`, `implementation`.
- Audits are point-in-time snapshot reports. They do not accept relations and establish no links. Recurring insights belong in agent pattern memory, not hand-linked relations.

---

## 7. Retrieval Layer (`retrieval_mcp`)

### `list_relations(uri)`
- Reads relations from OpenViking for the given project resource URI.
- Returns a flat list of relations under `"relations"`:
  ```json
  {
    "uri": "viking://resources/project/decisions/DEC-0012.md",
    "relations": [
      {
        "uri": "viking://resources/project/research/debates/consensus.md",
        "reason": "produced_from",
        "desc": "consensus algorithm evaluation"
      },
      {
        "uri": "viking://resources/project/domains/core/consensus.md",
        "reason": "promoted_to",
        "desc": "authoritative domain specification"
      }
    ]
  }
  ```
- Any malformed or legacy entries that do not match `<reason>, <desc>` syntax are returned with `"raw_reason"` and `"parse_error"` fields rather than crashing or being omitted.
