from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "braining_mcp"))
sys.path.insert(0, str(ROOT / "superpowers_mcp"))

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

from ov_client import OpenVikingError
from decision_frontmatter import build_decision_markdown, get_status
import braining_mcp.server as braining_server
import superpowers_mcp.server as superpowers_server


class FakeOpenVikingClient:
    """In-memory OpenViking client for testing writer tools."""

    def __init__(
        self,
        files: dict[str, str] | None = None,
        relations: list[dict[str, Any]] | None = None,
    ) -> None:
        self.files: dict[str, str] = dict(files) if files else {}
        self.relations: list[dict[str, Any]] = list(relations) if relations else []
        self.write_fail_uris: set[str] = set()
        self.delete_fail_uris: set[str] = set()
        self.read_fail_uris: set[str] = set()

    def __enter__(self) -> "FakeOpenVikingClient":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def close(self) -> None:
        pass

    def read(self, uri: str) -> str:
        if uri in self.read_fail_uris:
            raise OpenVikingError(f"Backend read failed for {uri}")
        if uri not in self.files:
            raise OpenVikingError(f"File not found: {uri}")
        return self.files[uri]

    def write(self, uri: str, content: str, mode: str = "replace") -> dict[str, Any]:
        if uri in self.write_fail_uris:
            raise OpenVikingError(f"Backend write failed for {uri}")
        if mode == "create" and uri in self.files:
            raise OpenVikingError(f"Resource already exists: {uri}")
        self.files[uri] = content
        return {}

    def stat_resource(self, uri: str) -> dict[str, Any]:
        if uri not in self.files:
            raise OpenVikingError(f"Resource not found: {uri}")
        return {
            "name": uri.rsplit("/", 1)[-1],
            "size": len(self.files[uri]),
            "mode": "0644",
            "modTime": "2026-09-03T00:00:00Z",
            "isDir": False,
            "isLocked": False,
        }

    def delete_resource(self, uri: str) -> dict[str, Any]:
        if uri in self.delete_fail_uris:
            raise OpenVikingError(f"Backend delete failed for {uri}")
        if uri in self.files:
            del self.files[uri]
        return {}

    def exists(self, uri: str, is_file: bool = False) -> bool:
        return uri in self.files

    def link(self, from_uri: str, to_uris: str | list[str], reason: str = "") -> dict[str, Any]:
        targets = [to_uris] if isinstance(to_uris, str) else list(to_uris)
        for target in targets:
            self.relations.append({"from_uri": from_uri, "uri": target, "reason": reason})
        return {}

    def unlink(self, from_uri: str, to_uri: str) -> dict[str, Any]:
        self.relations = [
            r
            for r in self.relations
            if not (r.get("from_uri") == from_uri and r.get("uri") == to_uri)
        ]
        return {}

    def get_relations(self, uri: str) -> list[dict[str, Any]]:
        return [
            {"uri": r.get("uri"), "reason": r.get("reason", "")}
            for r in self.relations
            if r.get("from_uri") == uri
        ]

    def ls(self, uri: str) -> list[dict[str, Any]]:
        prefix = uri.rstrip("/") + "/"
        results = []
        for f_uri in sorted(self.files):
            if f_uri.startswith(prefix):
                results.append({"uri": f_uri, "name": f_uri[len(prefix):]})
        return results


