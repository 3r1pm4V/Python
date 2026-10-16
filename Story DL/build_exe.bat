@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

rem ---- Doc cau hinh build tu .env (bo qua dong comment) ----
set "APP_NAME=StoryLoader"
set "ONEFILE=1"
set "WINDOWED=1"
set "PYTHON_CMD=py -3"
set "ICON="
set "RUN_TESTS=1"
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
)

echo ============================================
echo  Build %APP_NAME%  (onefile=%ONEFILE%, windowed=%WINDOWED%)
echo ============================================

rem ---- 1. venv ----
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Tao virtualenv .venv ...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :fail_python
) else (
    echo [1/4] Dung lai .venv co san
)
set "VPY=.venv\Scripts\python.exe"

rem ---- 2. dependencies ----
echo [2/4] Cai dependencies ...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements-dev.txt
if errorlevel 1 goto :fail

rem ---- 3. test ----
if "%RUN_TESTS%"=="1" (
    echo [3/4] Chay unit test ...
    "%VPY%" -m pytest -q tests
    if errorlevel 1 goto :fail
) else (
    echo [3/4] Bo qua test
)

rem ---- 4. build ----
echo [4/4] PyInstaller ...
"%VPY%" -m PyInstaller StoryLoader.spec --noconfirm --clean
if errorlevel 1 goto :fail

echo.
echo ============================================
if "%ONEFILE%"=="1" (
    echo  XONG: dist\%APP_NAME%.exe
) else (
    echo  XONG: dist\%APP_NAME%\%APP_NAME%.exe  ^(copy ca thu muc^)
)
echo  Luu y: may dich can cai Google Chrome. config/history/queue duoc luu canh file .exe
echo ============================================
pause
exit /b 0

:fail_python
echo [LOI] Khong tao duoc venv. Kiem tra PYTHON_CMD trong .env (can Python 3.10+ tren may BUILD).
pause
exit /b 1

:fail
echo [LOI] Build that bai - xem log phia tren.
pause
exit /b 1
