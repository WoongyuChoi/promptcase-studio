@echo off
setlocal
pushd "%~dp0"

for /f "usebackq delims=" %%V in (`py -c "from promptcase_studio import __version__; print(__version__)"`) do set "APP_VERSION=%%V"
if not defined APP_VERSION goto :failed

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
    set "BUILD_FOLDER=%CD%\dist\PromptcaseStudio-%APP_VERSION%"
    set "BUILD_OUTPUT=%CD%\dist\PromptcaseStudio-%APP_VERSION%\PromptcaseStudio.exe"
    set "BUILD_ARCHIVE=%CD%\dist\PromptcaseStudio-%APP_VERSION%-windows-x64.zip"
) else (
    echo Invalid PROMPTCASE_PACKAGE_MODE: %PROMPTCASE_PACKAGE_MODE%
    echo Use onefile or onedir.
    popd
    exit /b 2
)

echo [1/2] Installing build dependencies...
py -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto :failed

echo [2/2] Building PromptcaseStudio %PACKAGE_LABEL% package v%APP_VERSION%...
py -m PyInstaller --noconfirm --clean promptcase-studio.spec
if errorlevel 1 goto :failed

if /I "%PROMPTCASE_PACKAGE_MODE%"=="onedir" (
    copy /Y "%CD%\docs\RUN_FIRST.txt" "%BUILD_FOLDER%\RUN_FIRST.txt" >nul
    echo Creating complete folder archive...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -LiteralPath '%BUILD_FOLDER%' -DestinationPath '%BUILD_ARCHIVE%' -CompressionLevel Optimal -Force"
    if errorlevel 1 goto :failed
)

echo.
echo Build complete: %BUILD_OUTPUT% ^(v%APP_VERSION%^)
if /I "%PROMPTCASE_PACKAGE_MODE%"=="onedir" echo Distribute this archive: %BUILD_ARCHIVE%
popd
exit /b 0

:failed
echo.
echo Build failed. Review the output above.
popd
exit /b 1
