"""The `guide` gate profile's decision layer and the
plain-English rendering of findings (OPC plan v2 §4/§5;
work packages W1 + W2).

`guide` is a gate profile for one-person companies and small
teams who build with AI coding agents but are not professional
programmers. It runs the strict pipeline unchanged — same
prompts, same merge, same adjudication, no demotions — and
then re-decides the outcome in shipping terms:

- every finding standing at the gate is sorted into one of
  three buckets (see `bucket_of`): red ("fix before you
  ship"), yellow ("fix soon"), grey ("nice to improve");
- the verdict is one of READY TO SHIP / SHIP WITH KNOWN
  ISSUES (n yellow) / NOT SAFE TO SHIP (n red) /
  COULD NOT CHECK. SHIP WITH KNOWN ISSUES is its own recorded
  state: it is never labelled PASS, and the record's strict
  `gate` field keeps whatever the strict gate said, so a
  guide ship is never counted as a strict pass;
- exit codes stay 0/1/2 (red present -> 1, could not check
  -> 2, otherwise 0 with the yellow count in the record).

The classification is a pure function of the finding data the
run already carries (severity, category, deterministic rule,
title) — deterministic and replayable, like every other gate
rule in this codebase. The plain-English explanations
(`explain_finding`) are generated from that same finding data
by the same rule, so there is no second source of truth: the
urgency words come from the bucket alone, and a red finding
cannot be softened into yellow wording (pinned by tests).

This module imports nothing from the engine; callers pass the
blocking-severity set the gate ran with.
"""

import re

BUCKETS = ("red", "yellow", "grey")

BUCKET_LABELS = {
    "red": "Fix before you ship",
    "yellow": "Fix soon",
    "grey": "Nice to improve",
}

# The guide verdict states. `verdict` is the human wording
# (with counts); `verdict_state` is the stable machine token.
READY_TO_SHIP = "ready_to_ship"
SHIP_WITH_KNOWN_ISSUES = "ship_with_known_issues"
NOT_SAFE_TO_SHIP = "not_safe_to_ship"
COULD_NOT_CHECK = "could_not_check"

VERDICT_STATES = (READY_TO_SHIP, SHIP_WITH_KNOWN_ISSUES,
                  NOT_SAFE_TO_SHIP, COULD_NOT_CHECK)

EXIT_CODES = {READY_TO_SHIP: 0, SHIP_WITH_KNOWN_ISSUES: 0,
              NOT_SAFE_TO_SHIP: 1, COULD_NOT_CHECK: 2}

DEFAULT_BLOCKING_SEVS = ("blocker", "major")

# Deterministic-scan rules whose finding is ship-stopping by
# construction, whatever category the rule files under: the
# project's own test command failed (the main path is broken
# as far as anyone can tell), and secret material in the code.
_RED_RULES = ("test-failure",)

# Money/payments mistakes are a red class (§4) but carry no
# category of their own — model findings file them under
# correctness/reliability. The signal is the finding's own
# title, matched on word boundaries.
_MONEY_RE = re.compile(
    r"(?i)\b(payments?|billing|charged?|charging|refunds?|"
    r"checkout|invoices?|prices?|pricing|currency|money|"
    r"stripe|paypal|amounts?|totals?|discounts?|tax(es)?)\b")

# Crashes on the main path are the other keyword-signalled red
# class. Word boundaries keep "crashlytics"-style names and
# "panic" in prose from tripping it.
_CRASH_RE = re.compile(
    r"(?i)\b(crash(es|ed|ing)?|segfault|segmentation fault|"
    r"panics?|panicked|stack overflow|unhandled exception|"
    r"fatal error)\b")

_RED_CATEGORIES = ("security", "data-loss")


