# Claude Code session adapter

This adapter belongs in your own Claude Code configuration. It does not modify
the official OpenViking memory plugin.

Merge `hooks.example.json`'s `PreToolUse` entry into the applicable Claude Code
settings. The example command already uses the MCP root from the supplied
configuration (`/home/hmmm/projects/openviking-mcp`); update it if the checkout
moves.

Why a per-call hook is needed:

- A fresh `claude` or `claude --resume` supplies `CLAUDE_CODE_SESSION_ID` to a
  newly launched stdio MCP process, so the environment fallback is exact.
- `/clear` and interactive `/resume` can switch the Claude session while the
  stdio MCP subprocess remains alive. Its launch-time environment is then
  stale, but `PreToolUse` receives the current `session_id` and replaces it.
- Claude's hook payload retains the parent `session_id` during subagent tool
  calls. The adapter intentionally ignores `agent_id`, so MCP usage and
  reasoning retrieval attach to the parent session as required.
- Separate Claude processes have separate hook calls and IDs; no shared
  "current" file and no latest-session lookup is used.

The derived ID is exactly `cc-<Claude session_id>`, matching the attached
OpenViking Claude plugin's current implementation. Before a session-bound call,
the MCP asks OpenViking to auto-create that exact ID if needed. This closes the
first-turn race where the memory plugin has not yet run its first Stop capture.

FastMCP rejects or strips undeclared tool arguments before the Python handler,
so `runtime_session_id` must be an optional property in both session-bound tool
schemas. It is integration-owned: agents should omit it, and this hook
authoritatively overwrites any existing value before execution.
