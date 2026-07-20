@echo off
chcp 65001 >nul
title Jarvis - Microfone
cd /d "%~dp0"
uv run python voz/jarvis_voz.py --microfone
if errorlevel 1 pause
