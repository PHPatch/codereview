"""GitLab integration tests — fake transport, no network."""
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli as _cli
from codereview.gitlab import (GitLabClient, GitLabError, assemble_diff,
                               parse_mr_url, render_mr_comment,
                               review_mr, url_base)

MR_JSON = {"id": 99, "iid": 7, "title": "Add the thing",
           "description": "does stuff",
           "author": {"username": "dev"}, "sha": "abc123def",
           "state": "opened"}
PROJECT_JSON = {"id": 42, "path_with_namespace": "octo/hello"}
CHANGES_JSON = {"changes": [
    {"old_path": "app.py", "new_path": "app.py", "new_file": False,
     "deleted_file": False, "renamed_file": False,
     "diff": "@@ -1,1 +1,2 @@\n x = 1\n+run_all_the_things()\n"},
    {"old_path": "new.py", "new_path": "new.py", "new_file": True,
     "deleted_file": False, "renamed_file": False,
     "diff": "@@ -0,0 +1,1 @@\n+brand_new()\n"},
    {"old_path": "gone.py", "new_path": "gone.py", "new_file": False,
     "deleted_file": True, "renamed_file": False,
     "diff": "@@ -1,1 +0,0 @@\n-old()\n"},
]}
DIFF = assemble_diff(CHANGES_JSON["changes"])


