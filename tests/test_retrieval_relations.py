from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "retrieval_mcp"))

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    import types

    class _RequestError(Exception):
        pass

    sys.modules["httpx"] = types.SimpleNamespace(
        Client=object,
        RequestError=_RequestError,
    )

import retrieval_mcp.server as retrieval_server
from ov_client import OpenVikingError


class TestRetrievalRelations(unittest.TestCase):
    """Test suite for retrieval_mcp list_relations tool."""

    def test_valid_relations_parsed_into_flat_list(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0001.md"
        target_uri = "viking://resources/project/decisions/DEC-0002.md"

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = [
                {"uri": target_uri, "reason": "supersedes, replaces v1 architecture"}
            ]

            res = retrieval_server.list_relations(source_uri)

        mock_client.get_relations.assert_called_once_with(source_uri)
        self.assertEqual(res["uri"], source_uri)
        self.assertIsInstance(res["relations"], list)
        self.assertEqual(len(res["relations"]), 1)
        self.assertEqual(
            res["relations"][0],
            {
                "uri": target_uri,
                "reason": "supersedes",
                "desc": "replaces v1 architecture",
            },
        )

    def test_valid_relations_preserves_commas_in_desc(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0001.md"
        target_uri = "viking://resources/project/decisions/DEC-0002.md"
        complex_desc = "replaces v1, adds caching, improves throughput, and updates docs"

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = [
                {"uri": target_uri, "reason": f"supersedes, {complex_desc}"}
            ]

            res = retrieval_server.list_relations(source_uri)

        self.assertEqual(len(res["relations"]), 1)
        self.assertEqual(
            res["relations"][0],
            {
                "uri": target_uri,
                "reason": "supersedes",
                "desc": complex_desc,
            },
        )

    def test_multiple_valid_relations_flat_order(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0024.md"
        raw_relations = [
            {
                "uri": "viking://resources/project/research/debates/advisors.md",
                "reason": "produced_from, initial consensus exploration",
            },
            {
                "uri": "viking://resources/project/domains/governance/advisors.md",
                "reason": "promoted_to, authoritative domain rule",
            },
            {
                "uri": "viking://resources/project/decisions/DEC-0031.md",
                "reason": "superseded_by, replaced by unified governance framework",
            },
        ]

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = raw_relations

            res = retrieval_server.list_relations(source_uri)

        self.assertEqual(res["uri"], source_uri)
        self.assertIsInstance(res["relations"], list)
        self.assertEqual(len(res["relations"]), 3)
        self.assertEqual(
            res["relations"],
            [
                {
                    "uri": "viking://resources/project/research/debates/advisors.md",
                    "reason": "produced_from",
                    "desc": "initial consensus exploration",
                },
                {
                    "uri": "viking://resources/project/domains/governance/advisors.md",
                    "reason": "promoted_to",
                    "desc": "authoritative domain rule",
                },
                {
                    "uri": "viking://resources/project/decisions/DEC-0031.md",
                    "reason": "superseded_by",
                    "desc": "replaced by unified governance framework",
                },
            ],
        )

    def test_malformed_missing_delimiter_legacy_reason(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0024.md"
        target_uri = "viking://resources/project/research/advisors.md"

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = [
                {"uri": target_uri, "reason": "concluded_from"}
            ]

            res = retrieval_server.list_relations(source_uri)

        self.assertEqual(len(res["relations"]), 1)
        self.assertEqual(
            res["relations"][0],
            {
                "uri": target_uri,
                "raw_reason": "concluded_from",
                "parse_error": "MISSING_DELIMITER",
            },
        )

    def test_malformed_empty_field(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0024.md"
        raw_relations = [
            {"uri": "viking://resources/project/architecture/arch.md", "reason": "promoted_to, "},
            {"uri": "viking://resources/project/domains/dom.md", "reason": ", missing reason"},
        ]

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = raw_relations

            res = retrieval_server.list_relations(source_uri)

        self.assertEqual(len(res["relations"]), 2)
        self.assertEqual(
            res["relations"][0],
            {
                "uri": "viking://resources/project/architecture/arch.md",
                "raw_reason": "promoted_to, ",
                "parse_error": "EMPTY_FIELD",
            },
        )
        self.assertEqual(
            res["relations"][1],
            {
                "uri": "viking://resources/project/domains/dom.md",
                "raw_reason": ", missing reason",
                "parse_error": "EMPTY_FIELD",
            },
        )

    def test_malformed_unknown_reason(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0024.md"
        target_uri = "viking://resources/project/decisions/DEC-0099.md"

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = [
                {"uri": target_uri, "reason": "custom_link_reason, unknown to vocabulary"}
            ]

            res = retrieval_server.list_relations(source_uri)

        self.assertEqual(len(res["relations"]), 1)
        self.assertEqual(
            res["relations"][0],
            {
                "uri": target_uri,
                "raw_reason": "custom_link_reason, unknown to vocabulary",
                "parse_error": "UNKNOWN_REASON",
            },
        )

    def test_malformed_control_characters(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0024.md"
        target_uri = "viking://resources/project/decisions/DEC-0099.md"

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = [
                {"uri": target_uri, "reason": "supersedes\n, multiline reason"}
            ]

            res = retrieval_server.list_relations(source_uri)

        self.assertEqual(len(res["relations"]), 1)
        self.assertEqual(
            res["relations"][0],
            {
                "uri": target_uri,
                "raw_reason": "supersedes\n, multiline reason",
                "parse_error": "INVALID_CONTROL_CHARS",
            },
        )

    def test_mixed_valid_and_malformed_entries(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0024.md"
        raw_relations = [
            {
                "uri": "viking://resources/project/decisions/DEC-0001.md",
                "reason": "supersedes, valid description",
            },
            {
                "uri": "viking://resources/project/research/legacy.md",
                "reason": "legacy_single_token",
            },
            {
                "uri": "viking://resources/project/domains/dom.md",
                "reason": "promoted_to, description with, comma, details",
            },
            {
                "uri": "viking://resources/project/unknown.md",
                "reason": "unrecognized, token",
            },
        ]

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = raw_relations

            res = retrieval_server.list_relations(source_uri)

        self.assertEqual(len(res["relations"]), 4)
        self.assertEqual(
            res["relations"][0],
            {
                "uri": "viking://resources/project/decisions/DEC-0001.md",
                "reason": "supersedes",
                "desc": "valid description",
            },
        )
        self.assertEqual(
            res["relations"][1],
            {
                "uri": "viking://resources/project/research/legacy.md",
                "raw_reason": "legacy_single_token",
                "parse_error": "MISSING_DELIMITER",
            },
        )
        self.assertEqual(
            res["relations"][2],
            {
                "uri": "viking://resources/project/domains/dom.md",
                "reason": "promoted_to",
                "desc": "description with, comma, details",
            },
        )
        self.assertEqual(
            res["relations"][3],
            {
                "uri": "viking://resources/project/unknown.md",
                "raw_reason": "unrecognized, token",
                "parse_error": "UNKNOWN_REASON",
            },
        )

    def test_ungrouped_flat_schema(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0024.md"
        raw_relations = [
            {
                "uri": "viking://resources/project/decisions/DEC-0001.md",
                "reason": "supersedes, reason one",
            },
            {
                "uri": "viking://resources/project/decisions/DEC-0002.md",
                "reason": "supersedes, reason two",
            },
        ]

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = raw_relations

            res = retrieval_server.list_relations(source_uri)

        # Ensure top level return is {"uri": ..., "relations": [...]}
        self.assertCountEqual(list(res.keys()), ["uri", "relations"])
        self.assertIsInstance(res["relations"], list)
        self.assertFalse(isinstance(res["relations"], dict))
        # Even if two entries share the same reason ("supersedes"), they are NOT grouped
        self.assertEqual(len(res["relations"]), 2)
        self.assertEqual(res["relations"][0]["reason"], "supersedes")
        self.assertEqual(res["relations"][1]["reason"], "supersedes")

    def test_empty_relations_returns_empty_list(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0024.md"

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = []

            res = retrieval_server.list_relations(source_uri)

        self.assertEqual(res, {"uri": source_uri, "relations": []})

    def test_invalid_uri_scope_rejected(self) -> None:
        invalid_uris = [
            "viking://user/preferences.json",
            "viking://agent/state.json",
            "https://example.com/decision.md",
            "viking://other/path.md",
            "",
        ]

        for invalid_uri in invalid_uris:
            with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
                res = retrieval_server.list_relations(invalid_uri)
                mock_ov_cls.assert_not_called()
                self.assertIn("error", res)
                self.assertNotIn("relations", res)

    def test_backend_client_error_propagated(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0024.md"

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.side_effect = OpenVikingError("Backend unavailable")

            res = retrieval_server.list_relations(source_uri)

        self.assertEqual(res, {"error": "Backend unavailable"})

    def test_non_dict_and_missing_key_entries_skipped(self) -> None:
        source_uri = "viking://resources/project/decisions/DEC-0024.md"
        raw_relations = [
            "not a dict",
            None,
            123,
            {"missing_uri": "foo", "reason": "supersedes, desc"},
            {"uri": "viking://resources/project/a.md"},  # missing reason
            {"uri": "", "reason": "supersedes, empty uri"},
            {"uri": None, "reason": "supersedes, none uri"},
            {
                "uri": "viking://resources/project/valid.md",
                "reason": "supersedes, valid item",
            },
        ]

        with patch("retrieval_mcp.server.OpenVikingClient") as mock_ov_cls:
            mock_client = MagicMock()
            mock_ov_cls.return_value.__enter__.return_value = mock_client
            mock_client.get_relations.return_value = raw_relations

            res = retrieval_server.list_relations(source_uri)

        self.assertEqual(len(res["relations"]), 1)
        self.assertEqual(
            res["relations"][0],
            {
                "uri": "viking://resources/project/valid.md",
                "reason": "supersedes",
                "desc": "valid item",
            },
        )


if __name__ == "__main__":
    unittest.main()
