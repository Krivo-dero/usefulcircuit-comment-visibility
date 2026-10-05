import unittest
from comment_visibility import collect, compare, depth


def comment(identifier, parent=None, post="p"):
    return {"id": identifier, "parent_id": parent, "post_id": post, "content": "private text"}


class VisibilityTests(unittest.TestCase):
    def test_typed_search_results_preserve_unknown_metadata(self):
        payload = {"results": [{"type": "comment", "id": "c", "post_id": "p", "content": "search snippet"}]}
        row = compare([], payload, "p")["comments"][0]
        self.assertEqual(row["comment_id"], "c")
        self.assertTrue(row["independently_observed"])
        self.assertIsNone(row["parent_depth"])
        self.assertIsNone(row["independent_verification_status"])

    def test_typed_post_search_results_are_not_comment_evidence(self):
        payload = {"results": [{"type": "post", "id": "post", "post_id": "p", "content": "post snippet"}]}
        self.assertEqual(collect(payload, "p"), {})

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

    def test_identical_duplicate_metadata_is_accepted_without_body_retention(self):
        repeated = {**comment("c"), "content": "different private body"}
        self.assertEqual(len(collect([comment("c"), repeated])), 1)

    def test_conflicting_duplicate_parents_are_rejected_in_both_orders(self):
        observations = [comment("c"), comment("c", "parent")]
        for rows in (observations, observations[::-1]):
            with self.assertRaisesRegex(ValueError, "Conflicting duplicate comment metadata"):
                collect(rows)

    def test_conflicting_duplicate_statuses_are_not_last_write_wins(self):
        with self.assertRaises(ValueError):
            collect([{**comment("c"), "verification_status": "pending"},
                     {**comment("c"), "verification_status": "verified"}])

    def test_duplicate_id_on_different_posts_is_rejected_without_post_filter(self):
        with self.assertRaises(ValueError):
            collect([comment("c", post="p"), comment("c", post="other")])
        self.assertEqual(len(collect([comment("c"), comment("c", post="other")], "p")), 1)

    def test_cross_capture_parent_conflict_makes_depth_unknown(self):
        tree = [comment("a"), comment("b", "a"), comment("c", "a")]
        independent = [comment("a"), comment("b", "a"), comment("c", "b")]
        row = next(r for r in compare(tree, independent)["comments"] if r["comment_id"] == "c")
        self.assertTrue(row["parent_mismatch"])
        self.assertIsNone(row["parent_depth"])
        self.assertEqual(row["depth_status"], "parent_observation_conflict")

    def test_cross_capture_ancestor_conflict_also_makes_descendant_depth_unknown(self):
        tree = [comment("a"), comment("b", "a"), comment("c", "b")]
        independent = [comment("a"), comment("b"), comment("c", "b")]
        row = next(r for r in compare(tree, independent)["comments"] if r["comment_id"] == "c")
        self.assertFalse(row["parent_mismatch"])
        self.assertIsNone(row["parent_depth"])
        self.assertEqual(row["depth_status"], "parent_observation_conflict")

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

    def test_failed_comment_can_be_observed_by_author(self):
        failed = {**comment("failed"), "verification_status": "failed"}
        report = compare([failed], {"notifications": [{"comment": failed}]}, "p")
        row = report["comments"][0]
        self.assertEqual(row["tree_reread_result"], "observed")
        self.assertEqual(row["tree_verification_status"], "failed")
        self.assertEqual(report["not_observed_in_tree"], 0)
        self.assertIn("Observed does not mean verified", report["limitations"])

    def test_verification_statuses_are_separate_capture_observations(self):
        report = compare([{**comment("c"), "verification_status": "pending"}],
                         [{**comment("c"), "verificationStatus": "verified"}], "p")
        row = report["comments"][0]
        self.assertEqual(row["tree_verification_status"], "pending")
        self.assertEqual(row["independent_verification_status"], "verified")

    def test_missing_status_remains_unknown(self):
        row = compare([comment("c")], [comment("c")], "p")["comments"][0]
        self.assertIsNone(row["tree_verification_status"])
        self.assertIsNone(row["independent_verification_status"])

    def test_notification_wrapper_id_does_not_become_comment(self):
        export = {"notifications": [{"id": "notification-id", "relatedCommentId": "c",
                  "post": {"id": "p"}, "comment": {
                      "id": "c", "body": "synthetic", "parentId": None,
                      "verificationStatus": "failed"}}]}
        parsed = collect(export, "p")
        self.assertEqual(set(parsed), {"c"})
        self.assertEqual(parsed["c"]["verification_status"], "failed")

    def test_camel_case_profile_capture_keeps_missing_metadata_unknown(self):
        profile = {"agent": {"id": "agent-id"}, "recentComments": [
            {"id": "c", "content": "synthetic profile text", "post": {"id": "p"}},
            {"id": "other", "content": "synthetic", "post": {"id": "other-post"}}],
            "recentPosts": [{"id": "post-id", "content": "not a comment"}]}
        report = compare([], profile, "p")
        self.assertEqual(report["independent_comments"], 1)
        row = report["comments"][0]
        self.assertEqual(row["comment_id"], "c")
        self.assertEqual(row["depth_status"], "parent_field_missing")
        self.assertIsNone(row["parent_depth"])
        self.assertIsNone(row["independent_verification_status"])
        self.assertTrue(row["independently_observed"])
        self.assertEqual(row["tree_reread_result"], "not_observed")
        self.assertNotIn("synthetic profile text", __import__("json").dumps(report))


if __name__ == "__main__":
    unittest.main()
