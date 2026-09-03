from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

from relation_domain import (  # noqa: E402
    RECIPROCAL_PAIRS,
    PARSE_ERROR_EMPTY_FIELD,
    PARSE_ERROR_INVALID_CONTROL_CHARS,
    PARSE_ERROR_MISSING_DELIMITER,
    PARSE_ERROR_UNKNOWN_REASON,
    parse_relation_reason,
    serialize_relation_reason,
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


if __name__ == "__main__":
    unittest.main()
