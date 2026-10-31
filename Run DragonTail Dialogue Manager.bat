@echo off
cd /d "%~dp0"
py -3 dragontail_dialogue_manager.py
if errorlevel 1 pause
