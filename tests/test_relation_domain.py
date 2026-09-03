from __future__ import annotations

import sys
import unittest
from pathlib import Path

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

from ov_client import OpenVikingClient, OpenVikingError
from relation_domain import (  # noqa: E402
    RECIPROCAL_PAIRS,
    PARSE_ERROR_EMPTY_FIELD,
    PARSE_ERROR_INVALID_CONTROL_CHARS,
    PARSE_ERROR_MISSING_DELIMITER,
    PARSE_ERROR_UNKNOWN_REASON,
    parse_relation_reason,
    remove_reciprocal_relation,
    serialize_relation_reason,
    set_reciprocal_relation,
    snapshot_relations,
    validate_endpoint_uri,
    validate_topology,
)


class ReciprocalPairsVocabularyTests(unittest.TestCase):
    """Test canonical reciprocal pairs vocabulary."""

    def test_canonical_pairs_exist_and_are_bidirectional(self) -> None:
        expected_pairs = {
            ("produces", "produced_from"),
            ("supersedes", "superseded_by"),
            ("promoted_to", "derived_from"),
            ("composes", "part_of"),
            ("enforces", "enforced_by"),
            ("references", "referenced_by"),
        }

        for p, s in expected_pairs:
            self.assertIn(p, RECIPROCAL_PAIRS)
            self.assertIn(s, RECIPROCAL_PAIRS)
            self.assertEqual(RECIPROCAL_PAIRS[p], s)
            self.assertEqual(RECIPROCAL_PAIRS[s], p)

        # Ensure no unexpected extra keys
        self.assertEqual(len(RECIPROCAL_PAIRS), len(expected_pairs) * 2)

    def test_involutory_symmetry(self) -> None:
        for k, v in RECIPROCAL_PAIRS.items():
            self.assertEqual(RECIPROCAL_PAIRS[v], k)


class ValidateEndpointUriTests(unittest.TestCase):
    """Test URI format and scope validation."""

    def test_valid_endpoint_uris(self) -> None:
        valid_uris = [
            "viking://resources/project/research/debates/auth.md",
            "viking://resources/project/decisions/DEC-0001.md",
            "viking://resources/project/architecture/overview.md",
            "viking://resources/project/domains/governance/advisors.md",
            "viking://resources/project/invariants/security.md",
            "viking://resources/project/README.md",
            "viking://resources/project/nested/deep/path/file.md",
        ]
        for uri in valid_uris:
            with self.subTest(uri=uri):
                # Should not raise
                validate_endpoint_uri(uri)

    def test_rejects_non_string(self) -> None:
        for invalid in [None, 123, [], {}]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_endpoint_uri(invalid)  # type: ignore[arg-type]

    def test_rejects_wrong_prefix(self) -> None:
        invalid_prefixes = [
            "viking://resources/user/notes.md",
            "viking://agent/skills/s.md",
            "https://example.com/project/decisions/DEC-0001.md",
            "/home/user/project/decisions/DEC-0001.md",
            "viking://resources/other/DEC-0001.md",
            "viking://resources/project",
        ]
        for uri in invalid_prefixes:
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    validate_endpoint_uri(uri)

    def test_rejects_non_md_extension(self) -> None:
        invalid_extensions = [
            "viking://resources/project/decisions/DEC-0001",
            "viking://resources/project/decisions/DEC-0001.txt",
            "viking://resources/project/decisions/DEC-0001.json",
            "viking://resources/project/decisions/",
        ]
        for uri in invalid_extensions:
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    validate_endpoint_uri(uri)

    def test_rejects_wildcards(self) -> None:
        wildcard_uris = [
            "viking://resources/project/architecture/*.md",
            "viking://resources/project/domains/**/*.md",
            "viking://resources/project/decisions/DEC-000?.md",
        ]
        for uri in wildcard_uris:
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    validate_endpoint_uri(uri)

    def test_rejects_traversal(self) -> None:
        traversal_uris = [
            "viking://resources/project/decisions/../secrets.md",
            "viking://resources/project/domains/../../agent/skills.md",
            "viking://resources/project/..md",
        ]
        for uri in traversal_uris:
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    validate_endpoint_uri(uri)

    def test_rejects_whitespace(self) -> None:
        whitespace_uris = [
            "viking://resources/project/decisions/DEC 0001.md",
            "viking://resources/project/decisions/DEC-0001\t.md",
            "viking://resources/project/decisions/DEC-0001\n.md",
            " viking://resources/project/decisions/DEC-0001.md",
            "viking://resources/project/decisions/DEC-0001.md ",
        ]
        for uri in whitespace_uris:
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    validate_endpoint_uri(uri)

    def test_rejects_control_characters(self) -> None:
        control_uris = [
            "viking://resources/project/decisions/DEC\x000001.md",
            "viking://resources/project/decisions/DEC\x1f0001.md",
            "viking://resources/project/decisions/DEC\x7f0001.md",
        ]
        for uri in control_uris:
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    validate_endpoint_uri(uri)

    def test_rejects_missing_filename(self) -> None:
        invalid_uris = [
            "viking://resources/project/.md",
            "viking://resources/project/decisions/.md",
        ]
        for uri in invalid_uris:
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    validate_endpoint_uri(uri)


