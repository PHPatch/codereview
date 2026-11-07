#!/usr/bin/env python3
"""codereview GitLab integration — review a merge request where it
lives. The GitLab sibling of github.py: same shape, same guards,
GitLab API v4 conventions.

Read path: fetch the MR's metadata and diff from the GitLab API
and run the review loop on the diff. Works without a token on
public projects; private projects need GITLAB_TOKEN.

Write path (needs GITLAB_TOKEN with access to the project): post
the report as an MR note and set a commit status on the MR head —
`codereview` name: success (gate pass), failed (blocked), pending
(inconclusive). GitLab has no review-event concept, so notes are
plain comments; there is no --request-changes equivalent.

Instances: gitlab.com by default. GITLAB_API_URL overrides the
full API base; GITLAB_HOST overrides the instance host; a
self-hosted MR URL's own host is used when neither is set.

Tokens come from the environment only, are never logged, and
authenticated requests refuse redirects (same rules as providers).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import providers as _providers
from .core import run_review, run_verification
from .github import _neutralise

_DEFAULT_API = "https://gitlab.com/api/v4"
# Project paths are one or more namespace segments (groups may
# nest) plus the project name; the MR number must end the URL
# (the L6 F4 lesson from the GitHub parser: "12abc" is not 12).
_MR_URL_RE = re.compile(
    r"^(https?)://([\w.-]+(?::\d+)?)/"
    r"((?:[\w.-]+/)+[\w.-]+)/-/merge_requests/(\d+)/?$")


class GitLabError(Exception):
    pass


def parse_mr_url(url):
    """(host, project_path, iid) for a GitLab MR URL.

    host keeps an explicit port if the URL carries one; the
    project path keeps every namespace segment (subgroups)."""
    m = _MR_URL_RE.match((url or "").strip())
    if not m:
        raise GitLabError(f"not a GitLab MR URL: {url!r}")
    return m.group(2), m.group(3), int(m.group(4))


def url_base(url):
    """scheme://host of an MR URL — the instance the MR lives on."""
    m = _MR_URL_RE.match((url or "").strip())
    if not m:
        raise GitLabError(f"not a GitLab MR URL: {url!r}")
    return f"{m.group(1)}://{m.group(2)}"


def _env_base():
    api = os.environ.get("GITLAB_API_URL", "").strip()
    if api:
        return api.rstrip("/")
    host = os.environ.get("GITLAB_HOST", "").strip()
    if host:
        if "://" not in host:
            host = f"https://{host}"
        return host.rstrip("/") + "/api/v4"
    return None


