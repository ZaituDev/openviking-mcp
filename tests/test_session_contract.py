from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - normal runtime installs it
    import types

    sys.modules["httpx"] = types.SimpleNamespace(
        Client=object, RequestError=RuntimeError
    )

from ov_client import OpenVikingClient, OpenVikingError  # noqa: E402


def function_node(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name} not found in {path}")


class SessionContractTests(unittest.TestCase):
    def test_session_field_is_optional_and_adapter_owned(self) -> None:
        retrieval = function_node(
            ROOT / "retrieval_mcp" / "server.py", "search_project_context"
        )
        logging = function_node(
            ROOT / "superpowers_mcp" / "server.py", "log_context_used"
        )
        for node in (retrieval, logging):
            args = [arg.arg for arg in node.args.args]
            self.assertNotIn("session_id", args)
            self.assertIn("runtime_session_id", args)
            self.assertNotIn("ctx", args)
            runtime_index = args.index("runtime_session_id")
            first_default = len(args) - len(node.args.defaults)
            default = node.args.defaults[runtime_index - first_default]
            self.assertIsInstance(default, ast.Constant)
            self.assertIsNone(default.value)
            docstring = ast.get_docstring(node) or ""
            self.assertIn("reserved for the client integration", docstring)

    def test_ensure_session_uses_exact_encoded_id_and_auto_create(self) -> None:
        client = OpenVikingClient.__new__(OpenVikingClient)
        calls = []

        def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {"result": {"session_id": "cc-a/b"}}

        client._request = request
        result = client.ensure_session("cc-a/b")
        self.assertEqual(result["session_id"], "cc-a/b")
        self.assertEqual(calls[0][0:2], ("GET", "/api/v1/sessions/cc-a%2Fb"))
        self.assertEqual(calls[0][2]["params"], {"auto_create": "true"})

    def test_used_endpoint_encodes_session_id(self) -> None:
        client = OpenVikingClient.__new__(OpenVikingClient)
        calls = []

        def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {"result": {"ok": True}}

        client._request = request
        client.session_used("cc-a/b", context_uris=["viking://resources/x"])
        self.assertEqual(calls[0][1], "/api/v1/sessions/cc-a%2Fb/used")

    def test_official_status_error_envelope_is_not_treated_as_success(self) -> None:
        class Response:
            status_code = 200
            text = "status error"

            @staticmethod
            def json():
                return {
                    "status": "error",
                    "error": {"code": "NOT_FOUND", "message": "missing"},
                }

        class HttpClient:
            base_url = "http://127.0.0.1:1933"

            @staticmethod
            def request(*args, **kwargs):
                return Response()

        client = OpenVikingClient.__new__(OpenVikingClient)
        client._client = HttpClient()
        with self.assertRaisesRegex(OpenVikingError, "missing") as raised:
            client._request("GET", "/api/v1/sessions/cc-test")
        self.assertEqual(raised.exception.code, "NOT_FOUND")

    def test_example_hook_targets_only_session_bound_tools(self) -> None:
        config = json.loads(
            (ROOT / "adapters" / "claude_code" / "hooks.example.json").read_text(
                encoding="utf-8"
            )
        )
        matcher = config["hooks"]["PreToolUse"][0]["matcher"]
        self.assertIn("search_project_context", matcher)
        self.assertIn("log_context_used", matcher)


if __name__ == "__main__":
    unittest.main()
