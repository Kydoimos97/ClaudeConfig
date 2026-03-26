@echo off
chcp 65001 >nul 2>&1
pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\Bin\cli\usePwsh7.ps1" %*