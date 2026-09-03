from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

from runtime_session import (  # noqa: E402
    RuntimeSessionError,
    claude_openviking_session_id,
    resolve_runtime_session_id,
)


class RuntimeSessionTests(unittest.TestCase):
    def test_matches_official_claude_parent_mapping(self) -> None:
        self.assertEqual(
            claude_openviking_session_id("1234-abcd"), "cc-1234-abcd"
        )

    def test_call_local_adapter_value_has_highest_precedence(self) -> None:
        env = {
            "OPENVIKING_SESSION_ID": "explicit-launcher",
            "CLAUDE_CODE_SESSION_ID": "stale-claude-id",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                resolve_runtime_session_id("cc-current-hook-id"),
                "cc-current-hook-id",
            )

    def test_launcher_override_precedes_claude_environment(self) -> None:
        env = {
            "OPENVIKING_SESSION_ID": "mapped-opencode-session",
            "CLAUDE_CODE_SESSION_ID": "claude-id",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                resolve_runtime_session_id(), "mapped-opencode-session"
            )

    def test_claude_environment_is_safe_process_launch_fallback(self) -> None:
        with patch.dict(
            os.environ, {"CLAUDE_CODE_SESSION_ID": "fresh-or-resumed"}, clear=True
        ):
            self.assertEqual(
                resolve_runtime_session_id(), "cc-fresh-or-resumed"
            )

    def test_missing_identity_fails_instead_of_guessing_latest(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeSessionError, "Refusing to guess"):
                resolve_runtime_session_id()

    def test_surrounding_whitespace_is_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeSessionError, "whitespace"):
                resolve_runtime_session_id(" cc-wrong ")


if __name__ == "__main__":
    unittest.main()