class GitLabClient:
    def __init__(self, token=None, base=None, opener=None,
                 url_base_hint=None):
        self.token = token if token is not None \
            else os.environ.get("GITLAB_TOKEN", "").strip()
        # Base precedence: explicit arg, GITLAB_API_URL /
        # GITLAB_HOST, the MR URL's own instance, gitlab.com.
        if base:
            self.base = base.rstrip("/")
        elif _env_base():
            self.base = _env_base()
        elif url_base_hint:
            self.base = url_base_hint.rstrip("/") + "/api/v4"
        else:
            self.base = _DEFAULT_API
        # Set by review_mr: the MR head the run reviewed, and
        # whether a commit status has been posted for it. The
        # crash handler uses them to mark a crashed run pending
        # (never success) — see crash.register_crash_hook.
        self.head_sha = None
        self.status_set = False
        self._opener = opener or urllib.request.build_opener(
            _providers._NoRedirect())
        self._project_ids = {}

    def _request(self, method, path, payload=None):
        headers = {"Accept": "application/json",
                   "User-Agent": "codereview"}
        if self.token:
            headers["PRIVATE-TOKEN"] = self.token
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=120) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                pass
            raise GitLabError(
                f"GitLab API {method} {path}: HTTP {e.code} {detail}"
            ) from e
        except (TimeoutError, ConnectionError, urllib.error.URLError) as e:
            raise GitLabError(f"GitLab API network error: {e}") from e

    def _get_json(self, path, what):
        raw = self._request("GET", path)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise GitLabError(f"bad {what} payload: {e}") from e

    def get_project_id(self, project):
        """Resolve a project path (namespaces included) to its
        numeric id — the MR endpoints address projects by id."""
        if project not in self._project_ids:
            quoted = urllib.parse.quote(project, safe="")
            data = self._get_json(f"/projects/{quoted}", "project")
            try:
                self._project_ids[project] = int(data["id"])
            except (KeyError, TypeError, ValueError) as e:
                raise GitLabError(
                    f"project payload has no id: {project!r}") from e
        return self._project_ids[project]

    def get_mr(self, project, iid):
        pid = self.get_project_id(project)
        return self._get_json(
            f"/projects/{pid}/merge_requests/{iid}", "MR")

    def get_mr_changes(self, project, iid):
        pid = self.get_project_id(project)
        data = self._get_json(
            f"/projects/{pid}/merge_requests/{iid}/changes",
            "MR changes")
        return data.get("changes") or []

    def get_mr_diff(self, project, iid):
        return assemble_diff(self.get_mr_changes(project, iid))

    @staticmethod
    def _post_result(raw, what):
        """Mirror of the GitHub client's L6 F3 guard: a POST's
        2xx body is not always JSON (a captive portal or proxy
        can answer 200 with HTML); an unparseable body surfaces
        as GitLabError — which review_mr records in the report —
        never as a raw JSONDecodeError escaping with no record
        written."""
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except ValueError as e:
            raise GitLabError(
                f"GitLab API {what}: 2xx response was not JSON"
            ) from e

    def post_note(self, project, iid, body):
        pid = self.get_project_id(project)
        raw = self._request(
            "POST", f"/projects/{pid}/merge_requests/{iid}/notes",
            payload={"body": body})
        return self._post_result(raw, "post note")

    def set_status(self, project, sha, state, description,
                   target_url=None):
        pid = self.get_project_id(project)
        payload = {"state": state, "name": "codereview",
                   "description": description[:255]}
        if target_url:
            payload["target_url"] = target_url
        raw = self._request(
            "POST", f"/projects/{pid}/statuses/{sha}",
            payload=payload)
        return self._post_result(raw, "set status")


def assemble_diff(changes):
    """Assemble a git-format unified diff from the GitLab
    /changes payload, whose per-file `diff` field carries only
    the hunk text — the `diff --git` / --- / +++ headers are
    rebuilt from the old/new paths so the review loop parses the
    result exactly like a GitHub diff."""
    out = []
    for ch in changes:
        old = ch.get("old_path") or ""
        new = ch.get("new_path") or ""
        if not (old or new):
            continue
        out.append(f"diff --git a/{old} b/{new}")
        out.append("--- " + ("/dev/null" if ch.get("new_file")
                             else f"a/{old}"))
        out.append("+++ " + ("/dev/null" if ch.get("deleted_file")
                             else f"b/{new}"))
        body = (ch.get("diff") or "").rstrip("\n")
        if body:
            out.append(body)
    return "\n".join(out) + ("\n" if out else "")


_GATE_STATUS = {"pass": "success", "blocked": "failed",
                "inconclusive": "pending"}


