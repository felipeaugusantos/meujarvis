@echo off
chcp 65001 >nul
title Jarvis - Voz
cd /d "%~dp0"
uv run python voz/jarvis_voz.py %*
if errorlevel 1 pause
