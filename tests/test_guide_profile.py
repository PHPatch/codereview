"""W1 + W2 — the `guide` gate profile and plain-English
explanations (OPC plan v2 §4/§5).

W1: `guide` runs the strict pipeline unchanged and re-decides
the finished gate in shipping terms. Findings standing at
the gate are bucketed red (fix before you ship — secrets and
security holes, money mistakes, data loss, main-path
crashes, a failing test command; these still block), yellow
(fix soon — blocking-severity findings outside the red
classes; they do not block) and grey (nice to improve —
below blocking severity). The verdict is READY TO SHIP /
SHIP WITH KNOWN ISSUES (n yellow) / NOT SAFE TO SHIP
(n red) / COULD NOT CHECK — its own recorded state, never
labelled PASS, with the strict gate kept on the record
untouched. Exit codes: red -> 1, could-not-check -> 2,
otherwise 0.

W2: `codereview explain` renders every finding in a record
as the five plain-English parts, generated from the finding
data itself; `codereview words` prints the glossary. The
urgency wording is a function of the bucket alone, so a red
finding can never be softened into yellow wording — pinned
below.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, core, guide, policy  # noqa: E402


def finding(severity="major", category="correctness", title="t",
            rule="", **kw):
    f = {"id": kw.pop("id", "fp-" + title[:12].replace(" ", "-")),
         "rule": rule, "severity": severity, "category": category,
         "file": "app/main.py", "line": 10, "title": title,
         "evidence": "e", "evidence_quote": "q",
         "recommendation": "do the fix", "confidence": 0.9,
         "sources": ["seat-a"], "consensus": False}
    f.update(kw)
    return f


class BucketTests(unittest.TestCase):
    def bucket(self, f, **kw):
        return guide.bucket_of(f, **kw)[0]

    def test_secret_rule_is_red(self):
        f = core.deterministic_scan(
            "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
            "@@ -0,0 +1,1 @@\n+api_key = \"abcdefgh12345678\"\n")[0]
        self.assertEqual(f["category"], "security")
        self.assertEqual(self.bucket(f), "red")

    def test_security_and_data_loss_blocking_are_red(self):
        self.assertEqual(self.bucket(finding(
            severity="major", category="security",
            title="SQL built by string formatting")), "red")
        self.assertEqual(self.bucket(finding(
            severity="blocker", category="data-loss",
            title="DELETE without a WHERE clause")), "red")

    def test_failing_test_command_is_red(self):
        f = finding(severity="blocker", category="testing",
                    rule="test-failure",
                    title="Test command failed: pytest")
        self.assertEqual(self.bucket(f), "red")

    def test_money_mistake_is_red(self):
        self.assertEqual(self.bucket(finding(
            severity="major", category="correctness",
            title="Refund is issued twice when the webhook "
                  "retries")), "red")
        self.assertEqual(self.bucket(finding(
            severity="blocker", category="correctness",
            title="Charge amount ignores the currency "
                  "conversion")), "red")

    def test_main_path_crash_is_red(self):
        self.assertEqual(self.bucket(finding(
            severity="blocker", category="reliability",
            title="Unhandled exception crashes the worker on "
                  "an empty queue")), "red")

    def test_plain_blocking_bug_is_yellow(self):
        self.assertEqual(self.bucket(finding(
            severity="blocker", category="reliability",
            title="sub() retries forever with no timeout or "
                  "backoff")), "yellow")
        self.assertEqual(self.bucket(finding(
            severity="major", category="correctness",
            title="Off-by-one in the report pagination")),
            "yellow")
        self.assertEqual(self.bucket(finding(
            severity="major", category="performance",
            title="N+1 query on the listing page")), "yellow")

    def test_minor_and_nit_are_grey(self):
        self.assertEqual(self.bucket(finding(
            severity="minor", category="quality",
            title="Debug statement left in added code")),
            "grey")
        self.assertEqual(self.bucket(finding(
            severity="nit", category="quality", title="typo")),
            "grey")
        # A minor-severity security item is still minor: the
        # panel's severity is the centrality signal.
        self.assertEqual(self.bucket(finding(
            severity="minor", category="security",
            title="Verbose error message")), "grey")

    def test_allow_major_tier_makes_major_advisory_grey(self):
        f = finding(severity="major", category="correctness",
                    title="Wrong total on the settings page")
        self.assertEqual(
            guide.bucket_of(f, blocking_sevs=("blocker",))[0],
            "grey")

    def test_every_bucket_carries_a_reason(self):
        for sev, cat in (("blocker", "security"),
                         ("major", "correctness"),
                         ("minor", "quality")):
            _b, reason, _k = guide.bucket_of(
                finding(severity=sev, category=cat))
            self.assertTrue(reason)


class GuideVerdictTests(unittest.TestCase):
    def section(self, findings, gate, **kw):
        return guide.guide_section(findings, gate, **kw)

    def test_ready_to_ship(self):
        s = self.section([finding(severity="minor",
                                  category="quality")], "pass")
        self.assertEqual(s["verdict"], "READY TO SHIP")
        self.assertEqual(s["verdict_state"], "ready_to_ship")
        self.assertEqual(s["exit_code"], 0)
        self.assertEqual(s["strict_gate"], "pass")

    def test_ship_with_known_issues(self):
        fs = [finding(severity="major", category="correctness",
                      title="Wrong sum on the settings page"),
              finding(severity="blocker", category="reliability",
                      title="Retry loop never gives up")]
        s = self.section(fs, "blocked")
        self.assertEqual(s["verdict"],
                         "SHIP WITH KNOWN ISSUES (2 yellow)")
        self.assertEqual(s["verdict_state"],
                         "ship_with_known_issues")
        self.assertEqual(s["exit_code"], 0)
        self.assertEqual(s["yellow_count"], 2)
        # The strict gate stays what it was: blocked — the
        # guide state is not a relabelled pass.
        self.assertEqual(s["strict_gate"], "blocked")

    def test_not_safe_to_ship(self):
        s = self.section([finding(
            severity="blocker", category="security",
            title="API key committed in the source")], "blocked")
        self.assertEqual(s["verdict"], "NOT SAFE TO SHIP (1 red)")
        self.assertEqual(s["exit_code"], 1)

    def test_could_not_check(self):
        s = self.section([], "inconclusive")
        self.assertEqual(s["verdict"], "COULD NOT CHECK")
        self.assertEqual(s["exit_code"], 2)

    def test_non_finding_block_is_never_shipped_over(self):
        s = self.section(
            [finding(severity="major", category="correctness",
                     title="Wrong sum on the settings page")],
            "blocked", non_finding_block=True)
        self.assertEqual(s["verdict_state"], "not_safe_to_ship")
        self.assertEqual(s["exit_code"], 1)
        self.assertTrue(s["non_finding_block"])

    def test_no_guide_verdict_is_ever_pass(self):
        cases = [
            ([], "pass"), ([], "blocked"), ([], "inconclusive"),
            ([finding(severity="blocker", category="security",
                      title="x")], "blocked"),
            ([finding(severity="major", category="correctness",
                      title="y")], "blocked"),
            ([finding(severity="minor", category="quality",
                      title="z")], "pass"),
        ]
        for fs, gate in cases:
            s = self.section(fs, gate)
            self.assertNotEqual(s["verdict"], "PASS")
            self.assertNotEqual(s["verdict_state"], "pass")
            self.assertIn(s["verdict_state"],
                          guide.VERDICT_STATES)


PATCH_CLEAN = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""

# Fake key value assembled from fragments: the fixture-hygiene test
# forbids secret-shaped literals in test files (see tests/test_core.py).
_FAKE_KEY_VALUE = "abcd" + "efgh1234" + "5678"

PATCH_SECRET = """diff --git a/app/config.py b/app/config.py
--- a/app/config.py
+++ b/app/config.py
@@ -1,1 +1,2 @@
 DEBUG = False
