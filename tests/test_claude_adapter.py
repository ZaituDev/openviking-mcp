from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "adapters" / "claude_code" / "inject_runtime_session.py"

spec = importlib.util.spec_from_file_location("inject_runtime_session", SCRIPT)
assert spec is not None and spec.loader is not None
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class ClaudeAdapterTests(unittest.TestCase):
    def test_injects_parent_session_and_ignores_subagent_id(self) -> None:
        output = adapter.build_hook_output(
            {
                "session_id": "parent-uuid",
                "agent_id": "subagent-uuid",
                "tool_input": {"query": "invariant", "mode": "reasoning"},
            }
        )
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["runtime_session_id"], "cc-parent-uuid")
        self.assertEqual(updated["query"], "invariant")

    def test_hook_value_overwrites_model_or_stale_input(self) -> None:
        output = adapter.build_hook_output(
            {
                "session_id": "current",
                "tool_input": {"runtime_session_id": "cc-stale"},
            }
        )
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["runtime_session_id"], "cc-current")

    def test_missing_session_is_noop(self) -> None:
        self.assertEqual(adapter.build_hook_output({"tool_input": {}}), {})

    def test_cli_emits_only_valid_hook_json(self) -> None:
        payload = {"session_id": "abc", "tool_input": {"context_uris": ["x"]}}
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(completed.stderr, "")
        self.assertEqual(
            json.loads(completed.stdout)["hookSpecificOutput"]["updatedInput"][
                "runtime_session_id"
            ],
            "cc-abc",
        )


if __name__ == "__main__":
    unittest.main()
