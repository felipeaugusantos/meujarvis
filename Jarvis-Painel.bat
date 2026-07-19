@echo off
title Jarvis Painel
cd /d "%~dp0"
echo Iniciando o painel...
echo.
echo Nesta maquina:  http://127.0.0.1:8001
echo No tablet:      http://SEU-IP-LOCAL:8001
echo.
echo Feche esta janela para desligar o painel.
echo.
start "" http://127.0.0.1:8001
uv run python dashboard/app.py
pause
