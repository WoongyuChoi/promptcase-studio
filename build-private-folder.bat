@echo off
setlocal
set "PROMPTCASE_PRIVATE_BUNDLE=1"
set "PROMPTCASE_PACKAGE_MODE=onedir"
call "%~dp0build-exe.bat" onedir
exit /b %errorlevel%
