from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "superpowers_mcp"))

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    import types

    class _RequestError(Exception):
        pass

    sys.modules["httpx"] = types.SimpleNamespace(
        Client=object,
        RequestError=_RequestError,
    )

from ov_client import OpenVikingError
from decision_frontmatter import build_decision_markdown, get_status
import server as superpowers_server


class FakeOpenVikingClient:
    """In-memory OpenViking client for testing promote_decision."""

    def __init__(self, files: dict[str, str] | None = None, relations: list[dict] | None = None) -> None:
        self.files: dict[str, str] = dict(files) if files else {}
        self.relations: list[dict] = list(relations) if relations else []
        self.write_fail_uris: set[str] = set()
        self.delete_fail_uris: set[str] = set()
        self.read_fail_uris: set[str] = set()
        self.corrupt_read_after_write: dict[str, str] = {}

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

    def write(self, uri: str, content: str, mode: str = "replace") -> dict:
        if uri in self.write_fail_uris:
            raise OpenVikingError(f"Backend write failed for {uri}")
        if mode == "create" and uri in self.files:
            raise OpenVikingError(f"Resource already exists: {uri}")
        self.files[uri] = content
        if uri in self.corrupt_read_after_write:
            self.files[uri] = self.corrupt_read_after_write.pop(uri)
        return {}

    def stat_resource(self, uri: str) -> dict:
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

    def delete_resource(self, uri: str) -> dict:
        if uri in self.delete_fail_uris:
            raise OpenVikingError(f"Backend delete failed for {uri}")
        if uri in self.files:
            del self.files[uri]
        return {}

    def exists(self, uri: str, is_file: bool = False) -> bool:
        return uri in self.files

    def link(self, from_uri: str, to_uris: str | list[str], reason: str = "") -> dict:
        targets = [to_uris] if isinstance(to_uris, str) else list(to_uris)
        for target in targets:
            self.relations.append({"from_uri": from_uri, "uri": target, "reason": reason})
        return {}

    def unlink(self, from_uri: str, to_uri: str) -> dict:
        self.relations = [
            r for r in self.relations
            if not (r.get("from_uri") == from_uri and r.get("uri") == to_uri)
        ]
        return {}

    def get_relations(self, uri: str) -> list[dict]:
        return [
            {"uri": r.get("uri"), "reason": r.get("reason", "")}
            for r in self.relations
            if r.get("from_uri") == uri
        ]


def _make_decision(status: str = "implemented", number: str = "0001") -> str:
    return build_decision_markdown(
        dec_number=number,
        context="Context for DEC-0001",
        problem="Problem statement",
        alternatives="Alternative 1",
        decision="Decision statement",
        consequences="Consequences statement",
        status=status,  # type: ignore[arg-type]
    )


