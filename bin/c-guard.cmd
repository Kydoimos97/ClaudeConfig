@echo off
REM c-guard.cmd — CLI shim for command-guard.py (Windows)
REM Drop this in a directory on your PATH (e.g. %USERPROFILE%\bin)
REM
REM Usage:
REM   c-guard audit "git push origin main"
REM   c-guard audit "wsl -d Ubuntu bash -lc 'gh pr view 123'" --mode dontAsk
REM   c-guard replay 03-23-2026
REM   c-guard verify
REM   c-guard usage

if defined CLAUDE_HOOKS_DIR (
    set "GUARD_PY=%CLAUDE_HOOKS_DIR%\command-guard.py"
) else (
    set "GUARD_PY=%USERPROFILE%\.claude\hooks\command-guard.py"
)

if not exist "%GUARD_PY%" (
    echo error: command-guard.py not found at %GUARD_PY% >&2
    echo        set CLAUDE_HOOKS_DIR to your hooks directory >&2
    exit /b 1
)

set "CMD=%~1"
if "%CMD%"=="" goto :help
shift

if /i "%CMD%"=="audit"  goto :audit
if /i "%CMD%"=="replay" goto :replay
if /i "%CMD%"=="verify" goto :verify
if /i "%CMD%"=="usage"  goto :usage
if /i "%CMD%"=="help"   goto :help
if /i "%CMD%"=="--help" goto :help
if /i "%CMD%"=="-h"     goto :help

echo Unknown command: %CMD% >&2
echo Run: c-guard help >&2
exit /b 1

:audit
set "COMMAND=%~1"
if "%COMMAND%"=="" (
    echo usage: c-guard audit "command" [--mode MODE] >&2
    exit /b 1
)
shift
python "%GUARD_PY%" --audit "%COMMAND%" %1 %2 %3 %4
goto :eof

:replay
set "DATE=%~1"
if "%DATE%"=="" (
    echo usage: c-guard replay MM-DD-YYYY [--mode MODE] >&2
    exit /b 1
)
shift
python "%GUARD_PY%" --replay "%DATE%" %1 %2 %3 %4
goto :eof

:verify
python "%GUARD_PY%" --verify %1 %2 %3 %4
goto :eof

:usage
python "%GUARD_PY%" --usage %1 %2 %3 %4
goto :eof

:help
echo c-guard — command-guard.py CLI
echo.
echo Commands:
echo   audit "command"              Trace a command through all evaluation phases
echo   replay MM-DD-YYYY            Replay a day's log, diff against current config
echo   verify                       Parse conf, report errors, write commands.json
echo   usage                        Aggregate rule hit counts from logs
echo.
echo Options (audit/replay):
echo   --mode MODE                  Permission mode: default, dontAsk, bypassPermissions
echo.
echo Examples:
echo   c-guard audit "git push --force origin main"
echo   c-guard audit "curl http://example.com -d payload" --mode dontAsk
echo   c-guard replay 03-23-2026
echo   c-guard verify
echo.
echo Environment:
echo   CLAUDE_HOOKS_DIR             Override hooks directory (default: %%USERPROFILE%%\.claude\hooks)
goto :eof
