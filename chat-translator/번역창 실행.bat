@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "VPYW=%VENV%\Scripts\pythonw.exe"

if exist "%VENV%\installed.ok" if exist "%VPYW%" goto run

echo ==================================================
echo  와우 채팅 번역 창 - 처음 한 번만 설치를 진행합니다
echo ==================================================
echo.

set "PY="
py -3 -c "import sys,tkinter; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
python -c "import sys,tkinter; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto have_python
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto have_python

echo Python이 설치되어 있지 않습니다. 자동으로 설치합니다...
echo 설치 창이 뜨면 허용해 주세요. 몇 분 걸릴 수 있습니다.
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto have_python

echo.
echo [!] Python 자동 설치에 실패했습니다.
echo     https://www.python.org/downloads/ 에서 Python을 설치한 뒤
echo     이 파일을 다시 더블클릭해 주세요.
echo     설치할 때 "Add python.exe to PATH" 에 체크하세요.
pause
exit /b 1

:have_python
echo [1/2] 전용 실행 환경을 만드는 중...
if not exist "%VPY%" %PY% -m venv "%VENV%"
if not exist "%VPY%" goto fail

echo [2/2] 필요한 패키지를 설치하는 중... 인터넷 연결 필요
"%VPY%" -m pip install --disable-pip-version-check -q -r "%~dp0requirements.txt"
if errorlevel 1 goto fail
"%VPY%" -c "import tkinter, anthropic" >nul 2>nul
if errorlevel 1 goto fail

echo ok> "%VENV%\installed.ok"
echo.
echo 설치 완료! 번역 창을 엽니다. 다음부터는 바로 열립니다.
timeout /t 2 >nul

:run
start "" "%VPYW%" "%~dp0run_translator.pyw"
exit /b 0

:fail
echo.
echo [!] 설치 중 문제가 생겼습니다. 인터넷 연결을 확인하고 다시 실행해 주세요.
echo     계속 실패하면 .venv 폴더를 지우고 다시 실행해 보세요.
pause
exit /b 1