class PromoteDecisionFieldValidationTests(unittest.TestCase):
    """Test required and forbidden field enforcement matrix across all 4 actions."""

    def setUp(self) -> None:
        self.dec_uri = "viking://resources/project/decisions/DEC-0001.md"
        self.fake_client = FakeOpenVikingClient(
            files={self.dec_uri: _make_decision("implemented")}
        )

    def test_unknown_action_rejected(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="invalid_action",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_ACTION")
            self.assertIn("invalid_action", res["error"]["message"])

    def test_edit_l2_missing_required_fields(self) -> None:
        required = {
            "target": "architecture",
            "target_path": "overview.md",
            "write_mode": "create",
            "content": "# Overview\n\nContent",
        }
        for field in required:
            kwargs = dict(required)
            del kwargs[field]
            with self.subTest(missing=field):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="edit_l2",
                        **kwargs,
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

    def test_edit_l2_forbidden_fields_rejected(self) -> None:
        forbidden = ["primary", "secondary", "reason_pair", "desc"]
        valid_kwargs = {
            "target": "architecture",
            "target_path": "overview.md",
            "write_mode": "create",
            "content": "# Overview\n\nContent",
        }
        for field in forbidden:
            kwargs = dict(valid_kwargs)
            kwargs[field] = "extra_value"
            with self.subTest(forbidden=field):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="edit_l2",
                        **kwargs,
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

    def test_edit_l2_section_enforcement(self) -> None:
        # write_mode="edit" requires section
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="overview.md",
                write_mode="edit",
                content="## Sub\nNew",
                section=None,
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

        # write_mode="create" forbids section
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="overview.md",
                write_mode="create",
                content="# Content",
                section="## Heading",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

        # write_mode="replace" forbids section
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="overview.md",
                write_mode="replace",
                content="# Content",
                section="## Heading",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

    def test_set_relation_missing_required_fields(self) -> None:
        required = {
            "primary": self.dec_uri,
            "secondary": "viking://resources/project/architecture/overview.md",
            "reason_pair": "promoted_to/derived_from",
            "desc": "implements new design",
        }
        for field in required:
            kwargs = dict(required)
            del kwargs[field]
            with self.subTest(missing=field):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="set_relation",
                        **kwargs,
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

    def test_set_relation_forbidden_fields_rejected(self) -> None:
        forbidden = ["target", "target_path", "write_mode", "content", "section"]
        valid_kwargs = {
            "primary": self.dec_uri,
            "secondary": "viking://resources/project/architecture/overview.md",
            "reason_pair": "promoted_to/derived_from",
            "desc": "implements new design",
        }
        for field in forbidden:
            kwargs = dict(valid_kwargs)
            kwargs[field] = "extra_value"
            with self.subTest(forbidden=field):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="set_relation",
                        **kwargs,
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

    def test_remove_relation_missing_required_fields(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="remove_relation",
                primary=self.dec_uri,
                secondary=None,
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

    def test_remove_relation_forbidden_fields_rejected(self) -> None:
        forbidden = ["target", "target_path", "write_mode", "content", "section", "reason_pair", "desc"]
        valid_kwargs = {
            "primary": self.dec_uri,
            "secondary": "viking://resources/project/architecture/overview.md",
        }
        for field in forbidden:
            kwargs = dict(valid_kwargs)
            kwargs[field] = "extra_value"
            with self.subTest(forbidden=field):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="remove_relation",
                        **kwargs,
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

    def test_set_relation_non_string_fields_rejected(self) -> None:
        invalid_types = [123, True, [], {}]
        for val in invalid_types:
            with self.subTest(primary=val):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="set_relation",
                        primary=val,  # type: ignore[arg-type]
                        secondary="viking://resources/project/architecture/overview.md",
                        reason_pair="promoted_to/derived_from",
                        desc="desc",
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

            with self.subTest(secondary=val):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="set_relation",
                        primary=self.dec_uri,
                        secondary=val,  # type: ignore[arg-type]
                        reason_pair="promoted_to/derived_from",
                        desc="desc",
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

    def test_remove_relation_non_string_fields_rejected(self) -> None:
        invalid_types = [123, True, [], {}]
        for val in invalid_types:
            with self.subTest(primary=val):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="remove_relation",
                        primary=val,  # type: ignore[arg-type]
                        secondary="viking://resources/project/architecture/overview.md",
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

            with self.subTest(secondary=val):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="remove_relation",
                        primary=self.dec_uri,
                        secondary=val,  # type: ignore[arg-type]
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")

    def test_finalize_rejects_any_optional_fields(self) -> None:
        optional_fields = [
            ("target", "architecture"),
            ("target_path", "foo.md"),
            ("write_mode", "create"),
            ("content", "hello"),
            ("section", "# Foo"),
            ("primary", self.dec_uri),
            ("secondary", "viking://resources/project/architecture/foo.md"),
            ("reason_pair", "promoted_to/derived_from"),
            ("desc", "description"),
        ]
        for field, value in optional_fields:
            with self.subTest(field=field):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="finalize",
                        **{field: value},
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_ACTION_FIELDS")


class PromoteDecisionUriAndLifecycleTests(unittest.TestCase):
    """Test decision URI format and lifecycle authorization gating."""

    def test_invalid_decision_uri_syntax(self) -> None:
        invalid_uris = [
            ("not-a-string", 1234),
            ("wrong-prefix", "viking://resources/project/architecture/foo.md"),
            ("non-md", "viking://resources/project/decisions/DEC-0001.txt"),
            ("wildcard-star", "viking://resources/project/decisions/*.md"),
            ("wildcard-question", "viking://resources/project/decisions/DEC-000?.md"),
            ("traversal", "viking://resources/project/decisions/../other.md"),
            ("whitespace", "viking://resources/project/decisions/DEC 0001.md"),
            ("empty-filename", "viking://resources/project/decisions/.md"),
            ("double-slash", "viking://resources/project/decisions//DEC-0001.md"),
        ]
        for label, uri in invalid_uris:
            with self.subTest(label=label):
                res = superpowers_server.promote_decision(
                    dec_uri=uri,  # type: ignore[arg-type]
                    action="finalize",
                )
                self.assertFalse(res["ok"])
                self.assertEqual(res["error"]["code"], "INVALID_DECISION_URI")

    def test_decision_not_found(self) -> None:
        fake_client = FakeOpenVikingClient(files={})
        with patch.object(superpowers_server, "OpenVikingClient", return_value=fake_client):
            res = superpowers_server.promote_decision(
                dec_uri="viking://resources/project/decisions/DEC-9999.md",
                action="finalize",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "DECISION_NOT_FOUND")

    def test_decision_lifecycle_conflict_for_non_implemented_statuses(self) -> None:
        dec_uri = "viking://resources/project/decisions/DEC-0001.md"
        statuses = [
            "not-implemented",
            "promoted",
            "superseded",
        ]
        for status in statuses:
            with self.subTest(status=status):
                fake_client = FakeOpenVikingClient(files={dec_uri: _make_decision(status)})
                with patch.object(superpowers_server, "OpenVikingClient", return_value=fake_client):
                    res = superpowers_server.promote_decision(
                        dec_uri=dec_uri,
                        action="finalize",
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "LIFECYCLE_CONFLICT")
                    self.assertIn(status, res["error"]["message"])

    def test_decision_with_invalid_frontmatter_rejected(self) -> None:
        dec_uri = "viking://resources/project/decisions/DEC-0001.md"
        fake_client = FakeOpenVikingClient(files={dec_uri: "# DEC-0001\n\nNo frontmatter here."})
        with patch.object(superpowers_server, "OpenVikingClient", return_value=fake_client):
            res = superpowers_server.promote_decision(
                dec_uri=dec_uri,
                action="finalize",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "LIFECYCLE_CONFLICT")


class PromoteDecisionEditL2Tests(unittest.TestCase):
    """Test edit_l2 action across create, replace, edit modes and compensation."""

    def setUp(self) -> None:
        self.dec_uri = "viking://resources/project/decisions/DEC-0001.md"
        self.client = FakeOpenVikingClient(
            files={self.dec_uri: _make_decision("implemented")}
        )

    def test_target_tree_validation(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="research",
                target_path="doc.md",
                write_mode="create",
                content="# Doc",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_TARGET")

    def test_target_path_validation(self) -> None:
        invalid_paths = [
            "/absolute.md",
            "../escaped.md",
            "wildcard*.md",
            "no_ext",
            "wrong_ext.txt",
            ".overview.md",
            "sub/.overview.md",
            ".abstract.md",
            "sub/.abstract.md",
            "has space.md",
        ]
        for path in invalid_paths:
            with self.subTest(path=path):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="edit_l2",
                        target="architecture",
                        target_path=path,
                        write_mode="create",
                        content="# Doc",
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_TARGET_PATH")

    def test_write_mode_validation(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="doc.md",
                write_mode="append",
                content="# Doc",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_WRITE_MODE")

    def test_create_mode_success(self) -> None:
        target_path = "storage/engine.md"
        expected_uri = "viking://resources/project/architecture/storage/engine.md"
        content = "# Storage Engine\n\nDesign details."

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path=target_path,
                write_mode="create",
                content=content,
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["changed"])
            self.assertEqual(res["action"], "edit_l2")
            self.assertEqual(res["result"]["uri"], expected_uri)
            self.assertEqual(self.client.read(expected_uri), content)

    def test_create_mode_rejects_blank_content(self) -> None:
        for blank in ["", "   ", "\n\t\n"]:
            with self.subTest(blank=blank):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="edit_l2",
                        target="architecture",
                        target_path="doc.md",
                        write_mode="create",
                        content=blank,
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_CONTENT")

    def test_create_mode_fails_if_target_already_exists(self) -> None:
        target_uri = "viking://resources/project/architecture/doc.md"
        self.client.files[target_uri] = "# Existing"

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="doc.md",
                write_mode="create",
                content="# New",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "TARGET_EXISTS")
            self.assertEqual(self.client.read(target_uri), "# Existing")

    def test_create_mode_verification_failure_deletes_new_file(self) -> None:
        target_uri = "viking://resources/project/architecture/doc.md"
        self.client.corrupt_read_after_write[target_uri] = "corrupted read"

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="doc.md",
                write_mode="create",
                content="# Document",
            )
            self.assertFalse(res["ok"])
            self.assertFalse(res["changed"])
            self.assertTrue(res.get("state_restored"))
            self.assertEqual(res["error"]["code"], "VERIFICATION_FAILURE")
            self.assertNotIn(target_uri, self.client.files)

    def test_create_mode_compensation_failure_when_delete_fails(self) -> None:
        target_uri = "viking://resources/project/architecture/doc.md"
        self.client.corrupt_read_after_write[target_uri] = "corrupted read"
        self.client.delete_fail_uris.add(target_uri)

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="doc.md",
                write_mode="create",
                content="# Document",
            )
            self.assertFalse(res["ok"])
            self.assertTrue(res["changed"])
            self.assertFalse(res.get("state_restored"))
            self.assertEqual(res["error"]["code"], "COMPENSATION_FAILURE")
            self.assertIn("recovery", res)

    def test_replace_mode_fails_if_target_missing(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="nonexistent.md",
                write_mode="replace",
                content="# Content",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "TARGET_NOT_FOUND")

    def test_replace_mode_rejects_blank_content(self) -> None:
        target_uri = "viking://resources/project/architecture/doc.md"
        self.client.files[target_uri] = "# Existing"

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="doc.md",
                write_mode="replace",
                content="  \n  ",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_CONTENT")

    def test_replace_mode_noop_when_identical(self) -> None:
        target_uri = "viking://resources/project/architecture/doc.md"
        original = "# Document\n\nSame content."
        self.client.files[target_uri] = original

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="doc.md",
                write_mode="replace",
                content=original,
            )
            self.assertTrue(res["ok"])
            self.assertFalse(res["changed"])
            self.assertEqual(res["result"]["uri"], target_uri)

    def test_replace_mode_success_when_different(self) -> None:
        target_uri = "viking://resources/project/architecture/doc.md"
        self.client.files[target_uri] = "# Document\n\nOld content."
        new_content = "# Document\n\nUpdated content."

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="doc.md",
                write_mode="replace",
                content=new_content,
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["changed"])
            self.assertEqual(self.client.read(target_uri), new_content)

    def test_replace_mode_compensation_restores_original_on_verification_failure(self) -> None:
        target_uri = "viking://resources/project/architecture/doc.md"
        original = "# Document\n\nOriginal content."
        self.client.files[target_uri] = original
        self.client.corrupt_read_after_write[target_uri] = "corrupted"

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="doc.md",
                write_mode="replace",
                content="# Document\n\nNew content.",
            )
            self.assertFalse(res["ok"])
            self.assertFalse(res["changed"])
            self.assertTrue(res.get("state_restored"))
            self.assertEqual(res["error"]["code"], "VERIFICATION_FAILURE")
            self.assertEqual(self.client.read(target_uri), original)

    def test_edit_mode_fails_if_target_missing(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="domains",
                target_path="missing.md",
                write_mode="edit",
                section="## Scope",
                content="New scope",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "TARGET_NOT_FOUND")

    def test_edit_mode_fails_if_section_not_found(self) -> None:
        target_uri = "viking://resources/project/domains/auth.md"
        self.client.files[target_uri] = "# Auth Domain\n\n## Overview\nOverview text."

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="domains",
                target_path="auth.md",
                write_mode="edit",
                section="## Nonexistent Section",
                content="Some content",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_SECTION")

    def test_edit_mode_fails_if_ambiguous_section(self) -> None:
        target_uri = "viking://resources/project/domains/auth.md"
        self.client.files[target_uri] = "# Auth Domain\n\n## Scope\nFirst.\n\n## Scope\nSecond."

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="domains",
                target_path="auth.md",
                write_mode="edit",
                section="## Scope",
                content="New scope",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_SECTION")

    def test_edit_mode_noop_when_resulting_document_identical(self) -> None:
        target_uri = "viking://resources/project/domains/auth.md"
        original = "# Auth Domain\n\n## Scope\nIdentical scope.\n\n## Next\nNext."
        self.client.files[target_uri] = original

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="domains",
                target_path="auth.md",
                write_mode="edit",
                section="## Scope",
                content="Identical scope.",
            )
            self.assertTrue(res["ok"])
            self.assertFalse(res["changed"])
            self.assertEqual(self.client.read(target_uri), original)

    def test_edit_mode_success_updates_section(self) -> None:
        target_uri = "viking://resources/project/domains/auth.md"
        original = "# Auth Domain\n\n## Scope\nOld scope.\n\n## Next\nNext."
        self.client.files[target_uri] = original

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="domains",
                target_path="auth.md",
                write_mode="edit",
                section="## Scope",
                content="New expanded scope.",
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["changed"])
            expected = "# Auth Domain\n\n## Scope\nNew expanded scope.\n\n## Next\nNext."
            self.assertEqual(self.client.read(target_uri), expected)


