"""Fail-closed batch 1 — Duet fresh-eyes 2026-11-14 findings
A1, A2, A3, A6, A9, C1 (GitLab issues #16-#21).

Each test adapts the finding's repro with scripted seats. The
batch rule: malformed, unjudged, or never-cleared work must
never read as a clean pass — the gate fails closed (seat
failure / degraded / inconclusive / escalated), never silently
clean.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,4 @@\n"
    " import os\n"
    "+VALUE = compute_total(items)\n"
    "+print(VALUE)\n"
    "+RESULT = VALUE * 2\n")
CITED = "VALUE = compute_total(items)"
OTHER_LINE = "print(VALUE)"
THIRD_LINE = "RESULT = VALUE * 2"

META2 = {"seatA": {"family": "famA", "tier": "paid"},
         "seatB": {"family": "famB", "tier": "paid"}}
META3 = {"seatA": {"family": "famA", "tier": "paid"},
         "seatB": {"family": "famB", "tier": "paid"},
         "seatC": {"family": "famC", "tier": "paid"}}

PASS_PAYLOAD = {"verdict": "pass", "summary": "ok", "findings": []}


def mk_finding(sev="major", quote=CITED, file="app.py", line=2,
               title="Total computed without a guard"):
    return {"severity": sev, "category": "correctness",
            "file": file, "line": line, "title": title,
            "evidence": quote, "evidence_quote": quote,
            "recommendation": "guard it", "confidence": 0.9}


def seat_returning(payload):
    """A seat that answers every auxiliary prompt kind with a
    benign default and the review prompt with `payload`."""
    def fn(prompt):
        if "TECH LEAD ADJUDICATION" in prompt:
            return json.dumps({
                "decision": "sustain_finding",
                "evidence_quote": CITED,
                "rationale": "the finding stands"})
        if "CROSS-FAMILY CONFIRMATION" in prompt:
            return json.dumps({"verdict": "confirm"})
        if "RE-GROUND" in prompt:
            return json.dumps({"status": "confirmed",
                               "evidence_quote": CITED})
        if "VERIFICATION round" in prompt:
            return json.dumps({"resolutions": [], "new_findings": []})
        if isinstance(payload, str):
            return payload
        return json.dumps(payload)
    return fn


def run2(payload, patch=PATCH, **kw):
    kw.setdefault("seat_meta", META2)
    kw.setdefault("sleep", lambda *_a: None)
    return core.run_review(
        patch, {"seatA": seat_returning(payload),
                "seatB": seat_returning(payload)}, **kw)


class MalformedReplyTests(unittest.TestCase):
    """A1 (#16): a reply that parses as JSON but is not a review
    must fail the seat and degrade the run — never a clean PASS
    under --strict."""

    SHAPES = [
        ("findings as object", {"verdict": "pass", "findings": {"x": 1}}),
        ("findings as string", {"verdict": "pass", "findings": "none"}),
        ("empty object", {}),
        ("error object", {"error": "model unavailable"}),
        ("issues key", {"verdict": "pass",
                        "issues": [mk_finding()]}),
        ("verdict only", {"verdict": "changes_requested"}),
        ("findings not a list", {"verdict": "pass", "findings": 5}),
    ]

    def test_malformed_replies_never_pass_strict(self):
        for name, payload in self.SHAPES:
            with self.subTest(shape=name):
                rec = run2(payload, strict=True)
                self.assertEqual(rec["gate"], "inconclusive")
                self.assertTrue(rec["degraded"])

    def test_wellformed_empty_reply_still_passes(self):
        rec = run2(PASS_PAYLOAD, strict=True)
        self.assertEqual(rec["gate"], "pass")
        self.assertFalse(rec["degraded"])


class SeverityAliasTests(unittest.TestCase):
    """A2 (#17): severity aliases map to the canonical blocking
    severities; an unknown severity is a parse error, not a
    silent minor."""

    def _run_alias(self, sev):
        payload = {"verdict": "changes_requested",
                   "findings": [mk_finding(sev=sev)]}
        return run2(payload, strict=True)

    def test_critical_blocks_as_blocker(self):
        rec = self._run_alias("critical")
        self.assertEqual(rec["gate"], "blocked")
        self.assertEqual(rec["findings"][0]["severity"], "blocker")

    def test_high_blocks_as_major(self):
        rec = self._run_alias("High")
        self.assertEqual(rec["gate"], "blocked")
        self.assertEqual(rec["findings"][0]["severity"], "major")

    def test_blocker_with_trailing_space_blocks(self):
        rec = self._run_alias("blocker ")
        self.assertEqual(rec["gate"], "blocked")
        self.assertEqual(rec["findings"][0]["severity"], "blocker")

    def test_unknown_severity_fails_the_seat(self):
        rec = self._run_alias("urgent")
        self.assertEqual(rec["gate"], "inconclusive")
        self.assertTrue(rec["degraded"])

    def test_normalize_maps_aliases(self):
        f = core._normalize_finding(mk_finding(sev=" Critical "),
                                    "seat")
        self.assertEqual(f["severity"], "blocker")

    def test_normalize_unknown_severity_is_a_parse_error(self):
        with self.assertRaises(ValueError):
            core._normalize_finding(mk_finding(sev="urgent"), "seat")


# Assembled from fragments: the fixture-secret hygiene rule
# forbids secret-shaped literals in test files (the value the
# deterministic scan must catch is identical once joined).
SECRET_LINE = 'API_KEY = "' + "abcd1234" + "efgh5678" + '"'


def secret_patch(path):
    return (f"diff --git a/{path} b/{path}\n"
            f"--- /dev/null\n"
            f"+++ b/{path}\n"
            f"@@ -0,0 +1,1 @@\n"
            f"+{SECRET_LINE}\n")


ARCHIVED_PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    " import os\n"
    "+VALUE = compute_total(items)\n"
    "diff --git a/review-v096/codereview-20261104-000000.json "
    "b/review-v096/codereview-20261104-000000.json\n"
    "--- /dev/null\n"
    "+++ b/review-v096/codereview-20261104-000000.json\n"
    "@@ -0,0 +1,2 @@\n"
    "+{\"findings\": [{\"evidence\": \"result = "
    "eval(preserved_input)\"}]}\n"
    "+{\"note\": \"pre-fix lines preserved as evidence\"}\n"
    "diff --git a/gate-attempts.jsonl b/gate-attempts.jsonl\n"
    "--- /dev/null\n"
    "+++ b/gate-attempts.jsonl\n"
    "@@ -0,0 +1,1 @@\n"
    "+{\"gate\": \"blocked\", \"range\": \"a..b\"}\n")


class ArchivedScopeTests(unittest.TestCase):
    """A3 (#18): name-based archive exclusion applies only
    inside operator-designated record directories (the run's
    --out dir or --archived-dir entries). Everywhere else the
    paths are reviewed like everything else."""

    def _run(self, patch, **kw):
        kw.setdefault("seat_meta", META2)
        kw.setdefault("sleep", lambda *_a: None)
        return core.run_review(
            patch, {"seatA": seat_returning(PASS_PAYLOAD),
                    "seatB": seat_returning(PASS_PAYLOAD)}, **kw)

    def test_secret_under_review_dir_blocks_without_scope(self):
        rec = self._run(secret_patch("review_service/auth.py"),
                        strict=True)
        self.assertEqual(rec["gate"], "blocked")
        self.assertTrue(any(
            f.get("rule") == "hardcoded-secret"
            for f in rec["findings"]))

    def test_secret_in_plain_dir_blocks(self):
        rec = self._run(secret_patch("app/auth.py"), strict=True)
        self.assertEqual(rec["gate"], "blocked")

    def test_record_patch_not_excluded_without_scope(self):
        rec = self._run(ARCHIVED_PATCH, strict=True)
        self.assertEqual(rec["gate"], "blocked")
        self.assertTrue(any(
            f.get("rule") == "eval-exec" for f in rec["findings"]))

    def test_scoped_record_dirs_still_excluded(self):
        rec = self._run(
            ARCHIVED_PATCH, strict=True,
            archived_scope=["review-v096", "gate-attempts.jsonl"])
        self.assertEqual(rec["gate"], "pass")
        self.assertEqual(
            {e["path"] for e in rec["archived_exclusions"]},
            {"review-v096/codereview-20261104-000000.json",
             "gate-attempts.jsonl"})

    def test_archived_rule_unit(self):
        self.assertIsNone(core._archived_rule("review_service/auth.py"))
        self.assertIsNone(core._archived_rule("gate-attempts.jsonl"))
        self.assertIsNone(core._archived_rule(
            "src/review-v096/x.py", ["review-v096"]))
        self.assertEqual(
            core._archived_rule("review-v096/x.json", ["review-v096"]),
            "archived-scope:review-v096")
        self.assertEqual(
            core._archived_rule("gate-attempts.jsonl",
                                ["gate-attempts.jsonl"]),
            "archived-scope:gate-attempts.jsonl")


PATCH_A6 = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,5 @@\n"
    " import os\n"
    "+user = load_user()\n"
    "+VALUE = compute_total(items)\n"
    "+print(VALUE)\n"
    "+RESULT = VALUE * 2\n")


class ShapeSeat:
    """test_v100_integration's Seat contract: answers per prompt
    kind; the tech_lead payload is what varies here."""

    def __init__(self, review=None, xconfirm=None, tech_lead=None):
        self.review = ({"verdict": "pass", "summary": "ok",
                        "findings": []}
                       if review is None else review)
        self.xconfirm = ({"verdict": "confirm"}
                         if xconfirm is None else xconfirm)
        self.tech_lead = ({
            "decision": "sustain_refutation",
            "evidence_quote": THIRD_LINE,
            "rationale": "the refutation is correct on the code"}
            if tech_lead is None else tech_lead)

    def __call__(self, prompt):
        if "TECH LEAD ADJUDICATION" in prompt:
            payload = self.tech_lead
        elif "CROSS-FAMILY CONFIRMATION" in prompt:
            payload = self.xconfirm
        elif "RE-GROUND" in prompt:
            payload = {"status": "withdrawn",
                       "reason": "cannot support it"}
        else:
            payload = self.review
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return payload
        return json.dumps(payload)


def review3_a6(a, b, c, **kw):
    kw.setdefault("seat_meta", META3)
    kw.setdefault("sleep", lambda *_a: None)
    return core.run_review(
        PATCH_A6, {"seatA": a, "seatB": b, "seatC": c}, **kw)


def raiser_a6():
    return ShapeSeat(review={
        "verdict": "changes_requested",
        "findings": [mk_finding(line=3)]})


def refuter_a6():
    return ShapeSeat(xconfirm={
        "verdict": "refute", "evidence_quote": OTHER_LINE,
        "reason": "the claim is wrong"})


class TechLeadDismissalGroundingTests(unittest.TestCase):
    """A6 (#19): on the binding path a Tech Lead dismissal must
    meet the v2 dismissal standard — the deciding quote distinct
    from the refuter's and relevant to the claim. A bare 4-char
    quote that merely appears in the region dismisses nothing;
    the case escalates."""

    def _run(self, tl_payload):
        return review3_a6(raiser_a6(), refuter_a6(),
                          ShapeSeat(tech_lead=tl_payload))

    def test_four_char_quote_dismissal_escalates(self):
        rec = self._run({"decision": "sustain_refutation",
                         "evidence_quote": "user",
                         "rationale": "the claim is wrong"})
        self.assertEqual(rec.get("adjudicated_refuted_findings", []), [])
        self.assertEqual(len(rec.get("escalated_findings", [])), 1)

    def test_copied_refuter_quote_dismissal_escalates(self):
        rec = self._run({"decision": "sustain_refutation",
                         "evidence_quote": OTHER_LINE,
                         "rationale": "the claim is wrong"})
        self.assertEqual(rec.get("adjudicated_refuted_findings", []), [])
        self.assertEqual(len(rec.get("escalated_findings", [])), 1)

    def test_distinct_relevant_quote_still_sustains(self):
        rec = self._run({"decision": "sustain_refutation",
                         "evidence_quote": THIRD_LINE,
                         "rationale": "the refutation is correct"})
        self.assertEqual(len(rec["adjudicated_refuted_findings"]), 1)
        self.assertEqual(rec.get("escalated_findings", []), [])


CLEAN = """diff --git a/app/util.py b/app/util.py
--- a/app/util.py
+++ b/app/util.py
@@ -1,1 +1,4 @@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
"""

PREV_FINDING = {
    "id": "abc123", "severity": "major", "category": "reliability",
    "file": "app/alerts.py", "line": 6, "title": "Alert has no dedup",
    "evidence": "", "recommendation": "", "confidence": 0.8,
    "sources": ["a"], "consensus": False}

GOOD_EVIDENCE = ("return a + b and return a - b are the only "
                 "helpers left in app/util.py and the sendmail "
                 "alert is removed")


def fixed_seat(calls=None):
    def fixed(prompt):
        if calls is not None:
            calls.append(prompt)
        return json.dumps({
            "resolutions": [{"finding_id": "abc123",
                             "status": "fixed",
                             "evidence": GOOD_EVIDENCE}],
            "new_findings": []})
    return fixed


class VerificationGateCheckTests(unittest.TestCase):
    """A9 (#20), verification half: the previous gate outcome is
    checked, and verify-of-verify carries remaining + unjudged
    findings in the judged set."""

    def test_inconclusive_previous_is_refused(self):
        calls = []
        prev = {"gate": "inconclusive",
                "findings": [dict(PREV_FINDING)]}
        rec = core.run_verification(
            CLEAN, {"a": fixed_seat(calls), "b": fixed_seat(calls)},
            prev, "fixed it")
        self.assertEqual(rec["gate"], "inconclusive")
        self.assertEqual(calls, [])
        self.assertIn("previous", " ".join(rec["gate_reasons"]))

    def test_passed_previous_is_refused(self):
        calls = []
        prev = {"gate": "pass", "findings": [dict(PREV_FINDING)]}
        rec = core.run_verification(
            CLEAN, {"a": fixed_seat(calls), "b": fixed_seat(calls)},
            prev, "fixed it")
        self.assertEqual(rec["gate"], "inconclusive")
        self.assertEqual(calls, [])

    def test_blocked_previous_still_verifies(self):
        prev = {"gate": "blocked", "findings": [dict(PREV_FINDING)]}
        rec = core.run_verification(
            CLEAN, {"a": fixed_seat(), "b": fixed_seat()},
            prev, "fixed it")
        self.assertEqual(rec["gate"], "pass")
        self.assertEqual(len(rec["cleared"]), 1)

    def test_verify_of_verify_carries_unjudged(self):
        prev = {"gate": "blocked", "findings": [], "remaining": [],
                "unjudged": [dict(PREV_FINDING)]}
        rec = core.run_verification(
            CLEAN, {"a": fixed_seat(), "b": fixed_seat()},
            prev, "fixed it")
        self.assertEqual(rec["gate"], "pass")
        self.assertEqual([f["id"] for f in rec["cleared"]],
                         ["abc123"])

    def test_verify_of_verify_carries_remaining(self):
        def silent(prompt):
            return json.dumps({"resolutions": [], "new_findings": []})
        prev = {"gate": "blocked", "findings": [],
                "remaining": [dict(PREV_FINDING)], "unjudged": []}
        rec = core.run_verification(
            CLEAN, {"a": silent, "b": silent}, prev, "fixed it")
        self.assertEqual(rec["gate"], "blocked")
        self.assertEqual([f["id"] for f in rec["remaining"]],
                         ["abc123"])

    def test_unjudged_beats_blocked_when_another_remains(self):
        fx = {"id": "xxx111", "severity": "major",
              "category": "reliability", "file": "app/alerts.py",
              "line": 6, "title": "Alert has no dedup",
              "evidence": "", "recommendation": "", "confidence": 0.8,
              "sources": ["a"], "consensus": False}
        fy = {"id": "yyy222", "severity": "major",
              "category": "reliability", "file": "app/util.py",
              "line": 3, "title": "Sub has no guard",
              "evidence": "", "recommendation": "", "confidence": 0.8,
              "sources": ["b"], "consensus": False}

        def seat(prompt):
            # Both seats clear X (whose raiser "a" is absent, so X
            # is unjudged) and say nothing about Y (still open).
            return json.dumps({
                "resolutions": [{"finding_id": "xxx111",
                                 "status": "fixed",
                                 "evidence": GOOD_EVIDENCE}],
                "new_findings": []})
        prev = {"gate": "blocked", "findings": [fx, fy]}
        rec = core.run_verification(
            CLEAN, {"b": seat, "c": seat}, prev, "fixed it")
        self.assertEqual(rec["gate"], "inconclusive")
        self.assertEqual([f["id"] for f in rec["unjudged"]],
                         ["xxx111"])


LOOP_PATCH = (
    "diff --git a/f1.py b/f1.py\n"
    "--- a/f1.py\n"
    "+++ b/f1.py\n"
    "@@ -0,0 +1,1 @@\n"
    "+x = compute_risky(a)\n"
    "diff --git a/f2.py b/f2.py\n"
    "--- a/f2.py\n"
    "+++ b/f2.py\n"
    "@@ -0,0 +1,1 @@\n"
    "+y = compute_risky(b)\n")

LOOP_CLEAN = (
    "diff --git a/f1.py b/f1.py\n"
    "--- a/f1.py\n"
    "+++ b/f1.py\n"
    "@@ -1,1 +1,1 @@\n"
    "-x = compute_risky(a)\n"
    "+x = compute_safe(a)\n"
    "diff --git a/f2.py b/f2.py\n"
    "--- a/f2.py\n"
    "+++ b/f2.py\n"
    "@@ -1,1 +1,1 @@\n"
    "-y = compute_risky(b)\n"
    "+y = compute_safe(b)\n")

LOOP_CLEAN2 = (
    "diff --git a/f1.py b/f1.py\n"
    "--- a/f1.py\n"
    "+++ b/f1.py\n"
    "@@ -1,1 +1,1 @@\n"
    "-x = compute_safe(a)\n"
    "+x = compute_safe(a)  # guarded by caller check\n"
    "diff --git a/f2.py b/f2.py\n"
    "--- a/f2.py\n"
    "+++ b/f2.py\n"
    "@@ -1,1 +1,1 @@\n"
    "-y = compute_risky(b)\n"
    "+y = compute_safe(b)\n")

NEW_FINDING_N = {
    "severity": "major", "category": "correctness",
    "file": "f1.py", "line": 1,
    "title": "compute_safe result still unchecked",
    "evidence": "x = compute_safe(a)",
    "evidence_quote": "x = compute_safe(a)",
    "recommendation": "check the result", "confidence": 0.9}


class LoopCarriesUnjudgedTests(unittest.TestCase):
    """A9 (#20), loop half — Duet's scenario: round 1 seat A
    raises blocker X; round 2 A fails, so X is unjudged (the
    surviving seats confirm the fix, but the raiser never
    speaks), and a new blocker N blocks the round; round 3 must
    still judge X. The loop cannot finish PASS while
    finding_states lists X unresolved."""

    def test_loop_never_passes_with_unjudged_finding(self):
        ids = {}
        known_ids = set()

        def on_round(n, report):
            for f in report.get("findings") or []:
                known_ids.add(f["id"])
            if n == 1:
                for f in report["findings"]:
                    ids[f["file"]] = f["id"]

        def seat_a(prompt):
            if "VERIFICATION round" in prompt:
                raise RuntimeError("provider down")
            if "TECH LEAD ADJUDICATION" in prompt:
                return json.dumps({
                    "decision": "sustain_finding",
                    "evidence_quote": "x = compute_risky(a)"})
            if "CROSS-FAMILY CONFIRMATION" in prompt:
                return json.dumps({"verdict": "confirm"})
            if "RE-GROUND" in prompt:
                return json.dumps({
                    "status": "confirmed",
                    "evidence_quote": "x = compute_risky(a)"})
            return json.dumps({
                "verdict": "changes_requested",
                "findings": [mk_finding(
                    quote="x = compute_risky(a)", file="f1.py",
                    line=1, title="Risky call in f1")]})

        def verify_seat(own_file, own_quote):
            def fn(prompt):
                if "VERIFICATION round" in prompt:
                    if "guarded by caller check" in prompt:
                        evidence = (
                            "the new diff shows x = compute_safe(a) "
                            "guarded by caller check in f1.py and "
                            "y = compute_safe(b) in f2.py")
                        new_findings = []
                    else:
                        evidence = (
                            "the new diff shows x = compute_safe(a) "
                            "in f1.py and y = compute_safe(b) in "
                            "f2.py; the compute_risky calls are gone")
                        new_findings = [dict(NEW_FINDING_N)]
                    resolutions = [
                        {"finding_id": fid, "status": "fixed",
                         "evidence": evidence}
                        for fid in sorted(known_ids)]
                    return json.dumps({
                        "resolutions": resolutions,
                        "new_findings": new_findings})
                if "TECH LEAD ADJUDICATION" in prompt:
                    return json.dumps({
                        "decision": "sustain_finding",
                        "evidence_quote": own_quote})
                if "CROSS-FAMILY CONFIRMATION" in prompt:
                    return json.dumps({"verdict": "confirm"})
                if "RE-GROUND" in prompt:
                    return json.dumps({
                        "status": "confirmed",
                        "evidence_quote": own_quote})
                return json.dumps({
                    "verdict": "changes_requested",
                    "findings": [mk_finding(
                        quote=own_quote, file=own_file, line=1,
                        title="Risky call in " + own_file)]})
            return fn

        patches = [LOOP_PATCH]
        fixes = [LOOP_CLEAN, LOOP_CLEAN2, LOOP_CLEAN2]

        def get_patch():
            return patches[0]

        def builder(packet):
            patches[0] = fixes.pop(0) if fixes else LOOP_CLEAN2
            lines = [f"Finding {f['id']}: fixed — replaced with "
                     "compute_safe"
                     for f in packet["open_findings"]]
            return "\n".join(lines)

        result = core.run_loop(
            get_patch, builder,
            {"a": seat_a,
             "b": verify_seat("f2.py", "y = compute_risky(b)"),
             "c": verify_seat("f2.py", "y = compute_risky(b)")},
            max_rounds=3, on_round=on_round)
        self.assertEqual(result["final_gate"], "inconclusive")
        x_id = ids["f1.py"]
        self.assertEqual(
            result["finding_states"][x_id]["state"], "unresolved")


class MalformedFindingShapeTests(unittest.TestCase):
    """C1 (#21): seat-controlled shapes must degrade the run,
    never crash it."""

    def test_findings_scalar_degrades_not_crashes(self):
        rec = run2({"verdict": "pass", "findings": 5}, strict=True)
        self.assertEqual(rec["gate"], "inconclusive")

    def test_infinite_line_normalizes(self):
        raw = mk_finding()
        raw["line"] = float("inf")
        f = core._normalize_finding(raw, "seat")
        self.assertIsNotNone(f)
        self.assertIsNone(f["line"])


if __name__ == "__main__":
    unittest.main()
