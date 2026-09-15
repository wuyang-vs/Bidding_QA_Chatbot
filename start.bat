@echo off
chcp 65001 >nul
title Bidding QA Chatbot - 一键启动
echo ================================================
echo   招投标 RAG 智能问答系统 - 一键启动
echo ================================================
echo.

cd /d "%~dp0"

REM ---- 检查 Python venv ----
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [错误] 未找到 .venv\Scripts\python.exe
    echo 请先运行: uv sync
    pause
    exit /b 1
)

REM ---- 检查后端依赖 ----
"%PYTHON%" -c "import fastapi" 2>nul
if errorlevel 1 (
    echo [警告] 后端依赖未安装, 正在执行 uv sync...
    call uv sync
)

REM ---- 检查前端依赖 ----
if not exist "frontend\node_modules" (
    echo [警告] 前端依赖未安装, 正在执行 npm install...
    cd frontend && call npm install && cd ..
)

echo.
echo [1/2] 启动后端 API (端口 8001)...
start "BiddingQA-Backend" cmd /k ""%PYTHON%" main.py api"

echo [2/2] 启动前端 (端口 3000)...
start "BiddingQA-Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ================================================
echo   启动完成!
echo   前端:   http://localhost:3000
echo   后端:   http://localhost:8001
echo   API文档: http://localhost:8001/docs
echo   系统监控: http://localhost:8001/api/system/metrics
echo ================================================
echo.
echo 关闭此窗口不会停止服务. 要停止请关闭后端/前端独立窗口.
pause