class PromoteDecisionSetRelationTests(unittest.TestCase):
    """Test set_relation vocabulary restriction, primary authorization, and execution."""

    def setUp(self) -> None:
        self.dec_uri = "viking://resources/project/decisions/DEC-0001.md"
        self.arch_uri = "viking://resources/project/architecture/overview.md"
        self.domain_uri = "viking://resources/project/domains/auth.md"
        self.client = FakeOpenVikingClient(
            files={
                self.dec_uri: _make_decision("implemented"),
                self.arch_uri: "# Architecture Overview",
                self.domain_uri: "# Auth Domain",
            }
        )

    def test_disallowed_reason_pairs_rejected(self) -> None:
        disallowed = [
            "produces/produced_from",
            "supersedes/superseded_by",
            "unknown/unknown",
        ]
        for pair in disallowed:
            with self.subTest(pair=pair):
                with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
                    res = superpowers_server.promote_decision(
                        dec_uri=self.dec_uri,
                        action="set_relation",
                        primary=self.dec_uri,
                        secondary=self.arch_uri,
                        reason_pair=pair,
                        desc="test relation",
                    )
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["error"]["code"], "INVALID_REASON_PAIR")

    def test_promoted_to_requires_primary_equal_dec_uri(self) -> None:
        other_dec = "viking://resources/project/decisions/DEC-0002.md"
        self.client.files[other_dec] = _make_decision("implemented", number="0002")

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="set_relation",
                primary=other_dec,
                secondary=self.arch_uri,
                reason_pair="promoted_to/derived_from",
                desc="test description",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_RELATION_PRIMARY")

    def test_set_relation_success_creates_reciprocal_links(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="set_relation",
                primary=self.dec_uri,
                secondary=self.arch_uri,
                reason_pair="promoted_to/derived_from",
                desc="promoted from DEC-0001",
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["changed"])
            self.assertEqual(res["result"]["primary"], self.dec_uri)
            self.assertEqual(res["result"]["secondary"], self.arch_uri)

            # Verify reciprocal links exist in client
            p_rel = self.client.get_relations(self.dec_uri)
            s_rel = self.client.get_relations(self.arch_uri)
            self.assertEqual(p_rel, [{"uri": self.arch_uri, "reason": "promoted_to, promoted from DEC-0001"}])
            self.assertEqual(s_rel, [{"uri": self.dec_uri, "reason": "derived_from, promoted from DEC-0001"}])

    def test_set_relation_noop_when_exact_pair_already_exists(self) -> None:
        # Pre-populate exact links
        self.client.relations = [
            {"from_uri": self.dec_uri, "uri": self.arch_uri, "reason": "promoted_to, exact desc"},
            {"from_uri": self.arch_uri, "uri": self.dec_uri, "reason": "derived_from, exact desc"},
        ]

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="set_relation",
                primary=self.dec_uri,
                secondary=self.arch_uri,
                reason_pair="promoted_to/derived_from",
                desc="exact desc",
            )
            self.assertTrue(res["ok"])
            self.assertFalse(res["changed"])

    def test_set_relation_between_non_decision_entities(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="set_relation",
                primary=self.arch_uri,
                secondary=self.domain_uri,
                reason_pair="composes/part_of",
                desc="architecture composes auth domain",
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["changed"])

    def test_set_relation_invalid_topology_mapping(self) -> None:
        # composes/part_of requires primary under architecture/ and secondary under domains/
        # Passing domain as primary and architecture as secondary violates topology
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="set_relation",
                primary=self.domain_uri,
                secondary=self.arch_uri,
                reason_pair="composes/part_of",
                desc="invalid direction",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_TOPOLOGY")

        # Identical endpoints also violate topology
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="set_relation",
                primary=self.arch_uri,
                secondary=self.arch_uri,
                reason_pair="references/referenced_by",
                desc="self reference",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_TOPOLOGY")