class TestWriteDecision(unittest.TestCase):
    """Test write_decision with source_research, reciprocal relations, and stop-on-failure."""

    def setUp(self) -> None:
        self.fake_client = FakeOpenVikingClient()

    def test_signature_has_source_research_not_uris(self) -> None:
        sig = inspect.signature(braining_server.write_decision)
        self.assertIn("source_research", sig.parameters)
        self.assertNotIn("source_research_uris", sig.parameters)
        param = sig.parameters["source_research"]
        self.assertIsNone(param.default)

    def test_write_decision_without_source_research(self) -> None:
        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.write_decision(
                context="Context text",
                problem="Problem text",
                alternatives="Alternatives text",
                decision="Decision text",
                consequences="Consequences text",
            )
            self.assertEqual(res["uri"], "viking://resources/project/decisions/DEC-0001.md")
            self.assertEqual(res["dec_number"], "0001")
            self.assertEqual(res["status"], "not-implemented")
            self.assertEqual(res["linked_research"], [])
            self.assertIn("viking://resources/project/decisions/DEC-0001.md", self.fake_client.files)
            saved_content = self.fake_client.files["viking://resources/project/decisions/DEC-0001.md"]
            self.assertEqual(get_status(saved_content), "not-implemented")

    def test_write_decision_with_valid_source_research(self) -> None:
        r1 = "viking://resources/project/research/ideas/speed-up.md"
        r2 = "viking://resources/project/research/debates/arch-debate.md"
        self.fake_client.files[r1] = "# Speed Up Idea"
        self.fake_client.files[r2] = "# Arch Debate"

        source_research = [
            {"uri": r1, "desc": "Initial benchmark investigation"},
            {"uri": r2, "desc": "Debate outcome on consensus model"},
        ]

        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.write_decision(
                context="Context text",
                problem="Problem text",
                alternatives="Alternatives text",
                decision="Decision text",
                consequences="Consequences text",
                source_research=source_research,
            )

            dec_uri = "viking://resources/project/decisions/DEC-0001.md"
            self.assertEqual(res["uri"], dec_uri)
            self.assertEqual(res["dec_number"], "0001")
            self.assertEqual(res["status"], "not-implemented")
            self.assertEqual(
                res["linked_research"],
                [
                    {"uri": r1, "desc": "Initial benchmark investigation"},
                    {"uri": r2, "desc": "Debate outcome on consensus model"},
                ],
            )

            # Check reciprocal relations for r1 <-> dec_uri
            r1_rels = self.fake_client.get_relations(r1)
            self.assertEqual(
                r1_rels,
                [{"uri": dec_uri, "reason": "produces, Initial benchmark investigation"}],
            )
            dec_rels = self.fake_client.get_relations(dec_uri)
            self.assertIn(
                {"uri": r1, "reason": "produced_from, Initial benchmark investigation"},
                dec_rels,
            )

            # Check reciprocal relations for r2 <-> dec_uri
            r2_rels = self.fake_client.get_relations(r2)
            self.assertEqual(
                r2_rels,
                [{"uri": dec_uri, "reason": "produces, Debate outcome on consensus model"}],
            )
            self.assertIn(
                {"uri": r2, "reason": "produced_from, Debate outcome on consensus model"},
                dec_rels,
            )

    def test_write_decision_sequential_stop_on_first_failure(self) -> None:
        r1 = "viking://resources/project/research/ideas/idea-1.md"
        r2_missing = "viking://resources/project/research/ideas/missing.md"
        r3 = "viking://resources/project/research/ideas/idea-3.md"
        self.fake_client.files[r1] = "# Idea 1"
        self.fake_client.files[r3] = "# Idea 3"

        source_research = [
            {"uri": r1, "desc": "Idea 1 desc"},
            {"uri": r2_missing, "desc": "Missing desc"},
            {"uri": r3, "desc": "Idea 3 desc"},
        ]

        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.write_decision(
                context="Context text",
                problem="Problem text",
                alternatives="Alternatives text",
                decision="Decision text",
                consequences="Consequences text",
                source_research=source_research,
            )

            dec_uri = "viking://resources/project/decisions/DEC-0001.md"
            # Decision was created and preserved
            self.assertIn(dec_uri, self.fake_client.files)
            self.assertEqual(res["uri"], dec_uri)
            self.assertEqual(res["status"], "not-implemented")
            self.assertIn("error", res)
            self.assertIn(r2_missing, res["error"])

            # r1 link succeeded and was preserved
            self.assertEqual(
                res["linked_research"],
                [{"uri": r1, "desc": "Idea 1 desc"}],
            )
            self.assertEqual(
                self.fake_client.get_relations(r1),
                [{"uri": dec_uri, "reason": "produces, Idea 1 desc"}],
            )

            # r2 failed (missing file) and no links exist
            self.assertEqual(self.fake_client.get_relations(r2_missing), [])

            # r3 was NOT processed due to stop-on-first-failure
            self.assertEqual(self.fake_client.get_relations(r3), [])
            dec_rels = self.fake_client.get_relations(dec_uri)
            self.assertEqual(
                dec_rels,
                [{"uri": r1, "reason": "produced_from, Idea 1 desc"}],
            )

    def test_write_decision_invalid_source_research_type(self) -> None:
        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.write_decision(
                context="Context",
                problem="Problem",
                alternatives="Alt",
                decision="Dec",
                consequences="Cons",
                source_research="not-a-list",  # type: ignore[arg-type]
            )
            self.assertIn("error", res)

    def test_write_decision_invalid_entry_format(self) -> None:
        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.write_decision(
                context="Context",
                problem="Problem",
                alternatives="Alt",
                decision="Dec",
                consequences="Cons",
                source_research=[{"wrong_key": "bad"}],  # type: ignore[list-item]
            )
            self.assertIn("error", res)
            # Decision preserved
            self.assertEqual(res.get("status"), "not-implemented")

    def test_write_decision_invalid_desc_with_newlines(self) -> None:
        r1 = "viking://resources/project/research/ideas/test.md"
        self.fake_client.files[r1] = "# Research"
        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.write_decision(
                context="Context",
                problem="Problem",
                alternatives="Alt",
                decision="Dec",
                consequences="Cons",
                source_research=[{"uri": r1, "desc": "line 1\nline 2"}],
            )
            self.assertIn("error", res)
            self.assertEqual(res.get("status"), "not-implemented")
            self.assertEqual(self.fake_client.get_relations(r1), [])

    def test_write_decision_non_research_uri(self) -> None:
        non_res = "viking://resources/project/architecture/overview.md"
        self.fake_client.files[non_res] = "# Arch"
        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.write_decision(
                context="Context",
                problem="Problem",
                alternatives="Alt",
                decision="Dec",
                consequences="Cons",
                source_research=[{"uri": non_res, "desc": "Invalid target"}],
            )
            self.assertIn("error", res)
            self.assertEqual(res.get("status"), "not-implemented")

    def test_write_decision_trims_desc_in_linked_research(self) -> None:
        r1 = "viking://resources/project/research/ideas/untrimmed.md"
        self.fake_client.files[r1] = "# Untrimmed"
        source_research = [{"uri": r1, "desc": "   Padded description   "}]

        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.write_decision(
                context="Context",
                problem="Problem",
                alternatives="Alt",
                decision="Dec",
                consequences="Cons",
                source_research=source_research,
            )
            self.assertEqual(
                res["linked_research"],
                [{"uri": r1, "desc": "Padded description"}],
            )
            dec_uri = res["uri"]
            self.assertEqual(
                self.fake_client.get_relations(r1),
                [{"uri": dec_uri, "reason": "produces, Padded description"}],
            )


