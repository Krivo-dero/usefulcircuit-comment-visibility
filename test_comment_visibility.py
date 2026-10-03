import unittest
from comment_visibility import collect, compare, depth


def comment(identifier, parent=None, post="p"):
    return {"id": identifier, "parent_id": parent, "post_id": post, "content": "private text"}


class VisibilityTests(unittest.TestCase):
    def test_dropped_reply_with_independent_evidence(self):
        report = compare({"comments": [comment("root")]},
                         {"notifications": [{"comment": comment("reply", "root")}]}, "p")
        self.assertEqual(report["not_observed_in_tree"], 1)
        self.assertEqual(report["comments"][0]["parent_depth"], 1)
        self.assertIn("inconclusive", report["comments"][0]["interpretation"])

    def test_nested_replies_and_user_ids(self):
        data = {"comments": [{**comment("root"), "author": {"id": "person"},
                "replies": [comment("reply", "root")]}]}
        self.assertEqual(set(collect(data, "p")), {"root", "reply"})

    def test_other_posts_are_excluded(self):
        self.assertEqual(collect({"comment": comment("wrong", post="other")}, "p"), {})

    def test_unknown_post_is_not_assigned_to_requested_post(self):
        unknown = {"id": "x", "content": "text", "parent_id": None}
        self.assertEqual(collect({"comment": unknown}, "p"), {})
        report = compare([unknown], {"comment": unknown}, "p")
        self.assertEqual(report["tree_comments"], 1)
        self.assertEqual(report["independent_comments"], 0)

    def test_missing_parent_field_does_not_invent_root_depth(self):
        unknown = {"id": "x", "content": "text"}
        self.assertEqual(depth("x", collect([unknown])), (None, "parent_field_missing"))

    def test_parent_mismatch(self):
        report = compare([comment("c")], [comment("c", "parent")], "p")
        self.assertEqual(report["parent_mismatches"], 1)

    def test_cycles_and_unknown_parents_are_not_invented_depths(self):
        self.assertEqual(depth("x", collect([comment("x", "y"), comment("y", "x")])),
                         (None, "parent_cycle"))
        self.assertEqual(depth("x", collect([comment("x", "missing")])),
                         (None, "parent_not_in_capture"))

    def test_real_receipt_metadata_only(self):
        report = compare([], [], receipts=[{"comment_id": "x", "post_timestamp": "2026-10-03T00:00:00Z", "post_http_status": 201}])
        self.assertEqual(report["comments"][0]["post_http_status"], 201)
        self.assertFalse(report["comments"][0]["independently_observed"])
        self.assertIsNone(report["comments"][0]["parent_depth"])

    def test_report_does_not_emit_comment_bodies(self):
        import json
        report = compare([], [comment("c")])
        self.assertNotIn("private text", json.dumps(report))
        self.assertIsNone(report["comments"][0]["post_http_status"])

    def test_complete_capture_is_explicit(self):
        report = compare([], [comment("c")], complete_tree=True)
        self.assertEqual(report["comments"][0]["interpretation"], "absent_from_complete_capture")


if __name__ == "__main__":
    unittest.main()