class PromoteDecisionRemoveRelationTests(unittest.TestCase):
    """Test remove_relation decision primary constraint and reciprocal removal."""

    def setUp(self) -> None:
        self.dec_uri = "viking://resources/project/decisions/DEC-0001.md"
        self.other_dec_uri = "viking://resources/project/decisions/DEC-0002.md"
        self.arch_uri = "viking://resources/project/architecture/overview.md"
        self.domain_uri = "viking://resources/project/domains/auth.md"
        self.client = FakeOpenVikingClient(
            files={
                self.dec_uri: _make_decision("implemented", "0001"),
                self.other_dec_uri: _make_decision("implemented", "0002"),
                self.arch_uri: "# Arch",
                self.domain_uri: "# Domain",
            }
        )

    def test_decision_as_secondary_rejected(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="remove_relation",
                primary=self.arch_uri,
                secondary=self.dec_uri,
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_RELATION_PRIMARY")

    def test_other_decision_as_primary_rejected(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="remove_relation",
                primary=self.other_dec_uri,
                secondary=self.arch_uri,
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], "INVALID_RELATION_PRIMARY")

    def test_remove_relation_noop_when_absent(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="remove_relation",
                primary=self.dec_uri,
                secondary=self.arch_uri,
            )
            self.assertTrue(res["ok"])
            self.assertFalse(res["changed"])

    def test_remove_relation_success(self) -> None:
        self.client.relations = [
            {"from_uri": self.dec_uri, "uri": self.arch_uri, "reason": "promoted_to, desc"},
            {"from_uri": self.arch_uri, "uri": self.dec_uri, "reason": "derived_from, desc"},
        ]

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="remove_relation",
                primary=self.dec_uri,
                secondary=self.arch_uri,
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["changed"])
            self.assertEqual(self.client.get_relations(self.dec_uri), [])
            self.assertEqual(self.client.get_relations(self.arch_uri), [])


