@echo off
setlocal
pushd "%~dp0"

if /I "%~1"=="onedir" (
    set "PROMPTCASE_PACKAGE_MODE=onedir"
) else (
    set "PROMPTCASE_PACKAGE_MODE=onefile"
)
if /I "%PROMPTCASE_PACKAGE_MODE%"=="onefile" (
    set "PACKAGE_LABEL=one-file"
    set "BUILD_OUTPUT=%CD%\dist\PromptcaseStudio.exe"
) else if /I "%PROMPTCASE_PACKAGE_MODE%"=="onedir" (
    set "PACKAGE_LABEL=folder"
    set "BUILD_OUTPUT=%CD%\dist\PromptcaseStudio-folder\PromptcaseStudio.exe"
) else (
    echo Invalid PROMPTCASE_PACKAGE_MODE: %PROMPTCASE_PACKAGE_MODE%
    echo Use onefile or onedir.
    popd
    exit /b 2
)

for /f "usebackq delims=" %%V in (`py -c "from promptcase_studio import __version__; print(__version__)"`) do set "APP_VERSION=%%V"

echo [1/2] Installing build dependencies...
py -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto :failed

echo [2/2] Building PromptcaseStudio %PACKAGE_LABEL% package v%APP_VERSION%...
py -m PyInstaller --noconfirm --clean promptcase-studio.spec
if errorlevel 1 goto :failed

echo.
echo Build complete: %BUILD_OUTPUT% ^(v%APP_VERSION%^)
popd
exit /b 0

:failed
echo.
echo Build failed. Review the output above.
popd
exit /b 1
