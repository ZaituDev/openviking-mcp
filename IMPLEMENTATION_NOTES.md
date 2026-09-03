# Session integration assumptions and corrections

## Confirmed assumptions

- Claude Code starts these MCP servers with `command` and `args`, so the
  Claude-to-MCP transport is stdio. `OPENVIKING_SERVER_URL` controls the
  separate MCP-to-OpenViking HTTP connection.
- The attached OpenViking Claude plugin derives the parent OpenViking session
  as `cc-<Claude session_id>` and preserves the Claude ID verbatim.
- The plugin may not create that OpenViking session until its first Stop
  capture. Session-bound MCP tools must therefore ensure the same deterministic
  ID exists before search or `used()`.
- Parent routing is intentional for subagent MCP activity. The Claude adapter
  uses the parent hook `session_id` and ignores `agent_id`.
- A resource counts as used only when it materially influences work. A read by
  itself does not qualify.
- The supplied setup is a local anonymous deployment. For formal multi-tenant
  auth, URL/key/account/user equality is an operator precondition; the MCP does
  not parse or assume values from a plugin-owned config file.

## Corrections to earlier examples

- Reasoning search is not gated on five prompts. Intent analysis and query
  expansion can help immediately; captured conversation history begins adding
  value after a completed turn and often matters more mid-session.
- `log_context_used` has no warm-up delay. Log qualifying influence immediately,
  including on the first prompt.
- Passing a model-selected session ID is unsafe and unnecessary. FastMCP's
  strict schema validation does not preserve undeclared arguments, so the
  session-bound tools expose an optional `runtime_session_id` property. It is
  integration-owned: the client hook overwrites it on every call, and the
  agent is instructed to omit it. The MCP refuses to guess the latest session.
- Hooks are a thin Claude-specific adapter, not a dependency of the portable
  MCP core. OpenCode can use the same core once its adapter can obtain the
  official integration's OpenViking session mapping.

## Deliberate boundary

This project does not modify or take ownership of the official OpenViking
Claude/OpenCode memory plugins. It only ensures or uses the exact session ID
those integrations own; capture, commit, extraction, and resume context remain
their responsibility.