class ValidateTopologyTests(unittest.TestCase):
    """Test directional category topology rules and endpoint constraints."""

    def test_produces_topology(self) -> None:
        primary = "viking://resources/project/research/auth.md"
        secondary = "viking://resources/project/decisions/DEC-0001.md"
        pair = validate_topology(primary, secondary, "produces/produced_from")
        self.assertEqual(pair, ("produces", "produced_from"))

        # Wrong primary: decision instead of research
        with self.assertRaises(ValueError):
            validate_topology(secondary, primary, "produces/produced_from")

        # Wrong secondary: domain instead of decision
        with self.assertRaises(ValueError):
            validate_topology(
                primary,
                "viking://resources/project/domains/auth.md",
                "produces/produced_from",
            )

    def test_supersedes_topology(self) -> None:
        primary = "viking://resources/project/decisions/DEC-0002.md"
        secondary = "viking://resources/project/decisions/DEC-0001.md"
        pair = validate_topology(primary, secondary, "supersedes/superseded_by")
        self.assertEqual(pair, ("supersedes", "superseded_by"))

        # Primary not decision
        with self.assertRaises(ValueError):
            validate_topology(
                "viking://resources/project/research/auth.md",
                secondary,
                "supersedes/superseded_by",
            )

        # Secondary not decision
        with self.assertRaises(ValueError):
            validate_topology(
                primary,
                "viking://resources/project/research/auth.md",
                "supersedes/superseded_by",
            )

    def test_promoted_to_topology(self) -> None:
        primary = "viking://resources/project/decisions/DEC-0001.md"
        arch_sec = "viking://resources/project/architecture/overview.md"
        domain_sec = "viking://resources/project/domains/auth.md"
        invar_sec = "viking://resources/project/invariants/safety.md"

        self.assertEqual(
            validate_topology(primary, arch_sec, "promoted_to/derived_from"),
            ("promoted_to", "derived_from"),
        )
        self.assertEqual(
            validate_topology(primary, domain_sec, "promoted_to/derived_from"),
            ("promoted_to", "derived_from"),
        )
        self.assertEqual(
            validate_topology(primary, invar_sec, "promoted_to/derived_from"),
            ("promoted_to", "derived_from"),
        )

        # Wrong primary: research
        with self.assertRaises(ValueError):
            validate_topology(
                "viking://resources/project/research/r.md",
                arch_sec,
                "promoted_to/derived_from",
            )

        # Wrong secondary: research or decision
        with self.assertRaises(ValueError):
            validate_topology(
                primary,
                "viking://resources/project/research/r.md",
                "promoted_to/derived_from",
            )
        with self.assertRaises(ValueError):
            validate_topology(
                primary,
                "viking://resources/project/decisions/DEC-0002.md",
                "promoted_to/derived_from",
            )

    def test_composes_topology(self) -> None:
        primary = "viking://resources/project/architecture/overview.md"
        secondary = "viking://resources/project/domains/core.md"
        self.assertEqual(
            validate_topology(primary, secondary, "composes/part_of"),
            ("composes", "part_of"),
        )

        # Wrong primary
        with self.assertRaises(ValueError):
            validate_topology(secondary, primary, "composes/part_of")

        # Wrong secondary: invariants
        with self.assertRaises(ValueError):
            validate_topology(
                primary,
                "viking://resources/project/invariants/inv.md",
                "composes/part_of",
            )

    def test_enforces_topology(self) -> None:
        primary = "viking://resources/project/invariants/safety.md"
        secondary = "viking://resources/project/domains/core.md"
        self.assertEqual(
            validate_topology(primary, secondary, "enforces/enforced_by"),
            ("enforces", "enforced_by"),
        )

        # Wrong primary: domains
        with self.assertRaises(ValueError):
            validate_topology(secondary, primary, "enforces/enforced_by")

        # Wrong secondary: architecture
        with self.assertRaises(ValueError):
            validate_topology(
                primary,
                "viking://resources/project/architecture/arch.md",
                "enforces/enforced_by",
            )

    def test_references_topology(self) -> None:
        primary = "viking://resources/project/research/r.md"
        secondary = "viking://resources/project/domains/core.md"
        self.assertEqual(
            validate_topology(primary, secondary, "references/referenced_by"),
            ("references", "referenced_by"),
        )

        # Any valid project resource to any other valid project resource
        p2 = "viking://resources/project/invariants/inv.md"
        s2 = "viking://resources/project/architecture/arch.md"
        self.assertEqual(
            validate_topology(p2, s2, "references/referenced_by"),
            ("references", "referenced_by"),
        )

    def test_rejects_identical_endpoints(self) -> None:
        uri = "viking://resources/project/decisions/DEC-0001.md"
        with self.assertRaises(ValueError) as ctx:
            validate_topology(uri, uri, "supersedes/superseded_by")
        self.assertIn("identical", str(ctx.exception).lower())

    def test_rejects_unknown_reason_pair(self) -> None:
        p = "viking://resources/project/decisions/DEC-0001.md"
        s = "viking://resources/project/decisions/DEC-0002.md"
        for invalid_pair in ["unknown/pair", "produces", "invalid", "", "foo/bar"]:
            with self.subTest(invalid_pair=invalid_pair):
                with self.assertRaises(ValueError):
                    validate_topology(p, s, invalid_pair)

    def test_rejects_invalid_endpoint_uris(self) -> None:
        with self.assertRaises(ValueError):
            validate_topology(
                "viking://resources/user/notes.md",
                "viking://resources/project/decisions/DEC-0001.md",
                "produces/produced_from",
            )
        with self.assertRaises(ValueError):
            validate_topology(
                "viking://resources/project/research/r.md",
                "viking://resources/project/decisions/*.md",
                "produces/produced_from",
            )


