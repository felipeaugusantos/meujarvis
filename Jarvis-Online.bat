@echo off
chcp 65001 >nul
title Jarvis Online
cd /d "%~dp0"

if not exist "dashboard\.senha" (
  echo.
  echo   ATENCAO: nenhuma senha definida.
  echo.
  echo   Sem senha, qualquer pessoa com o endereco publico veria e apagaria
  echo   suas tarefas. Defina uma antes de expor o painel:
  echo.
  echo       uv run python dashboard/definir_senha.py
  echo.
  pause
  exit /b 1
)

echo.
echo   Subindo o painel...
start "Jarvis Painel" /min cmd /c "uv run python dashboard/app.py"

echo   Aguardando o painel responder...
:espera
timeout /t 2 /nobreak >nul
curl -s -o nul --max-time 2 http://127.0.0.1:8001/entrar || goto espera

echo.
echo   Abrindo o tunel. O endereco publico aparece abaixo, em
echo   https://algo-aleatorio.trycloudflare.com
echo.
echo   Feche esta janela para tirar o Jarvis do ar.
echo.

cloudflared tunnel --url http://127.0.0.1:8001
pause
