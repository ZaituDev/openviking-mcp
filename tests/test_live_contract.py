from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

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

from ov_client import OpenVikingClient, OpenVikingError
from relation_domain import (
    remove_reciprocal_relation,
    set_reciprocal_relation,
    snapshot_relations,
)
import retrieval_mcp.server as retrieval_server


@unittest.skipUnless(os.environ.get("OPENVIKING_LIVE_TESTS") == "1", "Live tests disabled")
class TestLiveOpenVikingContract(unittest.TestCase):
    """Opt-in live integration contract suite against a running OpenViking server."""

    def setUp(self) -> None:
        self.client = OpenVikingClient()
        self.created_uris: set[str] = set()

    def tearDown(self) -> None:
        for uri in list(self.created_uris):
            try:
                if self.client.exists(uri):
                    self.client.delete_resource(uri)
            except Exception:
                pass
        self.created_uris.clear()
        self.client.close()

    def _create_disposable_resource(
        self, content: str = "# Disposable Test Resource\n", suffix: str = "doc.md"
    ) -> str:
        """Create a disposable markdown resource with a unique UUID."""
        unique_id = uuid.uuid4().hex
        uri = f"viking://resources/project/live_test_{unique_id}_{suffix}"
        self.created_uris.add(uri)
        self.client.write(uri, content, mode="create")
        return uri

    def test_stat_file_versus_directory(self) -> None:
        """Verify stat distinguishes files from directories and returns expected metadata."""
        # 1. Directory stat
        dir_uri = "viking://resources/project/"
        dir_stat = self.client.stat_resource(dir_uri)
        self.assertTrue(dir_stat.get("isDir"))
        self.assertIsInstance(dir_stat.get("mode"), int)
        self.assertIsInstance(dir_stat.get("size"), int)
        self.assertEqual(dir_stat.get("name"), "project")

        # Exists checks for directory
        self.assertTrue(self.client.exists(dir_uri, is_file=False))
        self.assertFalse(self.client.exists(dir_uri, is_file=True))

        # 2. File stat
        content = "# Stat Test\nLive test file content.\n"
        file_uri = self._create_disposable_resource(content=content, suffix="stat.md")
        file_stat = self.client.stat_resource(file_uri)
        self.assertFalse(file_stat.get("isDir"))
        self.assertIsInstance(file_stat.get("mode"), int)
        self.assertEqual(file_stat.get("size"), len(content.encode("utf-8")))
        self.assertTrue(file_stat.get("name", "").endswith("stat.md"))

        # Exists checks for file
        self.assertTrue(self.client.exists(file_uri, is_file=False))
        self.assertTrue(self.client.exists(file_uri, is_file=True))

    def test_create_read_update_delete_round_trip(self) -> None:
        """Verify create, read, update, and delete round trip on disposable resource."""
        initial_content = "# Live Round Trip\nInitial test content."
        uri = self._create_disposable_resource(content=initial_content, suffix="crud.md")

        # 1. Exists and Read
        self.assertTrue(self.client.exists(uri))
        read_content = self.client.read(uri)
        self.assertEqual(read_content, initial_content)

        # 2. Update via replace mode
        updated_content = "# Live Round Trip\nUpdated test content with modifications."
        write_res = self.client.write(uri, updated_content, mode="replace")
        self.assertTrue(write_res.get("content_updated"))
        self.assertEqual(self.client.read(uri), updated_content)

        # 3. Delete
        del_res = self.client.delete_resource(uri)
        self.assertIsInstance(del_res, dict)
        self.assertFalse(self.client.exists(uri))
        self.created_uris.discard(uri)

        # Verify reading deleted resource raises OpenVikingError
        with self.assertRaises(OpenVikingError):
            self.client.read(uri)

    def test_native_link_and_unlink_round_trip(self) -> None:
        """Verify OpenVikingClient native link and unlink transport calls."""
        u1 = self._create_disposable_resource(content="# Node A\n", suffix="a.md")
        u2 = self._create_disposable_resource(content="# Node B\n", suffix="b.md")

        # Confirm initial state has no link between u1 and u2
        u1_initial = [r for r in self.client.get_relations(u1) if r.get("uri") == u2]
        self.assertEqual(u1_initial, [])

        # Link u1 -> u2
        link_reason = "references, native link contract test"
        link_res = self.client.link(u1, u2, reason=link_reason)
        self.assertIsInstance(link_res, dict)

        # Verify relation visible on u1
        u1_relations = [r for r in self.client.get_relations(u1) if r.get("uri") == u2]
        self.assertEqual(len(u1_relations), 1)
        self.assertEqual(u1_relations[0]["uri"], u2)
        self.assertEqual(u1_relations[0]["reason"], link_reason)

        # Unlink u1 -> u2
        unlink_res = self.client.unlink(u1, u2)
        self.assertIsInstance(unlink_res, dict)

        # Verify relation removed on u1
        u1_post = [r for r in self.client.get_relations(u1) if r.get("uri") == u2]
        self.assertEqual(u1_post, [])

    def test_reciprocal_relation_lifecycle(self) -> None:
        """Verify set_reciprocal_relation and remove_reciprocal_relation in both directions."""
        u1 = self._create_disposable_resource(content="# Reciprocal A\n", suffix="recip_a.md")
        u2 = self._create_disposable_resource(content="# Reciprocal B\n", suffix="recip_b.md")

        desc = "contract verification reciprocal link"
        set_res = set_reciprocal_relation(
            self.client,
            primary=u1,
            secondary=u2,
            reason_pair="references/referenced_by",
            desc=desc,
        )
        self.assertTrue(set_res.get("ok"))
        self.assertTrue(set_res.get("changed"))

        # Verify both directions in native relations
        u1_links, u2_links = snapshot_relations(self.client, u1, u2)
        self.assertEqual(len(u1_links), 1)
        self.assertEqual(u1_links[0]["uri"], u2)
        self.assertEqual(u1_links[0]["reason"], f"references, {desc}")

        self.assertEqual(len(u2_links), 1)
        self.assertEqual(u2_links[0]["uri"], u1)
        self.assertEqual(u2_links[0]["reason"], f"referenced_by, {desc}")

        # Idempotency: setting the same relation again should report changed=False
        set_res_repeat = set_reciprocal_relation(
            self.client,
            primary=u1,
            secondary=u2,
            reason_pair="references/referenced_by",
            desc=desc,
        )
        self.assertTrue(set_res_repeat.get("ok"))
        self.assertFalse(set_res_repeat.get("changed"))

        # Remove reciprocal relation
        rm_res = remove_reciprocal_relation(self.client, primary=u1, secondary=u2)
        self.assertTrue(rm_res.get("ok"))
        self.assertTrue(rm_res.get("changed"))

        # Verify both directions removed
        u1_links_after, u2_links_after = snapshot_relations(self.client, u1, u2)
        self.assertEqual(u1_links_after, [])
        self.assertEqual(u2_links_after, [])

        # Idempotency of removal
        rm_res_repeat = remove_reciprocal_relation(self.client, primary=u1, secondary=u2)
        self.assertTrue(rm_res_repeat.get("ok"))
        self.assertFalse(rm_res_repeat.get("changed"))

    def test_list_relations_parsed_entries(self) -> None:
        """Verify retrieval_mcp.server.list_relations returns flat parsed entries."""
        u1 = self._create_disposable_resource(content="# Doc A\n", suffix="list_a.md")
        u2 = self._create_disposable_resource(content="# Doc B\n", suffix="list_b.md")

        desc = "contract verification description, with comma, and extra context"
        set_res = set_reciprocal_relation(
            self.client,
            primary=u1,
            secondary=u2,
            reason_pair="references/referenced_by",
            desc=desc,
        )
        self.assertTrue(set_res.get("ok"))

        # Check list_relations on u1
        lr1 = retrieval_server.list_relations(u1)
        self.assertEqual(lr1.get("uri"), u1)
        u1_matches = [r for r in lr1.get("relations", []) if r.get("uri") == u2]
        self.assertEqual(len(u1_matches), 1)
        self.assertEqual(u1_matches[0]["reason"], "references")
        self.assertEqual(u1_matches[0]["desc"], desc)

        # Check list_relations on u2
        lr2 = retrieval_server.list_relations(u2)
        self.assertEqual(lr2.get("uri"), u2)
        u2_matches = [r for r in lr2.get("relations", []) if r.get("uri") == u1]
        self.assertEqual(len(u2_matches), 1)
        self.assertEqual(u2_matches[0]["reason"], "referenced_by")
        self.assertEqual(u2_matches[0]["desc"], desc)

    def test_disposable_resources_cleanup_verification(self) -> None:
        """Verify that disposable resources are completely cleaned up and do not leave residue."""
        u1 = self._create_disposable_resource(content="# Cleanup Test\n", suffix="cleanup.md")
        self.assertTrue(self.client.exists(u1))

        # Explicitly delete
        self.client.delete_resource(u1)
        self.created_uris.discard(u1)
        self.assertFalse(self.client.exists(u1))

        # Confirm 404 / OpenVikingError on stat
        with self.assertRaises(OpenVikingError):
            self.client.stat_resource(u1)


if __name__ == "__main__":
    unittest.main()