class FakeResponse:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Records requests; answers from canned GitLab routes."""

    def __init__(self):
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        path = req.full_url
        if req.method == "GET" and "/projects/" in path \
                and "merge_requests" not in path:
            return FakeResponse(json.dumps(PROJECT_JSON))
        if req.method == "GET" \
                and path.endswith("/merge_requests/7/changes"):
            return FakeResponse(json.dumps(CHANGES_JSON))
        if req.method == "GET" and path.endswith("/merge_requests/7"):
            return FakeResponse(json.dumps(MR_JSON))
        if req.method == "POST" and "/notes" in path:
            return FakeResponse('{"id": 11}')
        if req.method == "POST" and "/statuses/" in path:
            return FakeResponse('{"id": 12}')
        raise AssertionError(f"unexpected request {req.method} {path}")


class StatusFailOpener(FakeOpener):
    """The status POST fails with HTTP 500; the note succeeds."""

    def open(self, req, timeout=None):
        if req.method == "POST" and "/statuses/" in req.full_url:
            self.requests.append(req)
            raise urllib.error.HTTPError(
                req.full_url, 500, "Internal Server Error", {},
                io.BytesIO(b'{"message": "boom"}'))
        return super().open(req, timeout=timeout)


class NotFoundOpener:
    def __init__(self):
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", {},
            io.BytesIO(b'{"message": "404 Project Not Found"}'))


def fake_reviewer(findings=None):
    """Core-level provider protocol: a callable prompt -> JSON text."""
    def fn(prompt):
        return json.dumps({"findings": findings or [],
                           "summary": "fake", "usage": {}})
    return fn


BLOCKER = [{"severity": "blocker", "file": "app.py", "line": 2,
            "rule": "", "title": "Unguarded mass action",
            "detail": "runs everything with no guard"}]


def _client(token="tok", opener=None):
    return GitLabClient(token=token, opener=opener or FakeOpener())


class TestParse(unittest.TestCase):
    def test_gitlab_com_url(self):
        self.assertEqual(
            parse_mr_url("https://gitlab.com/superstartelecom/"
                         "codereview-l3-smoke-test/-/merge_requests/1"),
            ("gitlab.com", "superstartelecom/codereview-l3-smoke-test",
             1))

    def test_subgroup_path(self):
        self.assertEqual(
            parse_mr_url("https://gitlab.com/group/sub/deep/proj/-/"
                         "merge_requests/3"),
            ("gitlab.com", "group/sub/deep/proj", 3))

    def test_self_hosted_with_port(self):
        self.assertEqual(
            parse_mr_url("https://git.example.com:8443/team/proj/-/"
                         "merge_requests/9"),
            ("git.example.com:8443", "team/proj", 9))
        self.assertEqual(
            url_base("https://git.example.com:8443/team/proj/-/"
                     "merge_requests/9"),
            "https://git.example.com:8443")

    def test_trailing_slash_ok(self):
        self.assertEqual(
            parse_mr_url("https://gitlab.com/o/r/-/merge_requests/7/"),
            ("gitlab.com", "o/r", 7))

    def test_bad_urls(self):
        for bad in (
                "https://github.com/octo/hello/pull/42",
                "https://gitlab.com/octo/hello/merge_requests/7",
                "https://gitlab.com/octo/hello/-/merge_requests/7abc",
                "https://gitlab.com/octo/hello/-/merge_requests/7?x=1",
                "https://gitlab.com/solo/-/merge_requests/7",
                "https://gitlab.com/oc?to/hello/-/merge_requests/7",
                "https://gitlab.com/octo/hel%20lo/-/merge_requests/7",
                "https://gitlab.com/octo/hello/-/merge_requests/7/x"):
            with self.assertRaises(GitLabError, msg=bad):
                parse_mr_url(bad)


class TestClient(unittest.TestCase):
    def test_project_resolution_and_caching(self):
        op = FakeOpener()
        client = _client(opener=op)
        self.assertEqual(client.get_project_id("octo/hello"), 42)
        client.get_mr("octo/hello", 7)
        project_reads = [r for r in op.requests
                         if "/projects/" in r.full_url
                         and "merge_requests" not in r.full_url]
        self.assertEqual(len(project_reads), 1)  # cached
        self.assertIn("octo%2Fhello", project_reads[0].full_url)

    def test_get_mr_and_assembled_diff(self):
        client = _client()
        mr = client.get_mr("octo/hello", 7)
        self.assertEqual(mr["sha"], "abc123def")
        diff = client.get_mr_diff("octo/hello", 7)
        self.assertIn("diff --git a/app.py b/app.py", diff)
        self.assertIn("+run_all_the_things()", diff)
        self.assertIn("--- /dev/null", diff)   # the new file
        self.assertIn("+++ /dev/null", diff)   # the deleted file

    def test_private_token_header(self):
        op = FakeOpener()
        client = _client(opener=op)
        client.get_mr("octo/hello", 7)
        self.assertEqual(op.requests[0].get_header("Private-token"),
                         "tok")

    def test_no_token_no_header(self):
        op = FakeOpener()
        client = _client(token="", opener=op)
        client.get_mr("octo/hello", 7)
        self.assertIsNone(op.requests[0].get_header("Private-token"))

    def test_api_error_mapping(self):
        client = _client(opener=NotFoundOpener())
        with self.assertRaises(GitLabError) as ctx:
            client.get_mr("octo/hello", 7)
        self.assertIn("HTTP 404", str(ctx.exception))

    def test_base_from_env_host(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GITLAB_API_URL", "GITLAB_HOST")}
        env["GITLAB_HOST"] = "gitlab.example.com"
        with mock.patch.dict(os.environ, env, clear=True):
            client = GitLabClient(token="t", opener=FakeOpener())
        self.assertEqual(client.base,
                         "https://gitlab.example.com/api/v4")

    def test_base_from_env_api_url_wins(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GITLAB_API_URL", "GITLAB_HOST")}
        env["GITLAB_API_URL"] = "https://gl.internal/api/v4/"
        env["GITLAB_HOST"] = "ignored.example.com"
        with mock.patch.dict(os.environ, env, clear=True):
            client = GitLabClient(token="t", opener=FakeOpener())
        self.assertEqual(client.base, "https://gl.internal/api/v4")

    def test_base_from_url_hint(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GITLAB_API_URL", "GITLAB_HOST")}
        with mock.patch.dict(os.environ, env, clear=True):
            client = GitLabClient(
                token="t", opener=FakeOpener(),
                url_base_hint="https://git.example.com:8443")
        self.assertEqual(client.base,
                         "https://git.example.com:8443/api/v4")


class TestReviewMr(unittest.TestCase):
    def test_blocked_posts_note_and_failed_status(self):
        op = FakeOpener()
        client = _client(opener=op)
        report, actions = review_mr(
            client, "octo/hello", 7, {"fake": fake_reviewer(BLOCKER)},
            post=True)
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(report["mr"]["forge"], "gitlab")
        self.assertEqual(report["mr"]["head_sha"], "abc123def")
        self.assertEqual(len(actions), 2)
        posts = [r for r in op.requests if r.method == "POST"]
        note_body = json.loads(posts[0].data.decode())
        self.assertIn("BLOCKED", note_body["body"])
        status_body = json.loads(posts[1].data.decode())
        self.assertEqual(status_body["state"], "failed")
        self.assertEqual(status_body["name"], "codereview")

    def test_pass_posts_success_status(self):
        op = FakeOpener()
        client = _client(opener=op)
        report, _actions = review_mr(
            client, "octo/hello", 7, {"fake": fake_reviewer()},
            post=True)
        self.assertEqual(report["gate"], "pass")
        posts = [r for r in op.requests if r.method == "POST"]
        self.assertEqual(json.loads(posts[1].data.decode())["state"],
                         "success")

    def test_post_without_token_refused_before_any_request(self):
        op = FakeOpener()
        client = _client(token="", opener=op)
        with self.assertRaises(GitLabError):
            review_mr(client, "octo/hello", 7,
                      {"fake": fake_reviewer()}, post=True)
        self.assertEqual(op.requests, [])  # P5-02: refused pre-fetch

    def test_read_only_makes_no_posts(self):
        op = FakeOpener()
        client = _client(opener=op)
        report, actions = review_mr(
            client, "octo/hello", 7, {"fake": fake_reviewer(BLOCKER)})
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(actions, [])
        self.assertFalse(any(r.method == "POST" for r in op.requests))

    def test_status_failure_recorded_not_raised(self):
        op = StatusFailOpener()
        client = _client(opener=op)
        report, actions = review_mr(
            client, "octo/hello", 7, {"fake": fake_reviewer(BLOCKER)},
            post=True)
        self.assertEqual(actions, ["MR note posted"])
        self.assertEqual(report["posting"]["posted"], actions)
        self.assertIn("500", report["posting"]["error"])

    def test_empty_diff_refused(self):
        class EmptyChangesOpener(FakeOpener):
            def open(self, req, timeout=None):
                if req.full_url.endswith("/changes"):
                    self.requests.append(req)
                    return FakeResponse('{"changes": []}')
                return super().open(req, timeout=timeout)

        client = _client(opener=EmptyChangesOpener())
        with self.assertRaises(GitLabError):
            review_mr(client, "octo/hello", 7,
                      {"fake": fake_reviewer()})


class TestRender(unittest.TestCase):
    def test_comment_shape(self):
        report = {"gate": "blocked", "gate_reasons": ["1 blocker"],
                  "findings": [{"severity": "blocker", "file": "a.py",
                                "title": "Bad | thing",
                                "sources": ["fake"]}],
                  "version": "0.13.0", "patch_sha256": "x" * 32}
        md = render_mr_comment(report, "o/r", 3)
        self.assertIn("BLOCKED", md)
        self.assertIn("Bad / thing", md)  # pipe escaped for the table
        self.assertIn("MR !3", md)


class TestCliDispatch(unittest.TestCase):
    def test_unsupported_url_names_both_shapes(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            rc = _cli._pr_main(
                ["--pr", "https://example.com/nope"],
                providers_override={"fake": fake_reviewer()})
        self.assertEqual(rc, 2)
        self.assertIn("github.com/OWNER/REPO/pull/N", err.getvalue())
        self.assertIn("merge_requests/N", err.getvalue())

    def test_gitlab_post_without_token_exits_2_no_calls(self):
        calls = []

        def counting(prompt):
            calls.append(1)
            return fake_reviewer()(prompt)

        env = {k: v for k, v in os.environ.items()
               if k != "GITLAB_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("sys.stderr", io.StringIO()):
            rc = _cli._pr_main(
                ["--pr", "https://gitlab.com/octo/hello/-/"
                 "merge_requests/7", "--post"],
                providers_override={"fake": counting})
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])  # zero provider calls (P5-02)


if __name__ == "__main__":
    unittest.main()
