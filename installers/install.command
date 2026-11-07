#!/bin/sh
# CodeReview — macOS double-click installer.
#
# Download this file, then double-click it in Finder. It opens
# Terminal and runs the same installer as install.sh.
#
# Honest limits (also in installers/README.md): this file is NOT
# signed or notarised, so macOS Gatekeeper will block the first
# double-click. When that happens:
#   1. right-click (Control-click) the file and choose "Open";
#   2. in the dialog, click "Open" again.
# That one-time approval is Apple's rule for unsigned downloads —
# we will not pretend otherwise. If you would rather skip it,
# use the one-line Terminal install in installers/README.md.
#
# Set CODEREVIEW_INSTALL_SOURCE (see install.sh) before running
# to install from a non-PyPI source; normally not needed.

set -eu
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$DIR/install.sh" ]; then
    sh "$DIR/install.sh"
else
    # Standalone copy: fetch the installer next to this file.
    curl -fsSL https://phpatch.com/codereview/install.sh | sh
fi
echo ""
echo "You can close this window now."
