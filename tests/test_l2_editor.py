from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

from l2_editor import apply_section_edit  # noqa: E402


class L2EditorTests(unittest.TestCase):
    def test_edit_middle_section_same_level_following(self) -> None:
        doc = (
            "# Document Title\n\n"
            "## Section 1\n"
            "Old section 1 text.\n\n"
            "### Subsection 1.1\n"
            "Old sub text.\n\n"
            "## Section 2\n"
            "Section 2 content.\n"
        )
        replacement = (
            "New section 1 text.\n\n"
            "### New Subsection 1.1\n"
            "New sub text."
        )
        result = apply_section_edit(doc, "## Section 1", replacement)
        expected = (
            "# Document Title\n\n"
            "## Section 1\n"
            "New section 1 text.\n\n"
            "### New Subsection 1.1\n"
            "New sub text.\n\n"
            "## Section 2\n"
            "Section 2 content.\n"
        )
        self.assertEqual(result, expected)

    def test_edit_middle_section_higher_level_following(self) -> None:
        doc = (
            "# Top Level\n\n"
            "### Sub Section\n"
            "Sub content.\n\n"
            "## Sibling Level\n"
            "Sibling content.\n"
        )
        replacement = "Updated sub content."
        result = apply_section_edit(doc, "### Sub Section", replacement)
        expected = (
            "# Top Level\n\n"
            "### Sub Section\n"
            "Updated sub content.\n\n"
            "## Sibling Level\n"
            "Sibling content.\n"
        )
        self.assertEqual(result, expected)

    def test_edit_last_section_before_eof(self) -> None:
        doc = (
            "# Document Title\n\n"
            "## Section 1\n"
            "Section 1 content.\n\n"
            "## Section 2\n"
            "Old section 2 content.\n"
        )
        replacement = "New section 2 content."
        result = apply_section_edit(doc, "## Section 2", replacement)
        expected = (
            "# Document Title\n\n"
            "## Section 1\n"
            "Section 1 content.\n\n"
            "## Section 2\n"
            "New section 2 content.\n"
        )
        self.assertEqual(result, expected)

    def test_edit_last_section_without_trailing_newline_at_eof(self) -> None:
        doc = (
            "# Document Title\n\n"
            "## Section 1\n"
            "Section 1 content.\n\n"
            "## Section 2\n"
            "Old section 2 without newline"
        )
        replacement = "New section 2 content."
        result = apply_section_edit(doc, "## Section 2", replacement)
        expected = (
            "# Document Title\n\n"
            "## Section 1\n"
            "Section 1 content.\n\n"
            "## Section 2\n"
            "New section 2 content.\n"
        )
        self.assertEqual(result, expected)

    def test_preserve_content_outside_section_byte_for_byte(self) -> None:
        prefix = (
            "---\n"
            "id: DEC-042\n"
            "status: implemented\n"
            "tags: [foo, bar]\n"
            "---\n\n"
            "# Architecture Invariants\n\n"
            "Preceding notes with special chars: @#$%^&*() and \t tabs.\n\n"
        )
        suffix = (
            "## Next Section\n"
            "Next notes with preserved formatting:  \n"
            "Line with two trailing spaces.\n"
        )
        doc = f"{prefix}## Target Section\nOld body\n\n{suffix}"
        result = apply_section_edit(doc, "## Target Section", "Replacement body.")

        self.assertTrue(result.startswith(prefix))
        self.assertTrue(result.endswith(suffix))
        middle = result[len(prefix) : len(result) - len(suffix)]
        self.assertEqual(middle, "## Target Section\nReplacement body.\n\n")

    def test_ignore_headings_inside_fenced_code_blocks(self) -> None:
        doc = (
            "# Real Heading\n\n"
            "## Section 1\n"
            "Here is a code fence with headings:\n"
            "```markdown\n"
            "## Section 1\n"
            "## Section 2\n"
            "# Another Fake Heading\n"
            "```\n"
            "Code fence closed.\n\n"
            "## Section 2\n"
            "Real Section 2.\n"
        )
        # 1. Matching ## Section 1 outside fence must succeed uniquely
        result = apply_section_edit(doc, "## Section 1", "New Section 1 body.")
        expected = (
            "# Real Heading\n\n"
            "## Section 1\n"
            "New Section 1 body.\n\n"
            "## Section 2\n"
            "Real Section 2.\n"
        )
        self.assertEqual(result, expected)

        # 2. Searching for heading that only exists inside fence must raise ValueError
        with self.assertRaisesRegex(ValueError, "Section heading not found:"):
            apply_section_edit(doc, "# Another Fake Heading", "New body")

    def test_ignore_headings_inside_tilde_fenced_code_blocks(self) -> None:
        doc = (
            "# Real Heading\n\n"
            "## Section 1\n"
            "~~~python\n"
            "## Section 1 inside tilde\n"
            "## Section 2\n"
            "~~~\n"
            "More text.\n\n"
            "## Section 2\n"
            "Real Section 2.\n"
        )
        result = apply_section_edit(doc, "## Section 1", "Replacement text.")
        expected = (
            "# Real Heading\n\n"
            "## Section 1\n"
            "Replacement text.\n\n"
            "## Section 2\n"
            "Real Section 2.\n"
        )
        self.assertEqual(result, expected)

    def test_nested_code_fences_with_different_lengths(self) -> None:
        doc = (
            "## Outer Section\n"
            "````markdown\n"
            "```\n"
            "## Outer Section\n"
            "```\n"
            "````\n"
            "End of code.\n\n"
            "## Next Section\n"
            "Next content.\n"
        )
        result = apply_section_edit(doc, "## Outer Section", "Replaced.")
        expected = (
            "## Outer Section\n"
            "Replaced.\n\n"
            "## Next Section\n"
            "Next content.\n"
        )
        self.assertEqual(result, expected)

    def test_reject_missing_heading(self) -> None:
        doc = "# Doc\n\n## Existing\nContent\n"
        with self.assertRaisesRegex(ValueError, "Section heading not found:"):
            apply_section_edit(doc, "## Nonexistent", "Body")

        with self.assertRaisesRegex(ValueError, "Section heading not found:"):
            apply_section_edit(doc, "Not a heading", "Body")

    def test_reject_ambiguous_duplicate_heading(self) -> None:
        doc = (
            "# Doc\n\n"
            "## Duplicate Section\n"
            "First content.\n\n"
            "## Duplicate Section\n"
            "Second content.\n"
        )
        with self.assertRaisesRegex(
            ValueError, r"Ambiguous section heading \(multiple matches\):"
        ):
            apply_section_edit(doc, "## Duplicate Section", "New body")

    def test_reject_replacement_content_with_equal_heading(self) -> None:
        doc = "# Doc\n\n## Target Section\nContent\n\n## Other\nOther\n"
        replacement = "Some text\n\n## Equal Heading\nMore text"
        with self.assertRaisesRegex(
            ValueError,
            "Replacement content contains heading of equal or higher level:",
        ):
            apply_section_edit(doc, "## Target Section", replacement)

    def test_reject_replacement_content_with_higher_heading(self) -> None:
        doc = "# Doc\n\n## Target Section\nContent\n\n## Other\nOther\n"
        replacement = "Some text\n\n# Higher Heading\nMore text"
        with self.assertRaisesRegex(
            ValueError,
            "Replacement content contains heading of equal or higher level:",
        ):
            apply_section_edit(doc, "## Target Section", replacement)

    def test_allow_deeper_headings_in_replacement_content(self) -> None:
        doc = "# Doc\n\n## Target Section\nContent\n\n## Other\nOther\n"
        replacement = (
            "Intro\n\n"
            "### Deeper Heading 3\n"
            "Details\n\n"
            "#### Deeper Heading 4\n"
            "More details"
        )
        result = apply_section_edit(doc, "## Target Section", replacement)
        expected = (
            "# Doc\n\n"
            "## Target Section\n"
            "Intro\n\n"
            "### Deeper Heading 3\n"
            "Details\n\n"
            "#### Deeper Heading 4\n"
            "More details\n\n"
            "## Other\n"
            "Other\n"
        )
        self.assertEqual(result, expected)

    def test_allow_equal_or_higher_heading_inside_replacement_code_fence(
        self,
    ) -> None:
        doc = "# Doc\n\n## Target Section\nContent\n\n## Other\nOther\n"
        replacement = (
            "Intro\n\n"
            "```python\n"
            "# Comment level 1\n"
            "## Comment level 2\n"
            "```\n"
            "Outro"
        )
        result = apply_section_edit(doc, "## Target Section", replacement)
        expected = (
            "# Doc\n\n"
            "## Target Section\n"
            "Intro\n\n"
            "```python\n"
            "# Comment level 1\n"
            "## Comment level 2\n"
            "```\n"
            "Outro\n\n"
            "## Other\n"
            "Other\n"
        )
        self.assertEqual(result, expected)

    def test_allow_empty_replacement_content_with_following_section(self) -> None:
        doc = (
            "# Doc\n\n"
            "## Target Section\n"
            "Old content.\n\n"
            "## Next Section\n"
            "Next content.\n"
        )
        result = apply_section_edit(doc, "## Target Section", "")
        expected = (
            "# Doc\n\n"
            "## Target Section\n\n"
            "## Next Section\n"
            "Next content.\n"
        )
        self.assertEqual(result, expected)

        # Whitespace-only replacement content
        result_ws = apply_section_edit(doc, "## Target Section", "   \n\n   ")
        self.assertEqual(result_ws, expected)

    def test_allow_empty_replacement_content_at_eof(self) -> None:
        doc = (
            "# Doc\n\n"
            "## Target Section\n"
            "Old content to be emptied.\n"
        )
        result = apply_section_edit(doc, "## Target Section", "")
        expected = "# Doc\n\n## Target Section\n"
        self.assertEqual(result, expected)

        result_ws = apply_section_edit(doc, "## Target Section", "\n\n   \t\n")
        self.assertEqual(result_ws, expected)

    def test_normalization_of_newlines(self) -> None:
        # Replacement content with redundant leading/trailing whitespace
        doc = (
            "## Section A\n"
            "Old text.\n\n\n"
            "## Section B\n"
            "Next text.\n"
        )
        replacement = "\n\n\nNew section text.\n\n\n"
        result = apply_section_edit(doc, "## Section A", replacement)
        expected = (
            "## Section A\n"
            "New section text.\n\n"
            "## Section B\n"
            "Next text.\n"
        )
        self.assertEqual(result, expected)

    def test_heading_selector_trimming(self) -> None:
        doc = (
            "# Doc\n\n"
            "## Section With Whitespace\n"
            "Old text.\n\n"
            "## Other\n"
            "Other text.\n"
        )
        selector = "  \n  ## Section With Whitespace  \t "
        result = apply_section_edit(doc, selector, "Updated text.")
        expected = (
            "# Doc\n\n"
            "## Section With Whitespace\n"
            "Updated text.\n\n"
            "## Other\n"
            "Other text.\n"
        )
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
