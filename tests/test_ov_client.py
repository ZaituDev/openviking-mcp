from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - normal runtime installs it
    import types

    class _RequestError(Exception):
        pass

    sys.modules["httpx"] = types.SimpleNamespace(
        Client=object,
        RequestError=_RequestError,
    )
    import httpx

from ov_client import OpenVikingClient, OpenVikingError  # noqa: E402


class MockResponse:
    def __init__(self, status_code: int, data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._data = data
        self.text = text or ("" if data is None else str(data))

    def json(self):
        if self._data is None:
            raise ValueError("No JSON")
        return self._data


class OpenVikingClientTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = OpenVikingClient.__new__(OpenVikingClient)
        self.mock_http = MagicMock()
        self.mock_http.base_url = "http://127.0.0.1:1933"
        self.client._client = self.mock_http

    def test_stat_resource_success(self) -> None:
        stat_result = {
            "name": "decision-001.md",
            "size": 1024,
            "mode": 420,
            "modTime": "2026-09-03T10:00:00Z",
            "isDir": False,
            "isLocked": False,
        }
        self.mock_http.request.return_value = MockResponse(
            200, {"ok": True, "result": stat_result}
        )

        uri = "viking://resources/project/decisions/decision-001.md"
        result = self.client.stat_resource(uri)

        self.assertEqual(result, stat_result)
        self.mock_http.request.assert_called_once_with(
            "GET", "/api/v1/fs/stat", params={"uri": uri}
        )

    def test_stat_resource_direct_dict_result(self) -> None:
        stat_result = {
            "name": "dir",
            "size": 0,
            "mode": 493,
            "modTime": "2026-09-03T10:00:00Z",
            "isDir": True,
            "isLocked": False,
        }
        self.mock_http.request.return_value = MockResponse(200, stat_result)

        uri = "viking://resources/project/decisions"
        result = self.client.stat_resource(uri)
        self.assertEqual(result, stat_result)

    def test_stat_resource_error_raises_openviking_error(self) -> None:
        self.mock_http.request.return_value = MockResponse(
            404,
            {
                "ok": False,
                "status": "error",
                "error": {"code": "NOT_FOUND", "message": "resource not found"},
            },
        )
        with self.assertRaises(OpenVikingError) as ctx:
            self.client.stat_resource("viking://resources/project/decisions/missing.md")
        self.assertEqual(ctx.exception.code, "NOT_FOUND")
        self.assertIn("resource not found", str(ctx.exception))

    def test_unlink_success(self) -> None:
        self.mock_http.request.return_value = MockResponse(
            200, {"ok": True, "result": {"ok": True}}
        )

        from_uri = "viking://resources/project/research/r1.md"
        to_uri = "viking://resources/project/decisions/d1.md"
        result = self.client.unlink(from_uri, to_uri)

        self.assertEqual(result, {"ok": True})
        self.mock_http.request.assert_called_once_with(
            "DELETE",
            "/api/v1/relations/link",
            json={"from_uri": from_uri, "to_uri": to_uri},
        )

    def test_unlink_error_raises_openviking_error(self) -> None:
        self.mock_http.request.return_value = MockResponse(
            400,
            {
                "status": "error",
                "error": {"code": "INVALID_ARGUMENT", "message": "link does not exist"},
            },
        )
        with self.assertRaises(OpenVikingError) as ctx:
            self.client.unlink(
                "viking://resources/project/research/r1.md",
                "viking://resources/project/decisions/d1.md",
            )
        self.assertEqual(ctx.exception.code, "INVALID_ARGUMENT")
        self.assertIn("link does not exist", str(ctx.exception))

    def test_delete_resource_success(self) -> None:
        self.mock_http.request.return_value = MockResponse(
            200, {"ok": True, "result": {"deleted": True}}
        )

        uri = "viking://resources/project/decisions/staged.md"
        result = self.client.delete_resource(uri)

        self.assertEqual(result, {"deleted": True})
        self.mock_http.request.assert_called_once_with(
            "DELETE", "/api/v1/fs", params={"uri": uri}
        )

    def test_delete_resource_error_raises_openviking_error(self) -> None:
        self.mock_http.request.return_value = MockResponse(
            404,
            {
                "ok": False,
                "error": {"code": "NOT_FOUND", "message": "file not found"},
            },
        )
        with self.assertRaises(OpenVikingError) as ctx:
            self.client.delete_resource("viking://resources/project/decisions/missing.md")
        self.assertEqual(ctx.exception.code, "NOT_FOUND")
        self.assertIn("file not found", str(ctx.exception))

    def test_exists_returns_true_when_stat_succeeds(self) -> None:
        self.mock_http.request.return_value = MockResponse(
            200, {"result": {"name": "d1.md", "isDir": False}}
        )
        self.assertTrue(self.client.exists("viking://resources/project/decisions/d1.md"))

    def test_exists_returns_false_when_stat_fails(self) -> None:
        self.mock_http.request.return_value = MockResponse(
            404, {"error": {"code": "NOT_FOUND", "message": "not found"}}
        )
        self.assertFalse(self.client.exists("viking://resources/project/decisions/missing.md"))

    def test_exists_is_file_check(self) -> None:
        # Resource is a directory
        self.mock_http.request.return_value = MockResponse(
            200, {"result": {"name": "decisions", "isDir": True}}
        )
        uri = "viking://resources/project/decisions"
        self.assertTrue(self.client.exists(uri, is_file=False))
        self.assertFalse(self.client.exists(uri, is_file=True))

        # Resource is a file
        self.mock_http.request.return_value = MockResponse(
            200, {"result": {"name": "decisions.md", "isDir": False}}
        )
        file_uri = "viking://resources/project/decisions.md"
        self.assertTrue(self.client.exists(file_uri, is_file=True))

    def test_request_network_error_raises_openviking_error(self) -> None:
        self.mock_http.request.side_effect = httpx.RequestError("connection refused")
        with self.assertRaises(OpenVikingError) as ctx:
            self.client.stat_resource("viking://resources/project/x.md")
        self.assertIn("Could not reach OpenViking server", str(ctx.exception))

    def test_request_non_json_response_raises_openviking_error(self) -> None:
        self.mock_http.request.return_value = MockResponse(502, None, text="Bad Gateway")
        with self.assertRaises(OpenVikingError) as ctx:
            self.client.stat_resource("viking://resources/project/x.md")
        self.assertIn("OpenViking returned a non-JSON response", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
