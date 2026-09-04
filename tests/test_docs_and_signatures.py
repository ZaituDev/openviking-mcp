"""
Tests verifying docstrings, tool signatures, and documentation files.

Ensures no stale concepts (5-step promotion, .overview.md/.abstract.md writes,
audit linking, related_invariant_uris, source_research_uris, concluded_from/implements)
remain in docstrings, relation-tool-design.md, or README.md.
"""

from __future__ import annotations

import inspect
from pathlib import Path
import unittest

import braining_mcp.server as braining_server
import retrieval_mcp.server as retrieval_server
import superpowers_mcp.server as superpowers_server

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_DOCSTRING_SUBSTRINGS = [
    ".overview.md",
    ".abstract.md",
    "5 promotion steps",
    "5-step",
    "related_invariant_uris",
    "source_research_uris",
]

FORBIDDEN_README_SUBSTRINGS = [
    ".overview.md",
    ".abstract.md",
    "5 promotion steps",
    "5-step",
    "related_invariant_uris",
    "source_research_uris",
    "concluded_from",
    "implements",
]


class TestDocstringsAndSignatures(unittest.TestCase):
    """Test tool signatures and docstrings across MCP servers."""

    def test_signatures(self) -> None:
        """Verify tool signatures conform to staged promotion specification."""
        # promote_decision
        p_sig = inspect.signature(superpowers_server.promote_decision)
        self.assertEqual(
            list(p_sig.parameters.keys()),
            [
                "dec_uri",
                "action",
                "target",
                "target_path",
                "write_mode",
                "content",
                "section",
                "primary",
                "secondary",
                "reason_pair",
                "desc",
            ],
        )

        # write_decision
        wd_sig = inspect.signature(braining_server.write_decision)
        self.assertEqual(
            list(wd_sig.parameters.keys()),
            [
                "context",
                "problem",
                "alternatives",
                "decision",
                "consequences",
                "source_research",
            ],
        )
        self.assertNotIn("source_research_uris", wd_sig.parameters)

        # supersede_decision
        sd_sig = inspect.signature(braining_server.supersede_decision)
        self.assertEqual(
            list(sd_sig.parameters.keys()),
            [
                "old_dec_uri",
                "context",
                "problem",
                "alternatives",
                "decision",
                "consequences",
                "relation_desc",
            ],
        )

        # write_audit
        wa_sig = inspect.signature(superpowers_server.write_audit)
        self.assertEqual(
            list(wa_sig.parameters.keys()),
            ["category", "title", "content"],
        )
        self.assertNotIn("related_invariant_uris", wa_sig.parameters)

        # list_relations
        lr_sig = inspect.signature(retrieval_server.list_relations)
        self.assertEqual(
            list(lr_sig.parameters.keys()),
            ["uri"],
        )

    def test_tool_docstrings_no_forbidden_substrings(self) -> None:
        """Verify tool docstrings contain no forbidden stale substrings."""
        tools = {
            "promote_decision": superpowers_server.promote_decision,
            "write_decision": braining_server.write_decision,
            "supersede_decision": braining_server.supersede_decision,
            "write_audit": superpowers_server.write_audit,
            "list_relations": retrieval_server.list_relations,
        }

        for tool_name, tool_fn in tools.items():
            doc = tool_fn.__doc__
            self.assertIsNotNone(doc, f"Tool {tool_name} must have a docstring")
            assert doc is not None
            for forbidden in FORBIDDEN_DOCSTRING_SUBSTRINGS:
                self.assertNotIn(
                    forbidden,
                    doc,
                    f"Tool '{tool_name}' docstring contains forbidden substring: '{forbidden}'",
                )

    def test_module_docstrings_no_stale_terms(self) -> None:
        """Verify module docstrings do not reference stale concepts."""
        modules = {
            "superpowers_mcp": superpowers_server,
            "braining_mcp": braining_server,
            "retrieval_mcp": retrieval_server,
        }
        for mod_name, mod in modules.items():
            doc = mod.__doc__ or ""
            for forbidden in FORBIDDEN_DOCSTRING_SUBSTRINGS:
                self.assertNotIn(
                    forbidden,
                    doc,
                    f"Module '{mod_name}' docstring contains forbidden substring: '{forbidden}'",
                )
            self.assertNotIn(
                "concluded_from",
                doc,
                f"Module '{mod_name}' docstring contains stale 'concluded_from'",
            )

    def test_runtime_session_id_docstring_preserved(self) -> None:
        """Verify reserved phrase on runtime_session_id is intact."""
        log_ctx_doc = superpowers_server.log_context_used.__doc__ or ""
        search_ctx_doc = retrieval_server.search_project_context.__doc__ or ""
        phrase = "reserved for the client integration"
        self.assertIn(phrase, log_ctx_doc)
        self.assertIn(phrase, search_ctx_doc)

    def test_tool_docstrings_describe_new_behaviors(self) -> None:
        """Verify docstrings accurately detail the updated operations."""
        # promote_decision docstring
        p_doc = superpowers_server.promote_decision.__doc__ or ""
        self.assertIn("edit_l2", p_doc)
        self.assertIn("set_relation", p_doc)
        self.assertIn("remove_relation", p_doc)
        self.assertIn("finalize", p_doc)
        self.assertIn("implemented", p_doc)

        # write_decision docstring
        wd_doc = braining_server.write_decision.__doc__ or ""
        self.assertIn("source_research", wd_doc)
        self.assertIn("produces/produced_from", wd_doc)

        # supersede_decision docstring
        sd_doc = braining_server.supersede_decision.__doc__ or ""
        self.assertIn("relation_desc", sd_doc)
        self.assertIn("supersedes/superseded_by", sd_doc)

        # list_relations docstring
        lr_doc = retrieval_server.list_relations.__doc__ or ""
        self.assertIn("flat list", lr_doc)
        self.assertIn("raw_reason", lr_doc)
        self.assertIn("parse_error", lr_doc)


