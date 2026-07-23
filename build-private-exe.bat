@echo off
setlocal
set "PROMPTCASE_PRIVATE_BUNDLE=1"
call "%~dp0build-exe.bat"
exit /b %errorlevel%