def bucket_of(finding, blocking_sevs=DEFAULT_BLOCKING_SEVS):
    """Classify one finding standing at the gate ->
    (bucket, reason, klass).

    Red is reserved for the §4 ship-stopping classes: secrets
    and security holes, money/payments mistakes, data loss,
    crashes on the main path, and a failing test command.
    Everything else at blocking severity is yellow — a real
    bug or reliability risk that does not endanger users or
    data right now — and everything below blocking severity
    is grey. The severity the panel assigned is the
    centrality signal: a crash is red at blocking severity,
    where the reviewer judged it able to stop the program.
    """
    severity = finding.get("severity") or "minor"
    category = (finding.get("category") or "").lower()
    rule = finding.get("rule") or ""
    title = finding.get("title") or ""
    if severity not in blocking_sevs:
        if severity in ("blocker", "major"):
            return ("grey",
                    f"{severity}-severity finding, advisory "
                    f"under this gate's settings — not in a "
                    f"ship-stopping class and not blocking",
                    "advisory")
        return ("grey",
                f"{severity}-severity {category or 'general'} "
                f"item — style or minor polish, not a defect "
                f"that endangers users or data",
                "minor")
    if rule in _RED_RULES:
        return ("red",
                "the project's own test command failed — the "
                "change breaks behaviour the tests cover",
                "test-failure")
    if category in _RED_CATEGORIES:
        what = ("security hole or exposed secret"
                if category == "security" else
                "data loss")
        return ("red",
                f"{severity}-severity {category} finding — "
                f"{what} (a ship-stopping class under the "
                f"guide profile)",
                category)
    if _MONEY_RE.search(title):
        return ("red",
                f"{severity}-severity finding about money or "
                f"payments — charging the wrong amount, twice, "
                f"or losing a payment is a ship-stopping class "
                f"under the guide profile",
                "money")
    if _CRASH_RE.search(title):
        return ("red",
                f"{severity}-severity finding describing a "
                f"crash — a crash on the main path is a "
                f"ship-stopping class under the guide profile",
                "crash")
    return ("yellow",
            f"{severity}-severity {category or 'general'} "
            f"finding — a real bug or reliability risk, but "
            f"not in a ship-stopping class (no secret, "
            f"security hole, money mistake, data loss, or "
            f"main-path crash)",
            "blocking")


def classify(findings, blocking_sevs=DEFAULT_BLOCKING_SEVS):
    """Bucket every finding -> ({id: {bucket, reason, klass}},
    counts). Keyed by finding id (the record's identity);
    findings without an id are counted but cannot be keyed."""
    buckets = {}
    counts = {"red": 0, "yellow": 0, "grey": 0}
    for f in findings or []:
        bucket, reason, klass = bucket_of(f, blocking_sevs)
        counts[bucket] += 1
        fid = f.get("id")
        if fid:
            buckets[fid] = {"bucket": bucket, "reason": reason,
                            "klass": klass}
    return buckets, counts


def guide_section(findings, gate, blocking_sevs=
                  DEFAULT_BLOCKING_SEVS, non_finding_block=False):
    """The record's `guide` section + the per-finding stamps.

    `gate` is the strict gate the same run computed (the
    record keeps it untouched); `non_finding_block` says the
    gate was blocked by something other than findings (a
    blocking project-policy violation, required evidence, a
    tiering evidence requirement) — in that case guide never
    overrules the block with a shipping verdict, because the
    block is not the findings' to clear.

    Returns the section dict; its "buckets" maps each merged
    finding's id to its bucket entry (bucket, reason, class).
    """
    buckets, counts = classify(findings, blocking_sevs)
    red = counts["red"]
    yellow = counts["yellow"]
    if gate == "inconclusive":
        state = COULD_NOT_CHECK
        verdict = "COULD NOT CHECK"
    elif red:
        state = NOT_SAFE_TO_SHIP
        verdict = f"NOT SAFE TO SHIP ({red} red)"
    elif non_finding_block:
        state = NOT_SAFE_TO_SHIP
        verdict = "NOT SAFE TO SHIP"
    elif yellow:
        state = SHIP_WITH_KNOWN_ISSUES
        verdict = f"SHIP WITH KNOWN ISSUES ({yellow} yellow)"
    else:
        state = READY_TO_SHIP
        verdict = "READY TO SHIP"
    section = {
        "profile": "guide",
        "verdict": verdict,
        "verdict_state": state,
        "exit_code": EXIT_CODES[state],
        "strict_gate": gate,
        "red_count": red,
        "yellow_count": yellow,
        "grey_count": counts["grey"],
        "non_finding_block": bool(non_finding_block),
        "buckets": buckets,
    }
    return section


