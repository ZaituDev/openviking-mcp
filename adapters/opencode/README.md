# OpenCode compatibility boundary

The MCP core remains portable to OpenCode: it still runs as a normal stdio MCP
server and uses HTTP only for MCP-to-OpenViking calls. Flash retrieval and all
non-session-bound tools need no adapter.

Reasoning retrieval and `log_context_used` require an exact OpenViking session
ID. OpenCode does not currently put its session ID into MCP tool calls by
default. Its plugin lifecycle exposes a per-call `sessionID`, but the official
OpenViking OpenCode integration maps that ID to a separate OpenViking session.
Therefore an adapter must obtain the integration's *mapped OpenViking ID* and
inject it as the integration-owned `runtime_session_id` call field (for example in
`tool.execute.before`). The optional field is declared in the session-bound
tool schemas because FastMCP will not preserve undeclared arguments. The
adapter must not assume that `oc-<OpenCode sessionID>` is the shared session.

No speculative OpenCode adapter is shipped here because injecting the raw
OpenCode ID would create a second session rather than join the memory plugin's
session. If the official integration exposes its mapping, only this thin
adapter changes; `shared/runtime_session.py` and both MCP servers stay the same.
