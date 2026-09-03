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
:: Get date in YYYY-MM-DD format (locale-safe, no wmic)
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TODAY=%%I"

:: Fallback python
if not exist "%PYTHON%" set "PYTHON=python"

:: Parse argument
set "SCREENER=%~1"
if "%SCREENER%"=="" set "SCREENER=all"

:: Create report dirs
if not exist "%BASE_DIR%reports\idx" mkdir "%BASE_DIR%reports\idx"
if not exist "%BASE_DIR%reports\crypto" mkdir "%BASE_DIR%reports\crypto"
if not exist "%BASE_DIR%reports\us" mkdir "%BASE_DIR%reports\us"

:: ---- IDX ----
if "%SCREENER%"=="idx" goto :run_idx
if "%SCREENER%"=="all" goto :run_idx
goto :skip_idx

:run_idx
echo [%TIME%] Running IDX screener...
"%PYTHON%" "%BASE_DIR%screeners\idx\scripts\tuntun_undervalued_screener.py" --universe IHSG --limit 30 --format markdown > "%BASE_DIR%reports\idx\%TODAY%.md"
if exist "%BASE_DIR%reports\idx\%TODAY%.md" copy /Y "%BASE_DIR%reports\idx\%TODAY%.md" "%BASE_DIR%reports\idx\latest.md" >nul
echo [%TIME%] IDX done.
if "%SCREENER%"=="idx" goto :commit

:skip_idx

:: ---- Crypto ----
if "%SCREENER%"=="crypto" goto :run_crypto
if "%SCREENER%"=="all" goto :run_crypto
goto :skip_crypto

:run_crypto
echo [%TIME%] Running Crypto screener...
"%PYTHON%" "%BASE_DIR%screeners\crypto\scripts\crypto_undervalued_screener.py" --universe top100 --limit 20 --format markdown > "%BASE_DIR%reports\crypto\%TODAY%.md"
if exist "%BASE_DIR%reports\crypto\%TODAY%.md" copy /Y "%BASE_DIR%reports\crypto\%TODAY%.md" "%BASE_DIR%reports\crypto\latest.md" >nul
echo [%TIME%] Crypto done.
if "%SCREENER%"=="crypto" goto :commit

:skip_crypto

:: ---- US ----
if "%SCREENER%"=="us" goto :run_us
if "%SCREENER%"=="all" goto :run_us
goto :skip_us

:run_us
echo [%TIME%] Running US screener...
"%PYTHON%" "%BASE_DIR%screeners\us\scripts\us_undervalued_screener.py" --universe liquid --limit 30 --format markdown > "%BASE_DIR%reports\us\%TODAY%.md"
if exist "%BASE_DIR%reports\us\%TODAY%.md" copy /Y "%BASE_DIR%reports\us\%TODAY%.md" "%BASE_DIR%reports\us\latest.md" >nul
echo [%TIME%] US done.

:skip_us

:: ---- Auto commit to GitHub ----
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
