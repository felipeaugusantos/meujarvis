@echo off
title Jarvis
cd /d "%~dp0"
uv run jarvis chat %*
if errorlevel 1 pause
