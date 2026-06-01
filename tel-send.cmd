@echo off
REM tel-send.cmd — 프로젝트 문서를 텔레그램으로 직접 전송
REM 사용법: tel-send <파일경로>
REM 예)     tel-send E:\project\file_server_external.py

cd /d %~dp0
python tel-send.py %*
