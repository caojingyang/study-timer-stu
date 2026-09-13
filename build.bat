@echo off
setlocal enabledelayedexpansion
color 0B

:: ================================================
::   Study Timer System - One-Click Build Script
::   Automatically elevates, checks Python, installs
::   dependencies offline, and compiles to EXE.
:: ================================================

:: Auto-elevation: request admin privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: Change to script directory (handle relative paths)
cd /d "%~dp0"

echo.
echo ================================================
echo   Study Timer System - One-Click Build
echo ================================================
echo.
echo   Script directory: %~dp0
echo   Start time: %date% %time%
echo.

:: ================================================
:: Step 1: Check Python installation
:: ================================================
echo [Step 1/6] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   Python is NOT installed.
    echo.
    echo   Looking for offline Python installer...

    :: Try offline_packages directory first
    set "PY_INSTALLER="
    if exist "offline_packages\python-*.exe" (
        for %%f in (offline_packages\python-*.exe) do set "PY_INSTALLER=%%f"
    )
    if not defined PY_INSTALLER (
        if exist "python_packages\python-*.exe" (
            for %%f in (python_packages\python-*.exe) do set "PY_INSTALLER=%%f"
        )
    )

    if not defined PY_INSTALLER (
        echo   ERROR: No offline Python installer found!
        echo   Please place python-3.x.x-amd64.exe in:
        echo     - offline_packages\
        echo     - python_packages\
        echo.
        pause
        exit /b 1
    )

    echo   Found installer: !PY_INSTALLER!
    echo   Installing Python silently...
    echo   Please wait, this may take 1-2 minutes...
    echo.

    start /wait "" "!PY_INSTALLER!" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_pip=1

    :: Refresh PATH for current session
    call :refresh_path

    :: Verify installation
    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        :: Try common install paths
        set "PY_PATH=C:\Program Files\Python314"
        if exist "!PY_PATH!\python.exe" (
            set "PATH=!PY_PATH!;!PY_PATH!\Scripts;!PATH!"
        )
    )

    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo   ERROR: Python installation failed!
        echo   Please install Python manually and try again.
        pause
        exit /b 1
    )
    echo   Python installed successfully.
) else (
    echo   Python is already installed.
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo   Version: !PYVER!
echo.

:: ================================================
:: Step 2: Install dependencies (offline mode)
:: ================================================
echo [Step 2/6] Installing dependencies...

:: Determine offline package directory
set "PKG_DIR="
if exist "python_packages\requirements.txt" set "PKG_DIR=python_packages"
if not defined PKG_DIR if exist "offline_packages\requirements.txt" set "PKG_DIR=offline_packages"
if not defined PKG_DIR if exist "python_packages" set "PKG_DIR=python_packages"
if not defined PKG_DIR if exist "offline_packages" set "PKG_DIR=offline_packages"

if not defined PKG_DIR (
    echo   WARNING: No offline package directory found.
    echo   Attempting online installation...
    pip install pyinstaller pystray Pillow six pywebview
    goto deps_done
)

echo   Using offline packages from: %PKG_DIR%
echo.

:: Upgrade pip from local packages (if available)
dir /b "%PKG_DIR%\pip-*.whl" >nul 2>&1
if %errorlevel% equ 0 (
    echo   Upgrading pip...
    python -m pip install --no-index --find-links="%PKG_DIR%" --upgrade pip >nul 2>&1
    if !errorlevel! equ 0 (
        echo   pip upgraded successfully.
    ) else (
        echo   pip upgrade skipped (using current version).
    )
    echo.
)

:: Install from requirements.txt
if exist "%PKG_DIR%\requirements.txt" (
    echo   Installing from requirements.txt...
    pip install --no-index --find-links="%PKG_DIR%" -r "%PKG_DIR%\requirements.txt"
    if !errorlevel! neq 0 (
        echo   WARNING: Some packages failed to install from requirements.
        echo   Trying individual installation...
        for %%p in (pystray Pillow python-xlib six pyinstaller altgraph packaging pyinstaller-hooks-contrib setuptools pywebview) do (
            pip install --no-index --find-links="%PKG_DIR%" %%p >nul 2>&1
            if !errorlevel! equ 0 (
                echo     %%p - OK
            ) else (
                echo     %%p - FAILED, trying online...
                pip install %%p >nul 2>&1
                if !errorlevel! equ 0 (
                    echo     %%p - OK (online)
                ) else (
                    echo     %%p - FAILED
                )
            )
        )
    )
) else (
    echo   No requirements.txt found, installing core packages...
    for %%p in (pystray Pillow python-xlib six pyinstaller altgraph packaging pyinstaller-hooks-contrib setuptools pywebview) do (
        pip install --no-index --find-links="%PKG_DIR%" %%p >nul 2>&1
        if !errorlevel! equ 0 (
            echo     %%p - OK
        ) else (
            echo     %%p - FAILED
        )
    )
)

:deps_done
echo.
echo   Verifying installed packages...
set PKG_OK=1
pip show pyinstaller >nul 2>&1
if !errorlevel! neq 0 (
    echo   pyinstaller - MISSING
    set PKG_OK=0
) else (
    echo   pyinstaller - OK
)
pip show pystray >nul 2>&1
if !errorlevel! neq 0 (
    echo   pystray - MISSING
    set PKG_OK=0
) else (
    echo   pystray - OK
)
pip show Pillow >nul 2>&1
if !errorlevel! neq 0 (
    echo   Pillow - MISSING
    set PKG_OK=0
) else (
    echo   Pillow - OK
)

if !PKG_OK! equ 0 (
    echo.
    echo   ERROR: Required packages are missing!
    echo   Please check your offline package directory.
    pause
    exit /b 1
)
echo   All dependencies installed.
echo.

:: ================================================
:: Step 3: Clean previous build artifacts
:: ================================================
echo [Step 3/6] Cleaning previous build artifacts...

if exist "build" rmdir /s /q "build" 2>nul
if exist "dist" rmdir /s /q "dist" 2>nul
if exist "start_server.spec" del /q "start_server.spec" 2>nul
if exist "update.spec" del /q "update.spec" 2>nul

echo   Build directories cleaned.
echo.

:: ================================================
:: Step 4: Compile start_server.exe
:: ================================================
echo [Step 4/6] Compiling start_server.exe...
echo   Icon: icon.ico
echo   This may take 2-5 minutes, please wait...
echo.

if not exist "start_server.py" (
    echo   ERROR: start_server.py not found!
    pause
    exit /b 1
)

:: Build start_server with ui.html and update.html bundled
set ADD_DATA_ARGS=
if exist "ui.html" (
    set ADD_DATA_ARGS=--add-data "ui.html;."
)
if exist "update.html" (
    set ADD_DATA_ARGS=!ADD_DATA_ARGS! --add-data "update.html;."
)

pyinstaller --onefile --noconsole --name "start_server" --icon "icon.ico" ^
    !ADD_DATA_ARGS! ^
    --hidden-import pystray ^
    --hidden-import pystray._win32 ^
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --hidden-import webview ^
    --collect-submodules pystray ^
    --collect-all pystray ^
    --collect-all PIL ^
    --collect-all webview ^
    --exclude-module unittest ^
    --exclude-module pytest ^
    --exclude-module tkinter ^
    start_server.py

if !errorlevel! neq 0 (
    echo.
    echo   ERROR: start_server.exe build failed!
    pause
    exit /b 1
)
echo   start_server.exe built successfully.
echo.

:: ================================================
:: Step 5: Compile update.exe
:: ================================================
echo [Step 5/6] Compiling update.exe...
echo   Icon: update.ico
echo   This may take 1-2 minutes, please wait...
echo.

if not exist "update.py" (
    echo   ERROR: update.py not found!
    pause
    exit /b 1
)

:: Build update with update.html bundled
set UPDATE_DATA_ARGS=
if exist "update.html" (
    set UPDATE_DATA_ARGS=--add-data "update.html;."
)

pyinstaller --onefile --noconsole --name "update" --icon "update.ico" ^
    !UPDATE_DATA_ARGS! ^
    --hidden-import tkinter ^
    --hidden-import webview ^
    --collect-all webview ^
    --exclude-module unittest ^
    --exclude-module pytest ^
    update.py

if !errorlevel! neq 0 (
    echo.
    echo   ERROR: update.exe build failed!
    pause
    exit /b 1
)
echo   update.exe built successfully.
echo.

:: ================================================
:: Step 6: Copy files to current directory
:: ================================================
echo [Step 6/6] Copying built files to current directory...

:: Copy EXE files
if exist "dist\start_server.exe" (
    copy /y "dist\start_server.exe" "start_server.exe" >nul
    echo   start_server.exe copied.
) else (
    echo   WARNING: start_server.exe not found in dist\
)

if exist "dist\update.exe" (
    copy /y "dist\update.exe" "update.exe" >nul
    echo   update.exe copied.
) else (
    echo   WARNING: update.exe not found in dist\
)

:: Copy supporting static files to dist (for distribution)
echo.
echo   Copying static resources to dist\...
for %%f in (study_timer.html seat.html seat_choose.html seat_online.html ui.html update.html history.html remote.html ^
    icon.ico icon.jpg background.png timer.mp3 ^
    tailwind.min.css font-awesome.min.css tailwind.js xlsx.bundle.min.js) do (
    if exist "%%f" (
        copy /y "%%f" "dist\%%f" >nul 2>&1
        echo     %%f copied.
    )
)
if exist "fonts" (
    xcopy /y /i /e "fonts" "dist\fonts" >nul 2>&1
    echo     fonts\ copied.
)

:: Clean up build artifacts
if exist "build" rmdir /s /q "build" 2>nul
if exist "start_server.spec" del /q "start_server.spec" 2>nul
if exist "update.spec" del /q "update.spec" 2>nul

echo.
echo ================================================
echo   Build Complete!
echo ================================================
echo.
echo   Output files in dist\:
echo     - start_server.exe  (Main server program)
echo     - update.exe        (Online update tool)
echo     - Static resources   (HTML, images, etc.)
echo.
echo   Also copied to current directory:
echo     - start_server.exe
echo     - update.exe
echo.
echo   End time: %date% %time%
echo.
echo   Press any key to exit...
pause >nul
exit /b 0

:: ================================================
:: Subroutine: Refresh PATH after Python install
:: ================================================
:refresh_path
:: Refresh PATH for the current session
for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul`) do set "SYS_PATH=%%B"
for /f "usebackq tokens=2,*" %%A in (`reg query "HKCU\Environment" /v PATH 2^>nul`) do set "USR_PATH=%%B"
if defined SYS_PATH set "PATH=!SYS_PATH!;!PATH!"
if defined USR_PATH set "PATH=!USR_PATH!;!PATH!"
goto :eof
