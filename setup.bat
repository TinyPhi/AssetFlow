@echo off
rem SPDX-FileCopyrightText: 2026 TinyPhi
rem SPDX-License-Identifier: AGPL-3.0-only
rem One-command setup on Windows: runs scripts\bootstrap.ps1 (§B13.1, M1.6-T8).
rem   setup.bat                   set up minimal profile (safe to run again)
rem   setup.bat -Profile full     set up full profile
rem   setup.bat -DryRun           show what would change
rem   setup.bat -Reset            delete the local volumes first (development only)
rem   setup.bat -NoDemo           skip demo organization and users
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" %*
exit /b %ERRORLEVEL%
