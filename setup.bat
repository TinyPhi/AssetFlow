@echo off
rem SPDX-FileCopyrightText: 2026 TinyPhi
rem SPDX-License-Identifier: AGPL-3.0-only
rem One-command identity setup on Windows: runs scripts\bootstrap.ps1 (docs/operations/zitadel.md).
rem   setup.bat            set up or re-apply (safe to run again)
rem   setup.bat -DryRun    show what would change
rem   setup.bat -Reset     delete the local Zitadel volumes first (development only)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" %*
exit /b %ERRORLEVEL%