class SerializeRelationReasonTests(unittest.TestCase):
    """Test serialization of directional reason and description."""

    def test_serialize_valid(self) -> None:
        result = serialize_relation_reason("produces", "investigates auth options")
        self.assertEqual(result, "produces, investigates auth options")

    def test_serialize_trims_description(self) -> None:
        result = serialize_relation_reason("derived_from", "   changes quorum requirement   ")
        self.assertEqual(result, "derived_from, changes quorum requirement")

    def test_serialize_preserves_internal_commas(self) -> None:
        desc = "replaces DEC-0001, which is obsolete, per RFC-12"
        result = serialize_relation_reason("supersedes", desc)
        self.assertEqual(result, f"supersedes, {desc}")

    def test_serialize_rejects_empty_desc(self) -> None:
        for empty_desc in ["", "   ", "\t", "\n"]:
            with self.subTest(empty_desc=empty_desc):
                with self.assertRaises(ValueError):
                    serialize_relation_reason("produces", empty_desc)

    def test_serialize_rejects_control_characters(self) -> None:
        bad_descriptions = [
            "first line\nsecond line",
            "text with\rcarriage return",
            "text with\ttab",
            "null byte\x00 embedded",
            "control char \x1f test",
            "del char \x7f test",
        ]
        for bad in bad_descriptions:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    serialize_relation_reason("produces", bad)

    def test_serialize_rejects_unknown_reason(self) -> None:
        with self.assertRaises(ValueError):
            serialize_relation_reason("invalid_reason", "valid description")