# ------------------------------------------------- plain English (§5)

_WHY_BY_KLASS = {
    "security": (
        "A security hole can let someone into your system or "
        "expose your customers' private data."),
    "data-loss": (
        "This can permanently delete or corrupt information "
        "your product needs — often with no way to get it "
        "back."),
    "money": (
        "A money mistake can charge a customer the wrong "
        "amount, charge them twice, or lose a payment — the "
        "kind of error customers notice at once and do not "
        "forgive."),
    "crash": (
        "If the app crashes while a customer is using it, "
        "they lose what they were doing and may not come "
        "back."),
    "test-failure": (
        "Your safety net says something is already broken. "
        "Shipping on top of it hides this problem under the "
        "next one."),
}

_WHY_BY_CATEGORY = {
    "security": _WHY_BY_KLASS["security"],
    "data-loss": _WHY_BY_KLASS["data-loss"],
    "correctness": (
        "The code does the wrong thing, so customers can see "
        "wrong results or run into broken behaviour."),
    "reliability": (
        "This can make the app crash, hang, or fail at the "
        "moment a customer is using it."),
    "performance": (
        "This can make the app slow. Slow apps lose customers "
        "and can raise your hosting bill."),
    "testing": (
        "The safety net that is supposed to catch mistakes "
        "is not working, so real problems can ship without "
        "anyone noticing."),
    "quality": (
        "Untidy code is harder to change safely — every "
        "future fix gets slower and riskier."),
}

_WHY_DEFAULT = (
    "This can cause problems for your customers if it ships "
    "as it is.")

_URGENCY = {
    "red": ("Urgent — fix this before you ship. Do not "
            "release while it is open."),
    "yellow": ("Not urgent today — fix it soon, in your "
               "next round of work. It does not stop you "
               "shipping."),
    "grey": ("Low — fix it when you have time. It does not "
             "stop you shipping."),
}


def explain_finding(finding, blocking_sevs=
                    DEFAULT_BLOCKING_SEVS, bucket=None):
    """The five-part plain-English explanation of one finding
    (§5): what is wrong, why it matters to you, how urgent,
    how to fix (numbered steps), and a ready-to-paste
    instruction for the reader's coding agent. Every part is
    derived from the finding's own fields — the same data
    the gate judged — so the explanation can never describe
    a different problem than the record holds. The urgency
    wording is a function of the bucket alone: a red finding
    always reads as fix-before-you-ship.
    """
    if bucket is None:
        bucket, _reason, klass = bucket_of(finding,
                                           blocking_sevs)
    else:
        _b, _reason, klass = bucket_of(finding, blocking_sevs)
    title = (finding.get("title") or "Untitled finding").strip()
    file = finding.get("file") or ""
    line = finding.get("line")
    loc = file
    if file and line:
        loc = f"{file}, line {line}"
    what = title if title.endswith((".", "!")) else title + "."
    if loc:
        what += f" It is in {loc}."
    why = (_WHY_BY_KLASS.get(klass)
           or _WHY_BY_CATEGORY.get(
               (finding.get("category") or "").lower())
           or _WHY_DEFAULT)
    rec = (finding.get("recommendation") or "").strip()
    steps = []
    if rec:
        steps.append(rec if rec.endswith(".") else rec + ".")
    if file:
        steps.append(f"Make the change in {file}"
                     + (f" (around line {line})." if line
                        else "."))
    steps.append("Run your tests, then run CodeReview again "
                 "to check the fix.")
    agent = (f"Tell your agent: Fix this problem"
             + (f" in {loc}" if loc else "")
             + f": {title}."
             + (f" Suggested fix: {steps[0]}" if rec else "")
             + " When you are done, run the tests and re-run "
               "CodeReview.")
    return {
        "bucket": bucket,
        "bucket_label": BUCKET_LABELS[bucket],
        "what": what,
        "why": why,
        "urgency": _URGENCY[bucket],
        "fix_steps": steps,
        "agent_instruction": agent,
    }