+api_key = "%s"
""" % _FAKE_KEY_VALUE

PATCH_ALERT = """diff --git a/app/jobs.py b/app/jobs.py
--- a/app/jobs.py
+++ b/app/jobs.py
@@ -1,1 +1,2 @@
 import os
+send_alert("disk almost full")
"""


def empty_provider(prompt):
    return json.dumps({"summary": "stub", "findings": []})


def boom_provider(prompt):
    raise RuntimeError("seat down")


class GuideRunReviewTests(unittest.TestCase):
    def test_guide_red_blocks_and_keeps_strict_gate(self):
        rep = core.run_review(PATCH_SECRET,
                              {"a": empty_provider},
                              gate_profile="guide")
        self.assertEqual(rep["gate"], "blocked")
        self.assertEqual(rep["gate_profile"]["profile"],
                         "guide")
        self.assertEqual(rep["gate_profile"]["demotions"], [])
        g = rep["guide"]
        self.assertEqual(g["verdict_state"], "not_safe_to_ship")
        self.assertEqual(g["exit_code"], 1)
        self.assertEqual(g["red_count"], 1)
        f = rep["findings"][0]
        self.assertEqual(f["guide_bucket"], "red")
        self.assertIn("security", f["guide_bucket_reason"])

    def test_guide_yellow_only_ships_with_known_issues(self):
        rep = core.run_review(PATCH_ALERT,
                              {"a": empty_provider},
                              gate_profile="guide")
        self.assertEqual(rep["gate"], "blocked")
        g = rep["guide"]
        self.assertEqual(g["verdict_state"],
                         "ship_with_known_issues")
        self.assertEqual(g["verdict"],
                         "SHIP WITH KNOWN ISSUES (1 yellow)")
        self.assertEqual(g["exit_code"], 0)
        self.assertEqual(rep["findings"][0]["guide_bucket"],
                         "yellow")

    def test_guide_clean_is_ready_to_ship(self):
        rep = core.run_review(PATCH_CLEAN,
                              {"a": empty_provider},
                              gate_profile="guide")
        self.assertEqual(rep["gate"], "pass")
        self.assertEqual(rep["guide"]["verdict"],
                         "READY TO SHIP")
        self.assertEqual(rep["guide"]["exit_code"], 0)

    def test_guide_no_reviewer_could_not_check(self):
        rep = core.run_review(PATCH_CLEAN, {"a": boom_provider},
                              gate_profile="guide")
        self.assertEqual(rep["gate"], "inconclusive")
        self.assertEqual(rep["guide"]["verdict"],
                         "COULD NOT CHECK")
        self.assertEqual(rep["guide"]["exit_code"], 2)

    def test_strict_has_no_guide_section(self):
        rep = core.run_review(PATCH_SECRET,
                              {"a": empty_provider})
        self.assertNotIn("guide", rep)
        self.assertNotIn("guide_bucket", rep["findings"][0])

    def test_strict_and_guide_see_identical_findings(self):
        """The strict regression pin: guide is a decision
        layer over the strict pipeline, so the same inputs
        under strict and guide must produce the same
        findings, the same gate and the same reasons — guide
        only ADDS its section and per-finding stamps."""
        strict = core.run_review(PATCH_ALERT,
                                 {"a": empty_provider},
                                 gate_profile="strict")
        guided = core.run_review(PATCH_ALERT,
                                 {"a": empty_provider},
                                 gate_profile="guide")

        def strip(fs):
            return [{k: v for k, v in f.items()
                     if not k.startswith("guide_")}
                    for f in fs]

        self.assertEqual(strip(strict["findings"]),
                         strip(guided["findings"]))
        self.assertEqual(strict["gate"], guided["gate"])
        self.assertEqual(strict["gate_reasons"],
                         guided["gate_reasons"])
        self.assertEqual(strict["deterministic_findings"],
                         guided["deterministic_findings"])

    def test_guide_profile_pass_demotes_nothing(self):
        f = {"id": "fp1", "rule": "", "severity": "blocker",
             "category": "reliability", "file": "app/util.py",
             "line": 6, "title": "t", "evidence": "e",
             "evidence_quote": "q", "recommendation": "r",
             "confidence": 0.9, "sources": ["ops-seat"],
             "source_lenses": {"ops-seat": ["operations"]},
             "consensus": False}
        out, demotions = core.evaluate_gate_policy(
            [dict(f)], "guide")
        self.assertEqual(demotions, [])
        self.assertEqual(out[0]["severity"], "blocker")
        s_out, s_demotions = core.evaluate_gate_policy(
            [dict(f)], "strict")
        self.assertEqual(s_demotions, [])
        self.assertEqual(out[0]["severity"],
                         s_out[0]["severity"])

    def test_guide_is_a_known_profile_everywhere(self):
        self.assertIn("guide", core.GATE_PROFILES)
        self.assertEqual(policy.KNOWN_GATE_PROFILES,
                         core.GATE_PROFILES)

    def test_markdown_carries_guide_verdict(self):
        rep = core.run_review(PATCH_ALERT,
                              {"a": empty_provider},
                              gate_profile="guide")
        md = core.render_markdown(rep)
        self.assertIn("SHIP WITH KNOWN ISSUES (1 yellow)", md)
        self.assertIn("Fix soon", md)
        self.assertIn("Why it matters to you", md)


class ExplainTests(unittest.TestCase):
    RED = None  # built in setUp

    def setUp(self):
        self.red = finding(
            severity="blocker", category="security",
            title="API key committed in the source",
            recommendation="Move the key to the secret store "
                           "and rotate it")
        # NOTE: the yellow fixture's title avoids the money
        # keywords on purpose — a money-titled correctness
        # finding is red by the §4 classes (pinned in
        # BucketTests.test_money_mistake_is_red).
        self.yellow = finding(
            severity="major", category="correctness",
            title="Report sum is wrong when a reduction "
                  "applies",
            recommendation="Apply the reduction before the "
                           "rounding step")
        self.grey = finding(
            severity="minor", category="quality",
            title="Debug statement left in added code",
            recommendation="Remove the debug line")

    def test_five_parts_present_for_every_bucket(self):
        for f in (self.red, self.yellow, self.grey):
            ex = guide.explain_finding(f)
            self.assertTrue(ex["what"])
            self.assertTrue(ex["why"])
            self.assertTrue(ex["urgency"])
            self.assertGreaterEqual(len(ex["fix_steps"]), 2)
            self.assertTrue(
                ex["agent_instruction"].startswith(
                    "Tell your agent:"))

    def test_red_is_never_softened(self):
        ex = guide.explain_finding(self.red)
        self.assertEqual(ex["bucket"], "red")
        self.assertIn("before you ship", ex["urgency"])
        soft = ("fix soon", "when you have time",
                "does not stop you shipping", "fix it soon")
        for phrase in soft:
            self.assertNotIn(phrase, ex["urgency"].lower())
        text = guide.render_explanations([self.red])
        red_block = text.split("## ")[1]
        for phrase in soft:
            self.assertNotIn(phrase, red_block.lower())

    def test_explanation_comes_from_the_finding_data(self):
        a = guide.explain_finding(self.red)
        changed = dict(self.red,
                       title="Session token stored in plain "
                             "text")
        b = guide.explain_finding(changed)
        self.assertNotEqual(a["what"], b["what"])
        self.assertIn("Session token", b["what"])
        self.assertIn("app/main.py", a["what"])

    def test_render_groups_in_bucket_order(self):
        text = guide.render_explanations(
            [self.grey, self.yellow, self.red])
        self.assertLess(text.index("Fix before you ship"),
                        text.index("Fix soon"))
        self.assertLess(text.index("Fix soon"),
                        text.index("Nice to improve"))

    def test_render_uses_recorded_buckets_when_given(self):
        buckets = {self.red["id"]: {"bucket": "red",
                                     "reason": "r",
                                     "klass": "security"}}
        text = guide.render_explanations(
            [self.red], buckets=buckets)
        self.assertIn("Fix before you ship", text)


def run_cli(argv, **kw):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv, **kw)
    return rc, out.getvalue(), err.getvalue()


class GuideCliTests(unittest.TestCase):
    def write_patch(self, tmp, text):
        path = os.path.join(tmp, "change.diff")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_cli_guide_red_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = self.write_patch(tmp, PATCH_SECRET)
            rc, out, _ = run_cli(
                ["--patch", patch, "--gate-profile", "guide",
                 "--out", os.path.join(tmp, "out")],
                providers_override={"a": empty_provider})
            self.assertEqual(rc, 1)
            self.assertIn("NOT SAFE TO SHIP (1 red)", out)

    def test_cli_guide_yellow_only_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = self.write_patch(tmp, PATCH_ALERT)
            rc, out, _ = run_cli(
                ["--patch", patch, "--gate-profile", "guide",
                 "--out", os.path.join(tmp, "out")],
                providers_override={"a": empty_provider})
            self.assertEqual(rc, 0)
            self.assertIn("SHIP WITH KNOWN ISSUES (1 yellow)",
                          out)
            # The strict line is printed too — nothing hidden.
            self.assertIn("gate = BLOCKED", out)

    def test_cli_guide_clean_exits_0_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = self.write_patch(tmp, PATCH_CLEAN)
            rc, out, _ = run_cli(
                ["--patch", patch, "--gate-profile", "guide",
                 "--out", os.path.join(tmp, "out")],
                providers_override={"a": empty_provider})
            self.assertEqual(rc, 0)
            self.assertIn("READY TO SHIP", out)

    def test_cli_strict_unchanged_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            patch = self.write_patch(tmp, PATCH_ALERT)
            rc, out, _ = run_cli(
                ["--patch", patch,
                 "--out", os.path.join(tmp, "out")],
                providers_override={"a": empty_provider})
            self.assertEqual(rc, 1)
            self.assertNotIn("guide verdict", out)

    def test_explain_prints_five_parts(self):
        rep = core.run_review(PATCH_SECRET,
                              {"a": empty_provider},
                              gate_profile="guide")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "record.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(rep, fh)
            rc, out, _ = run_cli(["explain", path])
            self.assertEqual(rc, 0)
            for part in ("What is wrong:",
                         "Why it matters to you:",
                         "How urgent:", "How to fix:",
                         "Tell your agent:"):
                self.assertIn(part, out)
            self.assertIn("NOT SAFE TO SHIP (1 red)", out)

    def test_explain_missing_record_exits_2(self):
        rc, _, _ = run_cli(["explain", "/nonexistent/x.json"])
        self.assertEqual(rc, 2)

    def test_words_all_and_one(self):
        rc, out, _ = run_cli(["words"])
        self.assertEqual(rc, 0)
        self.assertIn("waiver", out)
        self.assertIn("verdict", out)
        rc, out, _ = run_cli(["words", "waiver"])
        self.assertEqual(rc, 0)
        self.assertIn("recorded decision", out)

    def test_words_unknown_term_exits_2(self):
        rc, _, err = run_cli(["words", "flibbertigibbet"])
        self.assertEqual(rc, 2)
        self.assertIn("flibbertigibbet", err)


if __name__ == "__main__":
    unittest.main()