class ParseRelationReasonTests(unittest.TestCase):
    """Test parsing of relation reason strings, split-once rule, and malformed handling."""

    def test_parse_valid_simple(self) -> None:
        raw = "derived_from, changes quorum requirement from 4 to 5"
        parsed = parse_relation_reason(raw)
        self.assertEqual(
            parsed,
            {"reason": "derived_from", "desc": "changes quorum requirement from 4 to 5"},
        )

    def test_parse_preserves_later_commas(self) -> None:
        raw = "supersedes, replaces DEC-0001, DEC-0002, and DEC-0003"
        parsed = parse_relation_reason(raw)
        self.assertEqual(
            parsed,
            {
                "reason": "supersedes",
                "desc": "replaces DEC-0001, DEC-0002, and DEC-0003",
            },
        )

    def test_parse_strips_reason_and_trims_desc(self) -> None:
        raw = "   produces   ,    initial research findings    "
        parsed = parse_relation_reason(raw)
        self.assertEqual(
            parsed,
            {"reason": "produces", "desc": "initial research findings"},
        )

    def test_parse_all_canonical_reasons(self) -> None:
        for reason in RECIPROCAL_PAIRS:
            raw = f"{reason}, valid description"
            parsed = parse_relation_reason(raw)
            self.assertEqual(parsed, {"reason": reason, "desc": "valid description"})

    def test_malformed_missing_delimiter(self) -> None:
        raw = "just plain text without comma"
        parsed = parse_relation_reason(raw)
        self.assertEqual(
            parsed,
            {"raw_reason": raw, "parse_error": PARSE_ERROR_MISSING_DELIMITER},
        )

        # Empty string also has no delimiter
        parsed_empty = parse_relation_reason("")
        self.assertEqual(
            parsed_empty,
            {"raw_reason": "", "parse_error": PARSE_ERROR_MISSING_DELIMITER},
        )

    def test_malformed_empty_fields(self) -> None:
        cases = [
            ", some description",
            "   , some description",
            "produces,",
            "produces,   ",
            ",",
            "   ,   ",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                parsed = parse_relation_reason(raw)
                self.assertEqual(
                    parsed,
                    {"raw_reason": raw, "parse_error": PARSE_ERROR_EMPTY_FIELD},
                )

    def test_malformed_unknown_reason(self) -> None:
        raw = "unknown_reason, valid description"
        parsed = parse_relation_reason(raw)
        self.assertEqual(
            parsed,
            {"raw_reason": raw, "parse_error": PARSE_ERROR_UNKNOWN_REASON},
        )

    def test_malformed_invalid_control_chars(self) -> None:
        cases = [
            "produces, multi\nline\ndesc",
            "produces, with\rcarriage return",
            "produces, with\ttab",
            "produces\x00, null byte in reason",
            "produces, null byte in desc\x00",
            "produces\t, tab in reason",
            "produces, del \x7f in desc",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                parsed = parse_relation_reason(raw)
                self.assertEqual(
                    parsed,
                    {
                        "raw_reason": raw,
                        "parse_error": PARSE_ERROR_INVALID_CONTROL_CHARS,
                    },
                )



class FakeOpenVikingClient:
    def __init__(
        self,
        stats: dict[str, dict[str, Any]] | None = None,
        relations: dict[str, list[dict[str, Any]]] | None = None,
    ):
        self.stats = stats or {}
        self.relations = relations or {}
        self.link_calls: list[tuple[str, str | list[str], str]] = []
        self.unlink_calls: list[tuple[str, str]] = []
        self.stat_calls: list[str] = []

    def stat_resource(self, uri: str) -> dict[str, Any]:
        self.stat_calls.append(uri)
        if uri not in self.stats:
            raise OpenVikingError(f"Resource '{uri}' not found", code="NOT_FOUND")
        return self.stats[uri]

    def get_relations(self, uri: str) -> list[dict[str, Any]]:
        return [dict(e) for e in self.relations.get(uri, [])]

    def link(self, from_uri: str, to_uris: str | list[str], reason: str = "") -> dict[str, Any]:
        self.link_calls.append((from_uri, to_uris, reason))
        targets = [to_uris] if isinstance(to_uris, str) else to_uris
        for t in targets:
            self.relations.setdefault(from_uri, []).append({"uri": t, "reason": reason})
        return {"ok": True}

    def unlink(self, from_uri: str, to_uri: str) -> dict[str, Any]:
        self.unlink_calls.append((from_uri, to_uri))
        if from_uri in self.relations:
            self.relations[from_uri] = [
                e for e in self.relations[from_uri] if e.get("uri") != to_uri
            ]
        return {"ok": True}


class ReciprocalRelationsTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.primary = "viking://resources/project/research/auth-rfc.md"
        self.secondary = "viking://resources/project/decisions/DEC-0001.md"
        self.reason_pair = "produces/produced_from"
        self.desc = "investigates auth options"
        self.primary_serialized = "produces, investigates auth options"
        self.secondary_serialized = "produced_from, investigates auth options"

        self.stats = {
            self.primary: {"name": "auth-rfc.md", "isDir": False},
            self.secondary: {"name": "DEC-0001.md", "isDir": False},
        }

    def test_snapshot_relations_extracts_links(self) -> None:
        client = FakeOpenVikingClient(
            stats=self.stats,
            relations={
                self.primary: [
                    {"uri": self.secondary, "reason": "produces, auth"},
                    {"uri": "viking://resources/project/decisions/DEC-0002.md", "reason": "other"},
                ],
                self.secondary: [
                    {"uri": self.primary, "reason": "produced_from, auth"},
                ],
            },
        )
        p_links, s_links = snapshot_relations(client, self.primary, self.secondary)
        self.assertEqual(p_links, [{"uri": self.secondary, "reason": "produces, auth"}])
        self.assertEqual(s_links, [{"uri": self.primary, "reason": "produced_from, auth"}])

    def test_snapshot_relations_rejects_identical_or_invalid_uris(self) -> None:
        client = FakeOpenVikingClient(stats=self.stats)
        with self.assertRaises(ValueError):
            snapshot_relations(client, self.primary, self.primary)
        with self.assertRaises(ValueError):
            snapshot_relations(client, "invalid-uri", self.secondary)

    def test_set_reciprocal_relation_stat_failure_or_directory(self) -> None:
        # 1. Primary does not exist
        client = FakeOpenVikingClient(
            stats={self.secondary: {"name": "DEC-0001.md", "isDir": False}}
        )
        res = set_reciprocal_relation(
            client, self.primary, self.secondary, self.reason_pair, self.desc
        )
        self.assertFalse(res["ok"])
        self.assertFalse(res["changed"])
        self.assertIn("not found", res["error"].lower())

        # 2. Secondary is a directory
        client_dir = FakeOpenVikingClient(
            stats={
                self.primary: {"name": "auth-rfc.md", "isDir": False},
                self.secondary: {"name": "decisions", "isDir": True},
            }
        )
        res_dir = set_reciprocal_relation(
            client_dir, self.primary, self.secondary, self.reason_pair, self.desc
        )
        self.assertFalse(res_dir["ok"])
        self.assertFalse(res_dir["changed"])
        self.assertIn("directory", res_dir["error"].lower())

    def test_set_reciprocal_relation_invalid_topology_or_desc(self) -> None:
        client = FakeOpenVikingClient(stats=self.stats)
        # Invalid topology (wrong direction)
        res = set_reciprocal_relation(
            client, self.secondary, self.primary, self.reason_pair, self.desc
        )
        self.assertFalse(res["ok"])
        self.assertFalse(res["changed"])

        # Invalid desc with control chars
        res_ctrl = set_reciprocal_relation(
            client, self.primary, self.secondary, self.reason_pair, "bad\ndesc"
        )
        self.assertFalse(res_ctrl["ok"])
        self.assertFalse(res_ctrl["changed"])

    def test_set_reciprocal_relation_noop_when_exact_exists(self) -> None:
        client = FakeOpenVikingClient(
            stats=self.stats,
            relations={
                self.primary: [{"uri": self.secondary, "reason": self.primary_serialized}],
                self.secondary: [{"uri": self.primary, "reason": self.secondary_serialized}],
            },
        )
        res = set_reciprocal_relation(
            client, self.primary, self.secondary, self.reason_pair, self.desc
        )
        self.assertTrue(res["ok"])
        self.assertFalse(res["changed"])
        self.assertEqual(len(client.unlink_calls), 0)
        self.assertEqual(len(client.link_calls), 0)

    def test_set_reciprocal_relation_fresh_creation(self) -> None:
        client = FakeOpenVikingClient(stats=self.stats, relations={})
        res = set_reciprocal_relation(
            client, self.primary, self.secondary, self.reason_pair, self.desc
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["changed"])
        # Verified state on client
        p_links, s_links = snapshot_relations(client, self.primary, self.secondary)
        self.assertEqual(p_links, [{"uri": self.secondary, "reason": self.primary_serialized}])
        self.assertEqual(s_links, [{"uri": self.primary, "reason": self.secondary_serialized}])

    def test_set_reciprocal_relation_drift_cleanup_and_convergence(self) -> None:
        # Pre-call state has stale reasons and duplicates
        client = FakeOpenVikingClient(
            stats=self.stats,
            relations={
                self.primary: [
                    {"uri": self.secondary, "reason": "produces, old"},
                    {"uri": self.secondary, "reason": "produces, duplicate"},
                ],
                self.secondary: [
                    {"uri": self.primary, "reason": "produced_from, stale"},
                ],
            },
        )
        res = set_reciprocal_relation(
            client, self.primary, self.secondary, self.reason_pair, self.desc
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["changed"])

        # Unlink was called for both endpoints
        self.assertIn((self.primary, self.secondary), client.unlink_calls)
        self.assertIn((self.secondary, self.primary), client.unlink_calls)

        # Verified state on client has exact single entry in each direction
        p_links, s_links = snapshot_relations(client, self.primary, self.secondary)
        self.assertEqual(p_links, [{"uri": self.secondary, "reason": self.primary_serialized}])
        self.assertEqual(s_links, [{"uri": self.primary, "reason": self.secondary_serialized}])

    def test_set_reciprocal_relation_rollback_on_second_link_failure(self) -> None:
        snapshot_primary = [{"uri": self.secondary, "reason": "produces, initial"}]
        snapshot_secondary = [{"uri": self.primary, "reason": "produced_from, initial"}]

        client = FakeOpenVikingClient(
            stats=self.stats,
            relations={
                self.primary: list(snapshot_primary),
                self.secondary: list(snapshot_secondary),
            },
        )

        real_link = client.link

        def link_side_effect(from_uri: str, to_uris: str | list[str], reason: str = ""):
            if from_uri == self.secondary and reason == self.secondary_serialized:
                raise OpenVikingError("Simulated backend crash on secondary link")
            return real_link(from_uri, to_uris, reason)

        client.link = link_side_effect  # type: ignore[method-assign]

        res = set_reciprocal_relation(
            client, self.primary, self.secondary, self.reason_pair, self.desc
        )
        self.assertFalse(res["ok"])
        self.assertFalse(res["changed"])
        self.assertTrue(res["state_restored"])
        self.assertIn("Simulated backend crash", res["error"])

        # Client state was restored back to snapshot
        p_links, s_links = snapshot_relations(client, self.primary, self.secondary)
        self.assertEqual(p_links, snapshot_primary)
        self.assertEqual(s_links, snapshot_secondary)

    def test_set_reciprocal_relation_rollback_on_verification_failure(self) -> None:
        client = FakeOpenVikingClient(stats=self.stats, relations={})

        real_get = client.get_relations
        read_count = 0

        def flaky_get_relations(uri: str):
            nonlocal read_count
            read_count += 1
            # Step 1 is snapshot (calls 1 and 2), Step 4 is verification (calls 3 and 4)
            if read_count == 4 and uri == self.secondary:
                # Return empty list simulating backend drop / corruption
                return []
            return real_get(uri)

        client.get_relations = flaky_get_relations  # type: ignore[method-assign]

        res = set_reciprocal_relation(
            client, self.primary, self.secondary, self.reason_pair, self.desc
        )
        self.assertFalse(res["ok"])
        self.assertFalse(res["changed"])
        self.assertTrue(res["state_restored"])

        # Persistent state matches pre-call snapshot (which was empty)
        client.get_relations = real_get  # type: ignore[method-assign]
        p_links, s_links = snapshot_relations(client, self.primary, self.secondary)
        self.assertEqual(p_links, [])
        self.assertEqual(s_links, [])

    def test_set_reciprocal_relation_compensation_failure_reports_recovery(self) -> None:
        client = FakeOpenVikingClient(
            stats=self.stats,
            relations={
                self.primary: [{"uri": self.secondary, "reason": "produces, old"}],
            },
        )

        # Trigger failure on secondary link, and fail compensation relink
        call_count = 0

        def failing_link(from_uri: str, to_uris: str | list[str], reason: str = ""):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Second link fails
                raise OpenVikingError("Secondary link failure")
            if call_count > 2:
                # Compensation link fails
                raise OpenVikingError("Restore relink failed catastrophically")
            targets = [to_uris] if isinstance(to_uris, str) else to_uris
            for t in targets:
                client.relations.setdefault(from_uri, []).append({"uri": t, "reason": reason})
            return {"ok": True}

        client.link = failing_link  # type: ignore[method-assign]

        res = set_reciprocal_relation(
            client, self.primary, self.secondary, self.reason_pair, self.desc
        )
        self.assertFalse(res["ok"])
        self.assertTrue(res["changed"])
        self.assertFalse(res["state_restored"])
        self.assertIn("recovery", res)
        recovery = res["recovery"]
        self.assertIn("current_state", recovery)
        self.assertIn("pre_call_state", recovery)
        self.assertIn("desired_state", recovery)
        self.assertTrue(recovery["secondary_failed"])

    def test_remove_reciprocal_relation_noop_when_absent(self) -> None:
        client = FakeOpenVikingClient(stats=self.stats, relations={})
        res = remove_reciprocal_relation(client, self.primary, self.secondary)
        self.assertTrue(res["ok"])
        self.assertFalse(res["changed"])
        self.assertEqual(len(client.unlink_calls), 0)

    def test_remove_reciprocal_relation_success(self) -> None:
        client = FakeOpenVikingClient(
            stats=self.stats,
            relations={
                self.primary: [
                    {"uri": self.secondary, "reason": self.primary_serialized},
                    {"uri": self.secondary, "reason": "drift"},
                ],
                self.secondary: [
                    {"uri": self.primary, "reason": self.secondary_serialized},
                ],
            },
        )
        res = remove_reciprocal_relation(client, self.primary, self.secondary)
        self.assertTrue(res["ok"])
        self.assertTrue(res["changed"])
        p_links, s_links = snapshot_relations(client, self.primary, self.secondary)
        self.assertEqual(p_links, [])
        self.assertEqual(s_links, [])

    def test_remove_reciprocal_relation_rollback_on_failure(self) -> None:
        pre_primary = [{"uri": self.secondary, "reason": self.primary_serialized}]
        pre_secondary = [{"uri": self.primary, "reason": self.secondary_serialized}]
        client = FakeOpenVikingClient(
            stats=self.stats,
            relations={
                self.primary: list(pre_primary),
                self.secondary: list(pre_secondary),
            },
        )

        real_unlink = client.unlink

        def failing_unlink(from_uri: str, to_uri: str):
            if from_uri == self.secondary:
                raise OpenVikingError("Unlink error on secondary")
            return real_unlink(from_uri, to_uri)

        client.unlink = failing_unlink  # type: ignore[method-assign]

        res = remove_reciprocal_relation(client, self.primary, self.secondary)
        self.assertFalse(res["ok"])
        self.assertFalse(res["changed"])
        self.assertTrue(res["state_restored"])
        self.assertIn("Unlink error on secondary", res["error"])

        # Client relations restored
        p_links, s_links = snapshot_relations(client, self.primary, self.secondary)
        self.assertEqual(p_links, pre_primary)
        self.assertEqual(s_links, pre_secondary)

    def test_remove_reciprocal_relation_compensation_failure(self) -> None:
        client = FakeOpenVikingClient(
            stats=self.stats,
            relations={
                self.primary: [{"uri": self.secondary, "reason": self.primary_serialized}],
                self.secondary: [{"uri": self.primary, "reason": self.secondary_serialized}],
            },
        )

        real_unlink = client.unlink

        def failing_unlink(from_uri: str, to_uri: str):
            if from_uri == self.secondary:
                raise OpenVikingError("Initial unlink failed on secondary")
            return real_unlink(from_uri, to_uri)

        def failing_link(from_uri: str, to_uris: str | list[str], reason: str = ""):
            raise OpenVikingError("Compensation relink failed")

        client.unlink = failing_unlink  # type: ignore[method-assign]
        client.link = failing_link  # type: ignore[method-assign]

        res = remove_reciprocal_relation(client, self.primary, self.secondary)
        self.assertFalse(res["ok"])
        self.assertTrue(res["changed"])
        self.assertFalse(res["state_restored"])
        self.assertIn("recovery", res)

    def test_remove_reciprocal_relation_invalid_uri_or_identical(self) -> None:
        client = FakeOpenVikingClient(stats=self.stats)
        res_ident = remove_reciprocal_relation(client, self.primary, self.primary)
        self.assertFalse(res_ident["ok"])
        self.assertFalse(res_ident["changed"])

        res_inv = remove_reciprocal_relation(client, "not-a-viking-uri", self.secondary)
        self.assertFalse(res_inv["ok"])
        self.assertFalse(res_inv["changed"])


if __name__ == "__main__":
    unittest.main()

