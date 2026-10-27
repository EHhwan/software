@echo off
setlocal
chcp 65001 >nul
rem 레시피 믹스 실행 파일 - 더블클릭하면 서버를 켜고 브라우저를 연다. 끄려면 이 창에서 Ctrl+C
pushd "%~dp0"

rem 1) 파이썬 확인
where python >nul 2>&1
if errorlevel 1 (
  echo [오류] 파이썬을 찾을 수 없어요. python.org 에서 설치할 때 "Add python.exe to PATH" 를 체크해 주세요.
  goto :fail
)

rem 2) 가상환경이 없으면 만든다 (처음 한 번)
if not exist "venv\Scripts\python.exe" (
  echo [준비] 가상환경을 만드는 중이에요... 처음 한 번만 시간이 걸려요.
  python -m venv venv
  if errorlevel 1 goto :fail
)

rem 3) 패키지 설치·확인 (git pull 로 새 패키지가 추가돼도 자동으로 설치된다)
echo [준비] 패키지를 확인하는 중이에요...
"venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [오류] 패키지 설치에 실패했어요. 위의 오류 메시지를 확인해 주세요.
  goto :fail
)

rem 4) .env 확인
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo [안내] .env 파일이 없어서 예시로 만들었어요. .env 를 열어 GEMINI_API_KEY 를 넣은 뒤 다시 실행해 주세요.
  notepad ".env"
  goto :fail
)

rem 5) 2초 뒤 브라우저 열기 + 서버 실행
echo.
echo  레시피 믹스 서버를 켰어요: http://127.0.0.1:5000
echo  끄려면 이 창에서 Ctrl + C 를 누르세요.
echo.
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5000"
"venv\Scripts\python.exe" run.py
popd
exit /b 0

:fail
pause
popd
exit /b 1
