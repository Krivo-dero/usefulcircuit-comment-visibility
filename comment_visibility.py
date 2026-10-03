"""Compare Moltbook comment-tree exports with independently captured comments.

Offline, read-only, no dependencies. Report observations, not deletion claims.
python3 comment_visibility.py --tree tree.json --independent notifications.json
Optional: --post-id UUID --receipts receipts.json --complete-tree
"""
import argparse
import datetime
import json
from pathlib import Path


def collect(payload, post_id=None, assume_post=False):
    """Find comment objects without mistaking notification, author or post IDs."""
    result = {}

    def visit(value, hint=None, inherited_post=None):
        if isinstance(value, list):
            for item in value:
                visit(item, hint, inherited_post)
        elif isinstance(value, dict):
            current_post = value.get("post_id", value.get("postId", inherited_post))
            if isinstance(value.get("post"), dict):
                current_post = value["post"].get("id", current_post)
            identifier = value.get("id", value.get("comment_id"))
            looks_like_comment = (
                hint in {"comments", "comment", "replies", "children", "recent_comments"}
                or "parent_id" in value or "parentId" in value
            ) and ("content" in value or "body" in value)
            if looks_like_comment and isinstance(identifier, str):
                # Unknown post ownership is not evidence about a specified post.
                if post_id is None or current_post == post_id:
                    result[identifier] = {
                        "id": identifier,
                        "parent_id": value.get("parent_id", value.get("parentId")),
                        "post_id": current_post,
                        "parent_known": "parent_id" in value or "parentId" in value,
                    }
            for key, child in value.items():
                if key not in {"author", "user", "post", "agent"}:
                    visit(child, key if key != "data" else hint, current_post)

    # A root list is conventionally a comment export, not arbitrary JSON.
    visit(payload, "comments" if isinstance(payload, list) else None,
          post_id if assume_post else None)
    return result


def depth(comment_id, comments):
    seen = set()
    current = comment_id
    steps = 0
    while current in comments:
        if current in seen:
            return None, "parent_cycle"
        seen.add(current)
        if not comments[current].get("parent_known", True):
            return None, "parent_field_missing"
        parent = comments[current]["parent_id"]
        if parent is None:
            return steps, "known"
        steps += 1
        current = parent
    return None, "parent_not_in_capture"


def compare(tree_payload, independent_payload, post_id=None, receipts=None, complete_tree=False):
    tree = collect(tree_payload, post_id, assume_post=True)
    independent = collect(independent_payload, post_id)
    all_comments = {**tree, **independent}
    receipts = receipts or []
    if not isinstance(receipts, list):
        raise ValueError("Receipts must be a JSON list")
    receipts_by_id = {r["comment_id"]: r for r in receipts
                      if isinstance(r, dict) and isinstance(r.get("comment_id"), str)
                      and (post_id is None or r.get("post_id", post_id) == post_id)}
    # A visible comment can still have its parent changed between read paths.
    rows = []
    for identifier in sorted(set(independent) | set(receipts_by_id)):
        receipt = receipts_by_id.get(identifier, {})
        known_depth, depth_status = depth(identifier, all_comments)
        observed = identifier in tree
        corroborated = identifier in independent
        row = {
            "comment_id": identifier,
            "post_timestamp": receipt.get("post_timestamp"),
            "post_http_status": receipt.get("post_http_status"),
            "parent_depth": known_depth,
            "depth_status": depth_status,
            "tree_reread_result": "observed" if observed else "not_observed",
            "independently_observed": corroborated,
            "parent_mismatch": bool(observed and corroborated and
                tree[identifier]["parent_known"] and independent[identifier]["parent_known"] and
                tree[identifier]["parent_id"] != independent[identifier]["parent_id"]),
        }
        if not observed:
            row["interpretation"] = (
                "absent_from_complete_capture" if complete_tree else "inconclusive_capture_may_be_partial")
        rows.append(row)
    return {
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "post_id": post_id,
        "tree_capture_declared_complete": complete_tree,
        "tree_comments": len(tree),
        "independent_comments": len(independent),
        "not_observed_in_tree": sum(r["tree_reread_result"] == "not_observed" for r in rows),
        "parent_mismatches": sum(r["parent_mismatch"] for r in rows),
        "comments": rows,
        "limitations": "Captures can differ in time, account visibility and pagination. Absence does not prove deletion. POST metadata is null unless a real write receipt was supplied. No comment text or API keys are included.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", required=True, type=Path)
    parser.add_argument("--independent", required=True, type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--post-id")
    parser.add_argument("--complete-tree", action="store_true",
                        help="Declare that YOU captured every page of the tree")
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text())
    print(json.dumps(compare(load(args.tree), load(args.independent), args.post_id,
        load(args.receipts) if args.receipts else None, args.complete_tree), indent=2))


if __name__ == "__main__":
    main()
