@echo off
setlocal
set "PROMPTCASE_PACKAGE_MODE=onedir"
call "%~dp0build-exe.bat" onedir
exit /b %errorlevel%