def render_mr_comment(report, project, iid):
    """The MR-visible summary of a report (Markdown) — the
    github.py renderer with a GitLab footer."""
    gate = report["gate"].upper()
    icon = {"PASS": "✅", "BLOCKED": "⛔",
            "INCONCLUSIVE": "⚠️"}.get(gate, "")
    lines = [f"## {icon} CodeReview gate: **{gate}**",
             "",
             _neutralise("; ".join(
                 report.get("gate_reasons") or [])), ""]

    def cell(text):
        return _neutralise(
            str(text or "").replace("|", "/")
            .replace("\r", " ").replace("\n", " "))

    findings = [f for f in report.get("findings") or []]
    if findings:
        lines.append("| Severity | File | Finding | Reviewer(s) |")
        lines.append("|---|---|---|---|")
        for f in findings:
            who = _neutralise(", ".join(f.get("sources") or []))
            lines.append(f"| {f['severity']} | {cell(f.get('file'))} "
                         f"| {cell(f.get('title'))} | {who} |")
        lines.append("")
    if report.get("mode") == "verify":
        lines.append(f"Cleared: {len(report.get('cleared') or [])} · "
                     f"Still open: {len(report.get('remaining') or [])}")
        lines.append("")
    if report.get("degraded"):
        lines.append("_Degraded round: at least one reviewer failed "
                     "(see the full report)._\n")
    lines.append(f"CodeReview {report.get('version')} · "
                 f"revision `{report.get('patch_sha256', '')[:12]}` · "
                 f"MR !{iid}")
    return "\n".join(lines)


def review_mr(client, project, iid, reviewer_providers,
              post=False, previous=None, builder_response="",
              test_results=None, strict=False, allow_major=False):
    """Fetch an MR, review (or verify) its diff, optionally post.

    Returns (report, actions) where actions records what was
    posted. A posting failure does NOT raise (P5-03, mirrored
    from review_pr): the completed review must survive it, so
    the failure is recorded on the report as
    report["posting"] = {"posted": [...], "error": "..."} and
    the caller decides the exit code after writing the report.
    Fetch and review failures still raise GitLabError.
    """
    if post and not client.token:
        # P5-02: refuse before any fetch or review spend — the
        # token check must not sit after the review has run.
        raise GitLabError("--post needs GITLAB_TOKEN")
    mr = client.get_mr(project, iid)
    diff = client.get_mr_diff(project, iid)
    if not diff.strip():
        raise GitLabError("the MR diff is empty")
    head_sha = (mr.get("sha")
                or (mr.get("diff_refs") or {}).get("head_sha") or "")
    try:
        client.head_sha = head_sha or None
    except AttributeError:  # a fake client without the slot
        pass
    author = ((mr.get("author") or {}).get("username")
              or (mr.get("author") or {}).get("name") or "")
    context = (f"GitLab MR {project}!{iid}: "
               f"{mr.get('title') or ''}\n"
               f"Author: {author}\n"
               f"{(mr.get('description') or '')[:1500]}")
    if previous is not None:
        report = run_verification(
            diff, reviewer_providers, previous, builder_response,
            test_results=test_results or [], allow_major=allow_major,
            strict=strict)
    else:
        report = run_review(
            diff, reviewer_providers, context=context,
            test_results=test_results or [], allow_major=allow_major,
            strict=strict)
    report["mr"] = {"forge": "gitlab", "project": project,
                    "iid": iid, "head_sha": head_sha,
                    "title": mr.get("title") or ""}
    actions = []
    if post:
        body = render_mr_comment(report, project, iid)
        try:
            client.post_note(project, iid, body)
            actions.append("MR note posted")
            if head_sha:
                state = _GATE_STATUS.get(report["gate"], "pending")
                desc = ("; ".join(report.get("gate_reasons") or [])
                        or report["gate"])
                if report["gate"] == "inconclusive":
                    # P5-11: `pending` is the documented state
                    # for an inconclusive gate, and the
                    # description must say so explicitly — branch
                    # protection waits on pending, so the human
                    # has to be able to see WHY it is pending.
                    desc = ("gate inconclusive — the review did "
                            f"not reach a verdict: {desc}")
                client.set_status(project, head_sha, state, desc)
                try:
                    client.status_set = True
                except AttributeError:
                    pass
                actions.append(
                    f"commit status set: codereview={state}")
        except GitLabError as exc:
            report["posting"] = {"posted": list(actions),
                                 "error": str(exc)}
    return report, actions
