@echo off
rem CodeReview — Windows double-click installer.
rem
rem Download this file, then double-click it. It opens a console
rem window and runs the same installer as install.ps1.
rem
rem Honest limits (also in installers\README.md): this file is
rem NOT signed, so Windows SmartScreen will warn on first run.
rem When that happens, click "More info", then "Run anyway".
rem That one-time approval is Microsoft's rule for unsigned
rem downloads — we will not pretend otherwise. If you would
rem rather skip it, use the one-line PowerShell install in
rem installers\README.md instead.
rem
rem If install.ps1 sits next to this file it is used; otherwise
rem the published copy is downloaded.

setlocal
set "DIR=%~dp0"
if exist "%DIR%install.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%install.ps1"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://phpatch.com/codereview/install.ps1 | iex"
)
echo.
echo You can close this window now.
pause
endlocal
