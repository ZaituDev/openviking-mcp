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
pip install -r requirements.txt --break-system-packages
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

## Relations: `link()` / `relations()` — native endpoints, confirmed working

An earlier build of OpenViking had `link` and `relations` confirmed
non-functional 100% of the time (a `503 UNAVAILABLE: Storage backend
unavailable ... Not a directory (os error 20)` error, reproduced via both
this client and the native `ov link` CLI). A self-owned fallback
(`relations.jsonl`/`.md`, written via `content/write`) worked around this
at the time.

That upstream bug is now fixed. Verified via live smoke test — `link()`
and a fresh `GET /api/v1/relations` both round-tripped correctly against
real project URIs (see `tests/relations_test.py`) — before the fallback
was removed. There is no self-owned relations store in this codebase
anymore; `ov_client.py`'s `link()` and `get_relations()` are the only
mechanism, calling the native endpoints directly.

`get_relations(uri)` returns the confirmed live shape: a flat list of
`{"uri": ..., "reason": ...}` entries. `reason` is a free-text field —
this codebase treats it as a small closed vocabulary
(`concluded_from`, `promoted_to` / `implements`, `superseded_by`,
`supersedes`) enforced at write time by each tool's `link()` call, not
by the server. `retrieval-mcp`'s `list_relations` tool groups results by
`reason` for readability; any reason value outside that vocabulary still
passes through under its own key rather than being dropped.

Every tool that links something (`write_decision`'s optional
research-linking, `supersede_decision`, `promote_decision`, `write_audit`)
calls `client.link()` directly, and tolerates a link failure without
failing the whole tool call — the underlying content write (the decision,
the promotion, the audit) is already durable by the time linking happens,
so a link error is surfaced in the response rather than treated as if the
whole operation failed.
