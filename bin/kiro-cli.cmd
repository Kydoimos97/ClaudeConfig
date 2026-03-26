@echo off
setlocal

for /f "delims=" %%i in ('wsl -d Ubuntu wslpath "%CD%"') do set WSLPWD=%%i

wsl -d Ubuntu --cd "%WSLPWD%" ~/.local/bin/kiro-cli %*