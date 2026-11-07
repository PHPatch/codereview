"""W3 (OPC plan §6): installers + guided-setup surface.

Covers: the installer scripts exist and carry the load-bearing
properties (isolated install of codereview-ai, pipx preferred
with a private-venv fallback, Python >= 3.11 gate, honest
unsigned/double-click limits in the README); the setup wizard's
plain-words closing block (missing key variables named with the
export line to run; "You're ready" next steps; the wizard still
never handles a key value); and `codereview doctor --plain`
(same probe result rendered in plain words with a fix per
problem, JSON default byte-shape unchanged, exit codes equal).
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, setup_wizard  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
INSTALLERS = os.path.join(ROOT, "installers")


def _read(name):
    with open(os.path.join(INSTALLERS, name),
              encoding="utf-8") as fh:
        return fh.read()


class InstallerScriptTests(unittest.TestCase):
    def test_shell_installer_is_isolated_and_gated(self):
        text = _read("install.sh")
        self.assertIn("codereview-ai", text)
        self.assertIn("pipx", text)
        self.assertIn("-m venv", text)
        # Python floor matches pyproject's requires-python.
        self.assertIn("(3, 11)", text)
        # Pre-launch source override is documented in-script.
        self.assertIn("CODEREVIEW_INSTALL_SOURCE", text)

    def test_powershell_installer_is_isolated_and_gated(self):
        text = _read("install.ps1")
        self.assertIn("codereview-ai", text)
        self.assertIn("pipx", text)
        self.assertIn("-m venv", text)
        self.assertIn("(3, 11)", text)
        self.assertIn("CODEREVIEW_INSTALL_SOURCE", text)

    def test_double_click_wrappers_delegate_to_installers(self):
        self.assertIn("install.sh", _read("install.command"))
        self.assertIn("install.ps1",
                      _read("install-windows.cmd"))

    def test_next_steps_name_a_real_command(self):
        # There is no `review` subcommand — the bare command
        # IS the review. A next-steps line naming
        # `codereview review` would send a first-time user
        # into a usage error (found by the W3 sandbox smoke).
        for name in ("install.sh", "install.ps1", "README.md"):
            self.assertNotIn("codereview review", _read(name))

    def test_readme_states_unsigned_limits_honestly(self):
        text = _read("README.md")
        self.assertIn("not signed", text)
        self.assertIn("Gatekeeper", text)
        self.assertIn("SmartScreen", text)
        self.assertIn("pipx install codereview-ai", text)


class WizardClosingBlockTests(unittest.TestCase):
    def _run(self, answers, environ):
        it = iter(answers)
        printed = []
        result = setup_wizard.run_wizard(
            input_fn=lambda _prompt: next(it),
            print_fn=printed.append, environ=environ)
        return result, "\n".join(printed)

    def _env(self, tmp, **extra):
        env = {"HOME": tmp, "PATH": tmp,
               "CODEREVIEW_CONFIG":
                   os.path.join(tmp, "config.toml")}
        env.update(extra)
        return env

    def test_missing_key_gets_export_hint_and_ready_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, out = self._run(
                ["deepseek", "", "", "", "-", ""],
                self._env(tmp))
            self.assertEqual(result["providers"], ["deepseek"])
            self.assertIn("DEEPSEEK_API_KEY", out)
            self.assertIn("export DEEPSEEK_API_KEY=", out)
            self.assertIn("You're ready. Next steps:", out)
            self.assertIn("codereview doctor --plain", out)
            # The closing block never asks for or echoes a key.
            self.assertNotIn("paste your key", out.lower())

    def test_set_key_skips_the_missing_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            _result, out = self._run(
                ["deepseek", "", "", "", "-", ""],
                self._env(tmp, DEEPSEEK_API_KEY="placeholder-w3"))
            self.assertNotIn("not set yet", out)
            self.assertIn("You're ready. Next steps:", out)


class DoctorPlainTests(unittest.TestCase):
    def _run_doctor(self, argv, providers):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli._doctor_main(
                argv, providers_override=providers)
        return code, buf.getvalue()

    def test_plain_all_ok(self):
        code, out = self._run_doctor(
            ["--plain"], {"stub": lambda prompt: "fine"})
        self.assertEqual(code, 0)
        self.assertIn("OK   stub — answers fine", out)
        self.assertIn("All seats OK", out)

    def test_plain_failure_names_problem_and_fix(self):
        def dead(prompt):
            raise RuntimeError("401 unauthorized: api key "
                               "not set")
        code, out = self._run_doctor(["--plain"],
                                     {"stub": dead})
        self.assertEqual(code, 2)
        self.assertIn("FAIL stub", out)
        self.assertIn("API key is missing or was rejected", out)
        self.assertIn("Fix:", out)

    def test_json_default_unchanged_shape(self):
        code, out = self._run_doctor(
            [], {"stub": lambda prompt: "fine"})
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["seats"][0]["name"], "stub")


if __name__ == "__main__":
    unittest.main()