def render_explanations(findings, blocking_sevs=
                        DEFAULT_BLOCKING_SEVS, buckets=None):
    """Plain-text explanations for a list of findings,
    grouped red first, then yellow, then grey (the §4 display
    order). `buckets` may carry a run's recorded
    classification ({id: {bucket, ...}}); without it the
    buckets are recomputed from the finding data.
    """
    rows = []
    for f in findings or []:
        recorded = (buckets or {}).get(f.get("id") or "")
        bucket = (recorded or {}).get("bucket")
        rows.append((bucket or bucket_of(f, blocking_sevs)[0],
                     f))
    lines = []
    for bucket in BUCKETS:
        group = [f for b, f in rows if b == bucket]
        if not group:
            continue
        lines.append(f"## {BUCKET_LABELS[bucket]} "
                     f"({len(group)})")
        lines.append("")
        for f in group:
            ex = explain_finding(f, blocking_sevs, bucket)
            lines.append(f"### {f.get('title') or 'Untitled'}")
            lines.append(f"- What is wrong: {ex['what']}")
            lines.append(f"- Why it matters to you: {ex['why']}")
            lines.append(f"- How urgent: {ex['urgency']}")
            lines.append("- How to fix:")
            for i, step in enumerate(ex["fix_steps"], 1):
                lines.append(f"  {i}. {step}")
            lines.append(f"- {ex['agent_instruction']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------- glossary (§5)

GLOSSARY = {
    "blocker": (
        "The most serious kind of finding. The change must "
        "not ship until it is fixed or proven wrong."),
    "consensus": (
        "More than one reviewer reported the same problem "
        "independently, which makes it more likely to be "
        "real."),
    "deterministic": (
        "Checked by a fixed rule in the program itself, not "
        "by an AI opinion — the same input always gives the "
        "same answer."),
    "diff": (
        "The list of changes you are asking to review: lines "
        "added, removed, or changed. Also called a patch."),
    "evidence": (
        "The proof attached to a claim — for example the "
        "exact line of code a finding points at."),
    "family": (
        "The company behind a model (for example OpenAI, "
        "Google, DeepSeek). Reviewers from different "
        "families check each other's work."),
    "finding": (
        "One problem the reviewers found in your change, "
        "with where it is and how to fix it."),
    "gate": (
        "The final check that decides whether a change may "
        "ship. It reads all the findings and gives a "
        "verdict."),
    "lens": (
        "One way of looking at your code. The correctness "
        "lens hunts for bugs; the operations lens hunts for "
        "things that break in production."),
    "major": (
        "A serious finding. Under the strict gate it blocks "
        "shipping, like a blocker."),
    "minor": (
        "A small finding. It does not block shipping."),
    "panel": (
        "The group of AI reviewers assigned to look at your "
        "change."),
    "probe": (
        "A small test the tool runs against your code to "
        "check whether a claimed problem really happens."),
    "profile": (
        "A named set of gate rules. 'strict' blocks on "
        "every serious finding; 'guide' sorts findings "
        "into fix-before-you-ship, fix-soon, and "
        "nice-to-improve."),
    "record": (
        "The saved file describing one review: what was "
        "checked, what was found, and the verdict. You keep "
        "it, and it can be verified later."),
    "repository": (
        "The folder holding your project's code and its "
        "history (usually a git repository)."),
    "severity": (
        "How serious a finding is: blocker, major, minor, "
        "or nit."),
    "verdict": (
        "The gate's decision in words: under strict, PASS, "
        "BLOCKED, or INCONCLUSIVE; under guide, READY TO "
        "SHIP, SHIP WITH KNOWN ISSUES, NOT SAFE TO SHIP, "
        "or COULD NOT CHECK."),
    "waiver": (
        "Your recorded decision to accept a finding and "
        "ship anyway. It stays in the record; it is never "
        "hidden."),
}


def glossary_text(term=None):
    """The glossary, whole or one term. Returns None for an
    unknown term (the caller decides the exit code)."""
    if term is None:
        lines = ["CodeReview words — the few terms that "
                 "cannot be avoided, in plain English.", ""]
        for word in sorted(GLOSSARY):
            lines.append(f"{word}: {GLOSSARY[word]}")
        return "\n".join(lines) + "\n"
    key = str(term).strip().lower()
    if key not in GLOSSARY:
        return None
    return f"{key}: {GLOSSARY[key]}\n"
