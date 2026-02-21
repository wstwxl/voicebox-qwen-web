@echo off
chcp 65001 > nul
title Qwen3-TTS Local Server
color 0B

echo ===================================================
echo     Qwen3-TTS 本地语音工作室 - 启动程序
echo     Powered by FastAPI & Qwen3-TTS
echo ===================================================
echo.
echo [1] 正在激活 Conda 虚拟环境 (voicebox)...
call "C:\Users\Amorwest\miniconda3\envs\voicebox\Scripts\activate.bat"

echo [2] 切换到工程目录...
cd /d "%~dp0"

echo [3] 正在启动本地服务器 (127.0.0.1:8888)...
echo [INFO] 如果浏览器没有自动打开，请手动访问 http://127.0.0.1:8888
echo [INFO] 按 Ctrl+C 可以退出服务器
echo.

:: 异步打开浏览器
start http://127.0.0.1:8888

:: 启动 FastAPI
"C:\Users\Amorwest\miniconda3\envs\voicebox\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8888

pause
