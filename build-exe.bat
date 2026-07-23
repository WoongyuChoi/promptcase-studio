@echo off
setlocal
pushd "%~dp0"

for /f "usebackq delims=" %%V in (`py -c "from promptcase_studio import __version__; print(__version__)"`) do set "APP_VERSION=%%V"

echo [1/2] Installing build dependencies...
py -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto :failed

echo [2/2] Building PromptcaseStudio.exe v%APP_VERSION%...
py -m PyInstaller --noconfirm --clean promptcase-studio.spec
if errorlevel 1 goto :failed

echo.
echo Build complete: %CD%\dist\PromptcaseStudio.exe ^(v%APP_VERSION%^)
popd
exit /b 0

:failed
echo.
echo Build failed. Review the output above.
popd
exit /b 1
