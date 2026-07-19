@echo off
title Jarvis Web
cd /d "%~dp0"
echo Iniciando o servidor do Jarvis...
echo.
echo Quando o navegador abrir, a interface estara em http://127.0.0.1:8000
echo Feche esta janela para desligar o Jarvis.
echo.
start "" http://127.0.0.1:8000
uv run jarvis serve --host 127.0.0.1 --port 8000
pause
