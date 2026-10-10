@echo off
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0未取得ファイルを取得.ps1" %*
set "取得結果=%ERRORLEVEL%"
echo.
pause
exit /b %取得結果%
