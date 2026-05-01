@echo off
title Obscura Vault
echo.
echo  ==========================================
echo   OBSCURA VAULT - Video Pipeline
echo   History They Buried. We Dig It Up.
echo  ==========================================
echo.
python start.py
if errorlevel 1 (
    echo.
    echo  ERROR: Could not start. Make sure Python is installed.
    echo  Download Python from: https://python.org/downloads
    echo.
    pause
)
