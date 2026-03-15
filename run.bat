@echo off
chcp 65001 >nul
title VisionBot v2.1
echo.
echo  ╔══════════════════════════════════════╗
echo  ║    VisionBot v2.1 — بدء التشغيل     ║
echo  ╚══════════════════════════════════════╝
echo.

:: التحقق من Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ❌ Python غير مثبت — حمّله من python.org
    pause & exit
)

:: تثبيت المتطلبات الأساسية
echo  📦 تثبيت المتطلبات...
pip install pyautogui pillow numpy --quiet
pip install anthropic openai groq --quiet

echo  ✅ جاهز!
echo.
python vision_bot_v2_1.py
pause
