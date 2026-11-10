"""Shared test-command runner (external review 2026-11-10, §4.3).

The test-command runner used to exist twice: the CLI's
`_run_tests` and the workflow engine's `_tests` closure inside
`run_workflow`. Only the CLI copy caught
`subprocess.TimeoutExpired` — a test command exceeding the
timeout raised out of the workflow step and crashed the
workflow — and both copies killed only the shell on timeout,
so child processes the command had spawned could keep running
as orphans.

This module is the single implementation both call sites use:

* shell=True is deliberate: test commands are operator-supplied
  shell strings (the same trust level as a CI config the
  operator wrote). They are never taken from the diff under
  review.
* Each command starts in its OWN process group
  (start_new_session=True, POSIX); on timeout the whole group
  is killed, not just the shell, so no spawned child survives.
  Two limits, stated plainly: (a) a child that ESCAPES the
  group (setsid, double-fork) cannot be killed by the group
  kill, and if it still holds the output pipes the post-kill
  drain is bounded (_DRAIN_SECONDS) — the failed result is
  returned anyway, escaped child or not; (b) on Windows
  start_new_session has no effect and only the shell is
  killed (see issue #12).
* A timeout is a failed RESULT, never an exception: the
  returned entry is {command, ok: False, exit_code: None,
  output_tail: "timed out"} — the historical CLI shape.
* Output is redacted at production (audit T standard): a
  failing test that echoes config or env must not put a secret
  into prompts or the record downstream. Only the last 4000
  characters of combined stdout+stderr are kept.

The redactor defaults to core.redact_secrets; it is imported
lazily so this module has no import cycle with core.
"""

from __future__ import annotations

import os
import signal
import subprocess

TIMEOUT_SECONDS = 1800
_DRAIN_SECONDS = 5
_TAIL_CHARS = 4000
_TIMEOUT_TAIL = "timed out"


def _default_redact(text):
    from .core import redact_secrets
    return redact_secrets(text)


def _kill_group(proc):
    """Kill the process group `proc` was started in (POSIX).

    The command was started with start_new_session=True, so its
    process-group id is its own pid and killing the group takes
    the shell and every child it spawned. A group that is
    already gone is not an error. On non-POSIX there is no group
    to kill; fall back to killing the process itself."""
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def run_commands(commands, cwd, *, timeout=TIMEOUT_SECONDS,
                 redact=None):
    """Run each shell command in `commands` in `cwd` and return
    one result dict per command:
    {command, ok, exit_code, output_tail}.

    Never raises for a command that fails or times out — both
    are ordinary failed results. `redact` overrides the output
    redactor (default: core.redact_secrets)."""
    redact = redact or _default_redact
    results = []
    for cmd in commands or []:
        proc = subprocess.Popen(
            cmd, shell=True, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        try:
            out_b, err_b = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            # Reap and drain, BOUNDED: a child that escaped the
            # process group (setsid, double-fork) can still hold
            # the output pipes open, and an unbounded
            # communicate() would then block until IT exits —
            # the 2s timeout would take as long as the child
            # lives. Drain with a bound; on a second timeout,
            # close our ends of the pipes and return the failed
            # result anyway. The escaped child itself cannot be
            # killed by the group kill (module docstring).
            try:
                proc.communicate(timeout=_DRAIN_SECONDS)
            except subprocess.TimeoutExpired:
                for stream in (proc.stdout, proc.stderr):
                    try:
                        if stream is not None:
                            stream.close()
                    except OSError:
                        pass
                try:
                    proc.wait(timeout=_DRAIN_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
            results.append({"command": cmd, "ok": False,
                            "exit_code": None,
                            "output_tail": _TIMEOUT_TAIL})
            continue
        tail = (out_b + err_b).decode(
            "utf-8", errors="replace")[-_TAIL_CHARS:]
        results.append({"command": cmd,
                        "ok": proc.returncode == 0,
                        "exit_code": proc.returncode,
                        "output_tail": redact(tail)})
    return results
