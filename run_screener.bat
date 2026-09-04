@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: ============================================
:: Screener Auto — Windows Task Scheduler Runner
:: ============================================
:: Usage: run_screener.bat [idx|crypto|us|all]

set "PYTHON=C:\Users\Kimia Farma\.local\bin\python3.14.exe"
set "BASE_DIR=%~dp0"
set "PYTHONIOENCODING=utf-8"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TODAY=%%I"

if not exist "%PYTHON%" set "PYTHON=python"

set "SCREENER=%~1"
if "%SCREENER%"=="" set "SCREENER=all"

if not exist "%BASE_DIR%reports\idx" mkdir "%BASE_DIR%reports\idx"
if not exist "%BASE_DIR%reports\crypto" mkdir "%BASE_DIR%reports\crypto"
if not exist "%BASE_DIR%reports\us" mkdir "%BASE_DIR%reports\us"
if not exist "%BASE_DIR%logs" mkdir "%BASE_DIR%logs"

:: ---- IDX ----
if "%SCREENER%"=="idx" goto :run_idx
if "%SCREENER%"=="all" goto :run_idx
goto :skip_idx

:run_idx
echo [%TIME%] Running IDX screener...
"%PYTHON%" "%BASE_DIR%screeners\idx\scripts\tuntun_undervalued_screener.py" --universe IHSG --limit 30 --format markdown > "%BASE_DIR%reports\idx\%TODAY%.md" 2> "%BASE_DIR%logs\idx-%TODAY%.err"
call :finalize_report "idx" "%TODAY%"
if "%SCREENER%"=="idx" goto :commit

:skip_idx

:: ---- Crypto ----
if "%SCREENER%"=="crypto" goto :run_crypto
if "%SCREENER%"=="all" goto :run_crypto
goto :skip_crypto

:run_crypto
echo [%TIME%] Running Crypto screener...
"%PYTHON%" "%BASE_DIR%screeners\crypto\scripts\crypto_undervalued_screener.py" --universe top100 --limit 20 --format markdown > "%BASE_DIR%reports\crypto\%TODAY%.md" 2> "%BASE_DIR%logs\crypto-%TODAY%.err"
call :finalize_report "crypto" "%TODAY%"
if "%SCREENER%"=="crypto" goto :commit

:skip_crypto

:: ---- US ----
if "%SCREENER%"=="us" goto :run_us
if "%SCREENER%"=="all" goto :run_us
goto :skip_us

:run_us
echo [%TIME%] Running US screener...
"%PYTHON%" "%BASE_DIR%screeners\us\scripts\us_undervalued_screener.py" --universe liquid --limit 30 --format markdown > "%BASE_DIR%reports\us\%TODAY%.md" 2> "%BASE_DIR%logs\us-%TODAY%.err"
call :finalize_report "us" "%TODAY%"

:skip_us
goto :commit

:: Only keep/copy/commit if report has content (>100 bytes)
:finalize_report
set "RNAME=%~1"
set "RDATE=%~2"
set "RFILE=%BASE_DIR%reports\%RNAME%\%RDATE%.md"
for %%A in ("%RFILE%") do set "RSIZE=%%~zA"
if not defined RSIZE set "RSIZE=0"
if %RSIZE% LSS 100 (
    echo [%TIME%] WARNING: %RNAME% report empty/failed ^(%RSIZE% bytes^). See logs\%RNAME%-%RDATE%.err
    if exist "%RFILE%" del "%RFILE%"
    exit /b 1
)
copy /Y "%RFILE%" "%BASE_DIR%reports\%RNAME%\latest.md" >nul
echo [%TIME%] %RNAME% done ^(%RSIZE% bytes^).
exit /b 0

:commit
echo [%TIME%] Committing reports to GitHub...
cd /d "%BASE_DIR%"
git add reports\
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "📊 Screener report %TODAY%"
    git push
    echo [%TIME%] Pushed to GitHub.
) else (
    echo [%TIME%] No changes to commit.
)

echo [%TIME%] All done!
exit /b 0
