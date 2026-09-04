# devClan OpenViking MCP Servers

Three custom MCP servers:

- `braining_mcp` — braining's write contract (research/, decisions/)
- `superpowers_mcp` — superpowers' write contract (architecture/,
  domains/, invariants/, audits/)
- `retrieval_mcp` — shared, read-only discovery/verification layer used
  by both. Owns no write ceiling.

Write enforcement is by tool-schema absence, not runtime checks — each
write-contract server only exposes the tools its mode is allowed to use.
Read scoping in `retrieval_mcp` is enforced at runtime, via
`shared/uri_guard.py`, since every retrieval tool takes an agent-supplied
URI and that URI must be checked before use — schema absence alone can't
constrain the *value* of a string argument the way it can constrain which
tools exist.

## Setup

```bash
cd openviking-mcp
uv pip install -r requirements.txt
```

Requires `openviking-server` running (see openviking_lifecycle.zsh). Claude
Code launches each configured MCP as a stdio subprocess; the MCP then talks to
OpenViking over HTTP at OPENVIKING_SERVER_URL (default
http://127.0.0.1:1933). Those are two different transport legs.

## Wiring into Claude Code

Reference each server from the corresponding .claude/agents/*.md file's
`mcpServers` field, or from a project-level .mcp.json. Tool names in agent
frontmatter follow `mcp:<server-name>:<tool-name>`, e.g.
`mcp:braining-mcp:write_decision`.

For exact reasoning-search and usage-log routing after `/clear`, interactive
`/resume`, and from subagents, merge the PreToolUse example in
`adapters/claude_code/hooks.example.json` into your own Claude Code settings.
It does not modify the official OpenViking memory plugin. See the adapter
README for the fresh/CLI-resume fallback behavior and parent-session policy.

FastMCP uses strict tool schemas (`additionalProperties: false`), so both
session-bound tools declare an optional `runtime_session_id`. This field is
adapter-owned, not agent-owned: agents omit it and the PreToolUse hook
overwrites it with the exact current session before every call.

## Environment variables

- OPENVIKING_SERVER_URL   (default: http://127.0.0.1:1933)
- OPENVIKING_API_KEY / OPENVIKING_BEARER_TOKEN (unset in dev mode)
- OPENVIKING_AGENT_ID     (default: devclan-mcp)
- OPENVIKING_ACCOUNT      (optional; send the same value as the memory plugin)
- OPENVIKING_USER         (optional; send the same value as the memory plugin)
- OPENVIKING_SESSION_ID   (optional exact-ID launcher fallback; never "latest")

## Verified against

Real OpenAPI spec (openviking_openapi.json), not guessed endpoints. Key
corrections made during build: content read/write live at
/api/v1/content/{read,write}, not /api/v1/fs/{read,write}; LinkRequest
uses `to_uris`, not `uris`.

## Known gaps / next steps

- Response body shapes for content/write, fs/mkdir, search/find,
  relations/link, and sessions POST were not fully typed in the OpenAPI
  spec (no $ref on 200 responses). Client code defensively handles both
  {"result": {...}} and flat dict shapes, but this should be verified
  against a live server call before heavy use.
- OpenCode session-bound routing remains an explicit adapter boundary. The
  portable MCP core is compatible, but the adapter must obtain the official
  OpenViking plugin's mapped session ID rather than inventing a second ID. See
  `adapters/opencode/README.md`.
- In authenticated/multi-tenant deployments, the MCP process and official
  memory plugin must receive the same URL, API key, account, and user. The
  supplied local dev configuration is anonymous; this project does not guess
  identity values from plugin-owned configuration files.

## Reciprocal Relations & Storage Format

Relations form a verified bidirectional graph connecting project knowledge resources using native OpenViking endpoints (`POST /api/v1/relations/link` and `DELETE /api/v1/relations/link`).

Relations are established and maintained in reciprocal pairs between concrete `.md` files.

### Closed Vocabulary (6 Canonical Pairs)

| Reason Pair | Directional Pair | Applicable Subtrees |
| :--- | :--- | :--- |
| `produces/produced_from` | `produces` ⇄ `produced_from` | `research/` ⇄ `decisions/` |
| `supersedes/superseded_by` | `supersedes` ⇄ `superseded_by` | `decisions/` ⇄ `decisions/` |
| `promoted_to/derived_from` | `promoted_to` ⇄ `derived_from` | `decisions/` ⇄ `architecture/`, `domains/`, or `invariants/` |
| `composes/part_of` | `composes` ⇄ `part_of` | `architecture/` ⇄ `domains/` |
| `enforces/enforced_by` | `enforces` ⇄ `enforced_by` | `invariants/` ⇄ `domains/` |
| `references/referenced_by` | `references` ⇄ `referenced_by` | Any concrete resource ⇄ Any concrete resource |

### Storage Format & Parsing

Native relation entries store a directional reason and description separated by a comma:

```text
<directional_reason>, <trimmed description>
```

- Endpoint A -> B: stored reason is `primary_reason, <desc>`
- Endpoint B -> A: stored reason is `secondary_reason, <desc>`

Parsing splits once on the first comma (`split(",", 1)`), preserving any subsequent commas in the description.

### Transactions & Exact-State Compensation

Relation operations take a pre-call snapshot of relations between endpoints, apply mutations, and verify read-backs. If linking or verification fails at any point, automatic compensation restores the exact pre-call snapshot state.

---

## Tool Reference

### superpowers_mcp

#### `promote_decision`

Execute a staged promotion action authorized by an implemented decision. Only decisions with status `implemented` may be promoted; decisions in other statuses are rejected.

**Signature:**
```python
promote_decision(
    dec_uri: str,
    action: str,  # "edit_l2" | "set_relation" | "remove_relation" | "finalize"
    target: str | None = None,  # "architecture" | "domains" | "invariants"
    target_path: str | None = None,  # relative path ending in .md
    write_mode: str | None = None,  # "create" | "replace" | "edit"
    content: str | None = None,
    section: str | None = None,  # required when write_mode="edit"
    primary: str | None = None,
    secondary: str | None = None,
    reason_pair: str | None = None,
    desc: str | None = None,
) -> dict[str, Any]
```

**Actions:**
- `edit_l2`: Create or update living-truth documentation under `architecture/`, `domains/`, or `invariants/`.
- `set_relation`: Create verified reciprocal relations between two endpoints.
- `remove_relation`: Remove reciprocal relations between two endpoints.
- `finalize`: Mark the decision frontmatter status as `promoted` after all edits and relations have been verified.

**Example — Edit Living Truth:**
```python
promote_decision(
    dec_uri="viking://resources/project/decisions/DEC-0024.md",
    action="edit_l2",
    target="domains",
    target_path="governance/advisors.md",
    write_mode="create",
    content="# Advisors Domain\n\nAuthoritative domain specifications...",
)
```

**Example — Set Reciprocal Relation:**
```python
promote_decision(
    dec_uri="viking://resources/project/decisions/DEC-0024.md",
    action="set_relation",
    primary="viking://resources/project/decisions/DEC-0024.md",
    secondary="viking://resources/project/domains/governance/advisors.md",
    reason_pair="promoted_to/derived_from",
    desc="governance advisor rules derived from DEC-0024",
)
```

**Example — Remove Reciprocal Relation:**
```python
promote_decision(
    dec_uri="viking://resources/project/decisions/DEC-0024.md",
    action="remove_relation",
    primary="viking://resources/project/decisions/DEC-0024.md",
    secondary="viking://resources/project/domains/governance/advisors.md",
)
```

**Example — Finalize Promotion:**
```python
promote_decision(
    dec_uri="viking://resources/project/decisions/DEC-0024.md",
    action="finalize",
)
```

#### `write_audit`

Write a point-in-time audit report to `audits/{category}/{slug}.md`. Audits are single-snapshot reports with no relations.

**Signature:**
```python
write_audit(
    category: str,  # "architecture" | "security" | "implementation"
    title: str,
    content: str,
) -> dict[str, Any]
```

**Example:**
```python
write_audit(
    category="security",
    title="Session Token Entropy Review",
    content="Audit findings on session token generation...",
)
```

#### `query_decisions`

Filter decisions by lifecycle status (`"not-implemented"`, `"implemented"`, `"promoted"`, `"superseded"`, or `"all"`).

#### `mark_decision_implemented`

Transitions a decision's status from `not-implemented` to `implemented` after implementation is completed and verified.

#### `log_context_used`

Records decisions/invariants that materially influenced work into the current session. Callers omit `runtime_session_id`, which is reserved for the client integration.

---

### braining_mcp

#### `write_decision`

Create a new decision record at `decisions/DEC-NNNN.md` with status `not-implemented`.

**Signature:**
```python
write_decision(
    context: str,
    problem: str,
    alternatives: str,
    decision: str,
    consequences: str,
    source_research: list[dict[str, str]] | None = None,
) -> dict[str, Any]
```

If `source_research` is provided, establishes reciprocal `produces/produced_from` relations between each research resource and the new decision.

**Example:**
```python
write_decision(
    context="Need robust multi-agent consensus...",
    problem="Advisory decisions lacked clear escalation paths...",
    alternatives="1. Single leader\n2. Quorum-based voting",
    decision="Adopt quorum-based voting with 2/3 threshold.",
    consequences="Increases consensus latency slightly but prevents deadlock.",
    source_research=[
        {
            "uri": "viking://resources/project/research/debates/consensus.md",
            "desc": "consensus protocol exploration",
        }
    ],
)
```

#### `supersede_decision`

Retire an existing decision and create its replacement atomically.

**Signature:**
```python
supersede_decision(
    old_dec_uri: str,
    context: str,
    problem: str,
    alternatives: str,
    decision: str,
    consequences: str,
    relation_desc: str,
) -> dict[str, Any]
```

Flips `old_dec_uri` status to `superseded`, creates the new decision with status `not-implemented`, and links them via reciprocal `supersedes/superseded_by` relations using `relation_desc`.

**Example:**
```python
supersede_decision(
    old_dec_uri="viking://resources/project/decisions/DEC-0010.md",
    context="Scaling requires revised consensus parameters...",
    problem="Static quorum size fails under dynamic cluster topologies...",
    alternatives="Dynamic quorum adjustment vs raft consensus.",
    decision="Adopt dynamic quorum sizing.",
    consequences="Supports elastically sized agent clusters.",
    relation_desc="replaces static quorum with dynamic cluster topology sizing",
)
```

#### `search_decisions`

Search existing decisions and invariants before authoring a new decision to avoid duplication or contradiction.

#### `write_research`

Write disposable, exploratory research content to `research/{ideas,debates,experiments}/`.

---

### retrieval_mcp

#### `list_relations`

Traverse graph relations for a given resource URI. Returns a flat list of relations under `"relations"`.

**Signature:**
```python
list_relations(uri: str) -> dict[str, Any]
```

**Response Format:**
```json
{
  "uri": "viking://resources/project/decisions/DEC-0024.md",
  "relations": [
    {
      "uri": "viking://resources/project/research/debates/advisors.md",
      "reason": "produced_from",
      "desc": "initial consensus exploration"
    },
    {
      "uri": "viking://resources/project/domains/governance/advisors.md",
      "reason": "promoted_to",
      "desc": "authoritative domain rule"
    }
  ]
}
```

Malformed or legacy entries that do not match the expected `<reason>, <desc>` format are preserved in the flat list with `raw_reason` and `parse_error` fields.

#### `read_project_resource`

Read a specific project resource at detail level `L0` (abstract), `L1` (overview), or `L2` (full content).

#### `list_project_resources`

Enumerate the project resources tree deterministically via `ls()`.

#### `search_project_context`

Perform semantic discovery across project knowledge via `find()` (stateless `flash` mode) or `search()` (intent-expanded `reasoning` mode). Callers omit `runtime_session_id`, which is reserved for the client integration.
