@echo off
REM weekly-restart.cmd — 매주 토요일 서버/터널 재시작
cd /d E:\project

echo [%date% %time%] 서버 재시작 시작...

REM 1. 기존 프로세스 정리
echo [1/3] 기존 프로세스 종료중...
taskkill /f /im cloudflared.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1
timeout /t 3 /nobreak >nul

REM 2. Flask 서버 실행
echo [2/3] Flask 서버 시작중...
start /B python file_server_external.py
timeout /t 5 /nobreak >nul

REM 3. Cloudflare Tunnel 실행
echo [3/3] Cloudflare Tunnel 시작중...
start /B cloudflared tunnel run a25968d2-4913-4154-b41b-70f3b1b52946

echo [%date% %time%] 재시작 완료!
