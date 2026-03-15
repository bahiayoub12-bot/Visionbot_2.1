@echo off
chcp 65001 >nul
title VisionBot v2.1 — بناء EXE
echo.
echo  ╔══════════════════════════════════════╗
echo  ║   بناء VisionBot v2.1 كـ EXE        ║
echo  ╚══════════════════════════════════════╝
echo.

pip install pyinstaller --quiet

pyinstaller --onefile --windowed ^
    --name "VisionBot_v2.1" ^
    --icon=assets\icon.ico ^
    --add-data "vision_config.json;." ^
    vision_bot_v2_1.py

echo.
echo  ✅ الملف في مجلد: dist\VisionBot_v2.1.exe
pause