class TestSupersedeDecision(unittest.TestCase):
    """Test supersede_decision requiring relation_desc and reciprocal supersedes/superseded_by."""

    def setUp(self) -> None:
        self.old_dec_uri = "viking://resources/project/decisions/DEC-0001.md"
        self.old_content = build_decision_markdown(
            dec_number="0001",
            context="Old context",
            problem="Old problem",
            alternatives="Old alt",
            decision="Old dec",
            consequences="Old cons",
            status="implemented",
        )
        self.fake_client = FakeOpenVikingClient(
            files={self.old_dec_uri: self.old_content}
        )

    def test_signature_requires_relation_desc(self) -> None:
        sig = inspect.signature(braining_server.supersede_decision)
        self.assertIn("relation_desc", sig.parameters)
        param = sig.parameters["relation_desc"]
        self.assertEqual(param.default, inspect.Parameter.empty)

    def test_supersede_decision_success(self) -> None:
        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.supersede_decision(
                old_dec_uri=self.old_dec_uri,
                context="New context",
                problem="New problem",
                alternatives="New alt",
                decision="New dec",
                consequences="New cons",
                relation_desc="Replaces single-threaded model with event loop",
            )

            new_dec_uri = "viking://resources/project/decisions/DEC-0002.md"
            self.assertEqual(res["new_uri"], new_dec_uri)
            self.assertEqual(res["old_uri"], self.old_dec_uri)
            self.assertEqual(res["old_status"], "superseded")
            self.assertNotIn("error", res)

            # Check new decision on disk
            new_content = self.fake_client.files[new_dec_uri]
            self.assertEqual(get_status(new_content), "not-implemented")

            # Check old decision on disk
            updated_old = self.fake_client.files[self.old_dec_uri]
            self.assertEqual(get_status(updated_old), "superseded")
            self.assertIn("superseded_by: DEC-0002", updated_old)

            # Check reciprocal relations
            new_rels = self.fake_client.get_relations(new_dec_uri)
            self.assertEqual(
                new_rels,
                [
                    {
                        "uri": self.old_dec_uri,
                        "reason": "supersedes, Replaces single-threaded model with event loop",
                    }
                ],
            )
            old_rels = self.fake_client.get_relations(self.old_dec_uri)
            self.assertEqual(
                old_rels,
                [
                    {
                        "uri": new_dec_uri,
                        "reason": "superseded_by, Replaces single-threaded model with event loop",
                    }
                ],
            )

    def test_supersede_decision_rejects_empty_relation_desc(self) -> None:
        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.supersede_decision(
                old_dec_uri=self.old_dec_uri,
                context="New context",
                problem="New problem",
                alternatives="New alt",
                decision="New dec",
                consequences="New cons",
                relation_desc="   ",
            )
            self.assertIn("error", res)
            # Old decision remains unchanged
            self.assertEqual(get_status(self.fake_client.files[self.old_dec_uri]), "implemented")

    def test_supersede_decision_rejects_multiline_relation_desc(self) -> None:
        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.supersede_decision(
                old_dec_uri=self.old_dec_uri,
                context="New context",
                problem="New problem",
                alternatives="New alt",
                decision="New dec",
                consequences="New cons",
                relation_desc="Line 1\nLine 2",
            )
            self.assertIn("error", res)
            self.assertEqual(get_status(self.fake_client.files[self.old_dec_uri]), "implemented")

    def test_supersede_decision_relation_failure_returns_hard_error(self) -> None:
        """If relation fails, new decision and old decision superseded status are preserved, relation compensated, and hard error returned."""
        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            # Patch set_reciprocal_relation to fail
            with patch(
                "braining_mcp.server.set_reciprocal_relation",
                return_value={"ok": False, "changed": False, "state_restored": True, "error": "Simulated relation failure"},
            ):
                res = braining_server.supersede_decision(
                    old_dec_uri=self.old_dec_uri,
                    context="New context",
                    problem="New problem",
                    alternatives="New alt",
                    decision="New dec",
                    consequences="New cons",
                    relation_desc="Valid relation desc",
                )

                # Hard error returned
                self.assertIn("error", res)
                self.assertIn("Simulated relation failure", res["error"])

                new_dec_uri = "viking://resources/project/decisions/DEC-0002.md"
                # Both decisions are preserved in their updated statuses
                self.assertIn(new_dec_uri, self.fake_client.files)
                self.assertEqual(get_status(self.fake_client.files[new_dec_uri]), "not-implemented")
                self.assertEqual(get_status(self.fake_client.files[self.old_dec_uri]), "superseded")

                # No relations exist
                self.assertEqual(self.fake_client.relations, [])

    def test_supersede_decision_rejects_non_decision_uri_upfront(self) -> None:
        arch_uri = "viking://resources/project/architecture/overview.md"
        self.fake_client.files[arch_uri] = "# Living Architecture"
        initial_file_count = len(self.fake_client.files)

        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.supersede_decision(
                old_dec_uri=arch_uri,
                context="New context",
                problem="New problem",
                alternatives="New alt",
                decision="New dec",
                consequences="New cons",
                relation_desc="Should be rejected upfront",
            )
            self.assertIn("error", res)
            self.assertIn("old_dec_uri", res["error"])
            # The architecture file was NOT overwritten
            self.assertEqual(self.fake_client.files[arch_uri], "# Living Architecture")
            # No new decision files were created
            self.assertEqual(len(self.fake_client.files), initial_file_count)

    def test_supersede_decision_rejects_non_md_uri_upfront(self) -> None:
        non_md_uri = "viking://resources/project/decisions/DEC-0001"
        initial_file_count = len(self.fake_client.files)

        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.supersede_decision(
                old_dec_uri=non_md_uri,
                context="New context",
                problem="New problem",
                alternatives="New alt",
                decision="New dec",
                consequences="New cons",
                relation_desc="Should be rejected upfront",
            )
            self.assertIn("error", res)
            self.assertEqual(len(self.fake_client.files), initial_file_count)

    def test_supersede_decision_rejects_traversal_uri_upfront(self) -> None:
        traversal_uri = "viking://resources/project/decisions/../decisions/DEC-0001.md"
        initial_file_count = len(self.fake_client.files)

        with patch.object(braining_server, "OpenVikingClient", return_value=self.fake_client):
            res = braining_server.supersede_decision(
                old_dec_uri=traversal_uri,
                context="New context",
                problem="New problem",
                alternatives="New alt",
                decision="New dec",
                consequences="New cons",
                relation_desc="Should be rejected upfront",
            )
            self.assertIn("error", res)
            self.assertEqual(len(self.fake_client.files), initial_file_count)


class TestWriteAudit(unittest.TestCase):
    """Test write_audit without related_invariant_uris and returning no relation output."""

    def setUp(self) -> None:
        self.fake_client = FakeOpenVikingClient()

    def test_signature_has_no_related_invariant_uris(self) -> None:
        sig = inspect.signature(superpowers_server.write_audit)
        self.assertEqual(list(sig.parameters.keys()), ["category", "title", "content"])

    def test_write_audit_success_returns_no_relation_output(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
            res = superpowers_server.write_audit(
                category="architecture",
                title="Q3 System Audit",
                content="Audit body text",
            )

            expected_uri = "viking://resources/project/audits/architecture/q3-system-audit.md"
            self.assertEqual(res, {"uri": expected_uri, "category": "architecture"})
            self.assertNotIn("linked_invariants", res)
            self.assertIn(expected_uri, self.fake_client.files)
            self.assertIn("Audit body text", self.fake_client.files[expected_uri])
            # No relations created
            self.assertEqual(self.fake_client.relations, [])

    def test_write_audit_invalid_category(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
            res = superpowers_server.write_audit(
                category="unknown_category",
                title="Bad Audit",
                content="Body",
            )
            self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
