@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "PYTHON_PACKAGE_ID=Python.Python.3.11"
set "OLLAMA_PACKAGE_ID=Ollama.Ollama"
set "DEFAULT_OLLAMA_MODEL=dolphin3"
set "SETUP_MARKER=.setup-complete"
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "OLLAMA_EXE="
set "HAS_WINGET="
set "OLLAMA_MODEL=%DEFAULT_OLLAMA_MODEL%"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"

echo.
echo ==========================================
echo           NovaAI Windows Setup
echo ==========================================
echo.

call :detect_winget

echo [1/8] Checking Python 3.11...
call :resolve_python_311
if errorlevel 1 (
    call :install_python || exit /b 1

    REM Refresh PATH for this session
    call :refresh_path

    call :resolve_python_311
    if errorlevel 1 (
        echo Python 3.11 was installed, but this shell cannot find it yet.
        echo Close this window, open a new one, and run setup.bat again.
        exit /b 1
    )
)
echo      Using Python launcher: %PYTHON_EXE% %PYTHON_ARGS%
echo.

echo [2/8] Creating the virtual environment...
if not exist ".venv\Scripts\python.exe" (
    call :run_python -m venv .venv
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        exit /b 1
    )
)
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
set "PYTHON_ARGS="
echo      Virtual environment ready.
echo.

echo [3/8] Installing Python packages...
call :run_python -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    exit /b 1
)
call :run_python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements.txt.
    exit /b 1
)
echo      Python dependencies installed.
echo.

echo [4/8] Preparing project files...
if not exist "data" mkdir data
if not exist "audio" mkdir audio
if not exist ".env" copy /y ".env.example" ".env" >nul
if not exist "data\profile.json" if exist "data\profile.example.json" copy /y "data\profile.example.json" "data\profile.json" >nul
call :read_ollama_model
echo      Runtime files are ready.
echo.

echo [5/8] Checking Ollama...
call :resolve_ollama
if errorlevel 1 (
    call :install_ollama || exit /b 1

    REM Refresh PATH again
    call :refresh_path

    call :resolve_ollama
    if errorlevel 1 (
        echo Ollama was installed, but this shell cannot find it yet.
        echo Close this window, open a new one, and run setup.bat again.
        exit /b 1
    )
)
echo      Using Ollama executable: %OLLAMA_EXE%
echo.

echo [6/8] Starting Ollama...
call :ensure_ollama_running
if errorlevel 1 exit /b 1
echo      Ollama API is online.
echo.

echo [7/8] Pulling the chat model (%OLLAMA_MODEL%)...
call :ensure_ollama_model
if errorlevel 1 exit /b 1
echo      Ollama model is ready.
echo.

echo [8/8] Preloading speech and voice models...
call :preload_runtime_models
if errorlevel 1 exit /b 1
echo      Speech and XTTS models are cached.
echo.

>"%SETUP_MARKER%" (
    echo setup_completed=1
    echo ollama_model=%OLLAMA_MODEL%
)

echo ==========================================
echo           NovaAI setup complete
echo ==========================================
echo.
echo Run the desktop GUI:
echo   .\launch_gui.bat
echo.
echo Run the GUI directly:
echo   .\.venv\Scripts\python.exe app.py --gui
echo.
echo Run the terminal version:
echo   .\.venv\Scripts\python.exe app.py
echo.

endlocal
exit /b 0


:detect_winget
set "HAS_WINGET="
where winget >nul 2>nul
if not errorlevel 1 set "HAS_WINGET=1"
exit /b 0


:require_winget
if defined HAS_WINGET exit /b 0
echo winget is required to install missing dependencies automatically.
echo Install Microsoft App Installer, then run setup.bat again.
exit /b 1


:resolve_python_311
set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3.11 -V >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3.11"
        exit /b 0
    )
)

if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
    exit /b 0
)

if exist "%ProgramFiles%\Python311\python.exe" (
    set "PYTHON_EXE=%ProgramFiles%\Python311\python.exe"
    exit /b 0
)

exit /b 1


:run_python
"%PYTHON_EXE%" %PYTHON_ARGS% %*
exit /b %errorlevel%


:install_python
call :require_winget || exit /b 1
echo      Python 3.11 is missing. Installing with winget...
winget install -e --id %PYTHON_PACKAGE_ID% --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity --silent
if errorlevel 1 (
    echo Failed to install Python 3.11 with winget.
    exit /b 1
)
exit /b 0


:resolve_ollama
set "OLLAMA_EXE="

if exist "%LocalAppData%\Programs\Ollama\ollama.exe" (
    set "OLLAMA_EXE=%LocalAppData%\Programs\Ollama\ollama.exe"
    exit /b 0
)

for /f "delims=" %%I in ('where ollama 2^>nul') do (
    set "OLLAMA_EXE=%%I"
    exit /b 0
)

exit /b 1


:install_ollama
call :require_winget || exit /b 1
echo      Ollama is missing. Installing with winget...
winget install -e --id %OLLAMA_PACKAGE_ID% --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity --silent
if errorlevel 1 (
    echo Failed to install Ollama with winget.
    exit /b 1
)
exit /b 0


:refresh_path
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul') do set "SYS_PATH=%%B"
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "USR_PATH=%%B"
set "PATH=%SYS_PATH%;%USR_PATH%"
exit /b 0


:read_ollama_model
set "OLLAMA_MODEL=%DEFAULT_OLLAMA_MODEL%"
if not exist ".env" exit /b 0

for /f "usebackq tokens=1* delims==" %%A in (`findstr /b "OLLAMA_MODEL=" ".env"`) do (
    if /i "%%A"=="OLLAMA_MODEL" set "OLLAMA_MODEL=%%B"
)

if not defined OLLAMA_MODEL set "OLLAMA_MODEL=%DEFAULT_OLLAMA_MODEL%"
exit /b 0


:ensure_ollama_running
set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

rem -- Quick check: is Ollama already running? (try curl first, then PowerShell)
curl -s -f --max-time 5 http://127.0.0.1:11434/api/tags >nul 2>nul
if not errorlevel 1 exit /b 0
if exist "%PS_EXE%" (
    "%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 | Out-Null; exit 0 } catch { exit 1 }"
    if not errorlevel 1 exit /b 0
)

rem -- Start Ollama
if exist "%LocalAppData%\Programs\Ollama\ollama app.exe" (
    start "" "%LocalAppData%\Programs\Ollama\ollama app.exe"
) else (
    start "" /MIN "%OLLAMA_EXE%" serve
)

rem -- Wait up to 60 s for Ollama to come online
set /a _oll_attempts=0
:ollama_wait_loop
timeout /t 1 /nobreak >nul
curl -s -f --max-time 5 http://127.0.0.1:11434/api/tags >nul 2>nul
if not errorlevel 1 exit /b 0
set /a _oll_attempts+=1
if %_oll_attempts% lss 60 goto ollama_wait_loop

echo Ollama did not come online within 60 seconds.
exit /b 1


:ensure_ollama_model
"%OLLAMA_EXE%" show "%OLLAMA_MODEL%" >nul 2>nul
if not errorlevel 1 exit /b 0

"%OLLAMA_EXE%" pull "%OLLAMA_MODEL%"
if errorlevel 1 (
    echo Failed to pull the Ollama model "%OLLAMA_MODEL%".
    exit /b 1
)

exit /b 0


:preload_runtime_models
call :run_python -m novaai.bootstrap
if errorlevel 1 (
    echo Failed to preload faster-whisper or XTTS model files.
    exit /b 1
)
exit /b 0