class TestDocumentationFiles(unittest.TestCase):
    """Test relation-tool-design.md and README.md content and accuracy."""

    def setUp(self) -> None:
        self.design_md_path = REPO_ROOT / "superpowers_mcp" / "relation-tool-design.md"
        self.readme_md_path = REPO_ROOT / "README.md"

    def test_relation_tool_design_spec(self) -> None:
        """Verify relation-tool-design.md is an authoritative specification."""
        self.assertTrue(self.design_md_path.exists())
        content = self.design_md_path.read_text(encoding="utf-8")

        # 6 reciprocal pairs
        expected_pairs = [
            ("produces", "produced_from"),
            ("supersedes", "superseded_by"),
            ("promoted_to", "derived_from"),
            ("composes", "part_of"),
            ("enforces", "enforced_by"),
            ("references", "referenced_by"),
        ]
        for primary_reason, secondary_reason in expected_pairs:
            self.assertIn(primary_reason, content)
            self.assertIn(secondary_reason, content)

        # Storage format & delimiter
        self.assertIn("<directional_reason>, <trimmed description>", content)
        self.assertIn("split", content.lower())

        # Reciprocal transactions and compensation
        self.assertIn("compensation", content.lower())
        self.assertIn("verification", content.lower())

        # Staged promotion actions
        self.assertIn("edit_l2", content)
        self.assertIn("set_relation", content)
        self.assertIn("remove_relation", content)
        self.assertIn("finalize", content)
        self.assertIn("implemented", content)

        # First-party writers and retrieval
        self.assertIn("write_decision", content)
        self.assertIn("supersede_decision", content)
        self.assertIn("write_audit", content)
        self.assertIn("list_relations", content)

        # No stale terms
        for forbidden in FORBIDDEN_README_SUBSTRINGS:
            self.assertNotIn(
                forbidden,
                content,
                f"relation-tool-design.md contains forbidden substring: '{forbidden}'",
            )

    def test_readme_docs(self) -> None:
        """Verify README.md reflects updated tools and signatures."""
        self.assertTrue(self.readme_md_path.exists())
        content = self.readme_md_path.read_text(encoding="utf-8")

        # No stale substrings
        for forbidden in FORBIDDEN_README_SUBSTRINGS:
            self.assertNotIn(
                forbidden,
                content,
                f"README.md contains forbidden substring: '{forbidden}'",
            )

        # Covers new tools and staged promotion
        self.assertIn("promote_decision", content)
        self.assertIn("write_decision", content)
        self.assertIn("supersede_decision", content)
        self.assertIn("write_audit", content)
        self.assertIn("list_relations", content)

        # Mentions staged promotion actions
        self.assertIn("edit_l2", content)
        self.assertIn("set_relation", content)
        self.assertIn("remove_relation", content)
        self.assertIn("finalize", content)


if __name__ == "__main__":
    unittest.main()
