# Installing CodeReview

CodeReview is a normal Python package (`codereview-ai`, Python
3.11+). The installers in this folder exist so a non-coder never
has to think about that: each one checks for a new-enough Python,
installs the package in an **isolated environment** (pipx when
available, otherwise a private virtual environment — your system
Python and other tools are never touched, and no administrator
rights are needed), and ends by printing the next steps.

## One-line installs

macOS / Linux:

```sh
curl -fsSL https://phpatch.com/codereview/install.sh | sh
```

Windows (PowerShell):

```powershell
irm https://phpatch.com/codereview/install.ps1 | iex
```

Both URLs serve the scripts in this folder (`install.sh` /
`install.ps1`). Prefer not to pipe a script into your shell? You
can also install with pipx or pip directly:

```sh
pipx install codereview-ai        # recommended
pip install --user codereview-ai  # works too
```

## Double-click installs — and their honest limits

- **macOS:** download `install.command` and double-click it. It
  opens Terminal and runs `install.sh`. **Limit:** the file is
  not signed or notarised, so Gatekeeper blocks the first
  double-click. Right-click the file, choose **Open**, then
  **Open** again in the dialog. That one-time step is Apple's
  rule for unsigned downloads; a signed installer is a
  post-launch item, not something we will simulate.
- **Windows:** download `install-windows.cmd` and double-click
  it. It runs `install.ps1` for you. **Limit:** the file is not
  signed, so SmartScreen warns on first run — click **More
  info**, then **Run anyway**. Same reasoning as macOS.

## After installing

```sh
codereview setup            # pick providers; you bring your own API keys
codereview doctor --plain   # every seat checked, problems in plain words with the fix
codereview                  # inside a git repo: your first review
```

Setup never asks for a key value and never stores one: it tells
you which environment variable each provider needs, and you set
it in your terminal. `doctor --plain` explains any problem it
finds (missing key, no quota, provider unreachable) in plain
words, with the fix, before you spend a review on it.

## For testers (pre-publication)

The installers take the package from PyPI by default. Before the
package is published, set `CODEREVIEW_INSTALL_SOURCE` to a local
checkout path or an exact spec and the installers use it instead:

```sh
CODEREVIEW_INSTALL_SOURCE=/path/to/codereview sh install.sh
```

```powershell
$env:CODEREVIEW_INSTALL_SOURCE = 'C:\path\to\codereview'; .\install.ps1
```

## Removing CodeReview

Delete the environment the installer created — pipx users:
`pipx uninstall codereview-ai`; everyone else: delete
`~/.local/share/codereview-venv` (macOS/Linux) or
`%LOCALAPPDATA%\codereview-venv` (Windows) and the `codereview`
link in `~/.local/bin` if one was made. Your setup file (which
contains provider names only, never keys) stays unless you
delete it too.