class PromoteDecisionFinalizeTests(unittest.TestCase):
    """Test finalize status transition and gating subsequent promotion calls."""

    def setUp(self) -> None:
        self.dec_uri = "viking://resources/project/decisions/DEC-0001.md"
        self.client = FakeOpenVikingClient(
            files={self.dec_uri: _make_decision("implemented")}
        )

    def test_finalize_updates_status_to_promoted(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="finalize",
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["changed"])
            self.assertEqual(res["action"], "finalize")
            self.assertEqual(res["result"]["status"], "promoted")

            # Verify in backend storage
            backend_content = self.client.read(self.dec_uri)
            self.assertEqual(get_status(backend_content), "promoted")

    def test_subsequent_promotion_calls_rejected_after_finalize(self) -> None:
        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="finalize",
            )
            self.assertTrue(res["ok"])

            # 1. Calling finalize again fails with LIFECYCLE_CONFLICT
            res2 = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="finalize",
            )
            self.assertFalse(res2["ok"])
            self.assertEqual(res2["error"]["code"], "LIFECYCLE_CONFLICT")

            # 2. Calling edit_l2 fails with LIFECYCLE_CONFLICT
            res3 = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="edit_l2",
                target="architecture",
                target_path="doc.md",
                write_mode="create",
                content="# Doc",
            )
            self.assertFalse(res3["ok"])
            self.assertEqual(res3["error"]["code"], "LIFECYCLE_CONFLICT")

            # 3. Calling set_relation fails with LIFECYCLE_CONFLICT
            res4 = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="set_relation",
                primary=self.dec_uri,
                secondary="viking://resources/project/architecture/doc.md",
                reason_pair="promoted_to/derived_from",
                desc="desc",
            )
            self.assertFalse(res4["ok"])
            self.assertEqual(res4["error"]["code"], "LIFECYCLE_CONFLICT")

            # 4. Calling remove_relation fails with LIFECYCLE_CONFLICT
            res5 = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="remove_relation",
                primary=self.dec_uri,
                secondary="viking://resources/project/architecture/doc.md",
            )
            self.assertFalse(res5["ok"])
            self.assertEqual(res5["error"]["code"], "LIFECYCLE_CONFLICT")

    def test_finalize_verification_failure_restores_implemented_status(self) -> None:
        # Corrupt read after write so verification fails
        self.client.corrupt_read_after_write[self.dec_uri] = _make_decision("corrupted")

        with patch.object(superpowers_server, "OpenVikingClient", return_value=self.client):
            res = superpowers_server.promote_decision(
                dec_uri=self.dec_uri,
                action="finalize",
            )
            self.assertFalse(res["ok"])
            self.assertFalse(res["changed"])
            self.assertTrue(res.get("state_restored"))
            self.assertEqual(res["error"]["code"], "VERIFICATION_FAILURE")

            # Backend status should be restored to implemented
            backend_content = self.client.read(self.dec_uri)
            self.assertEqual(get_status(backend_content), "implemented")


if __name__ == "__main__":
    unittest.main()
