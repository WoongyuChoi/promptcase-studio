@echo off
chcp 65001 >nul
setlocal EnableExtensions
pushd "%~dp0" >nul
python main.py
set "RUN_EXIT_CODE=%ERRORLEVEL%"
popd >nul
if not "%RUN_EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Promptcase Studio exited with code %RUN_EXIT_CODE%.
  pause
)
exit /b %RUN_EXIT_CODE%

