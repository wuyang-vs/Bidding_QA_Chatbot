@echo off
chcp 65001 >nul
title Bidding QA Chatbot - 停止服务
echo ================================================
echo   停止 BiddingQA 后端与前端进程
echo ================================================
echo.

setlocal enabledelayedexpansion

REM ---- 策略 1: 按窗口标题精准 kill ----
echo [策略1] 按窗口标题终止...
set "BACKEND_KILLED=0"
set "FRONTEND_KILLED=0"

for /f "tokens=2" %%p in ('tasklist /fi "WINDOWTITLE eq BiddingQA-Backend*" /fo list 2^>nul ^| find "PID:"') do (
    taskkill /f /pid %%p >nul 2>&1
    if !errorlevel!==0 (
        echo   后端窗口 %%p 已终止
        set "BACKEND_KILLED=1"
    )
)

for /f "tokens=2" %%p in ('tasklist /fi "WINDOWTITLE eq BiddingQA-Frontend*" /fo list 2^>nul ^| find "PID:"') do (
    taskkill /f /pid %%p >nul 2>&1
    if !errorlevel!==0 (
        echo   前端窗口 %%p 已终止
        set "FRONTEND_KILLED=1"
    )
)

if !BACKEND_KILLED!==0  echo   后端: 未找到匹配窗口
if !FRONTEND_KILLED!==0 echo   前端: 未找到匹配窗口

REM ---- 策略 2: 按端口兜底 kill ----
echo.
echo [策略2] 按端口兜底清理 (8001 / 3000)...

set "PORT_FALLBACK=0"

REM 后端 8001
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8001" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%p >nul 2>&1
    if !errorlevel!==0 (
        echo   端口 8001 (PID %%p) 已终止
        set "PORT_FALLBACK=1"
    )
)

REM 前端 3000
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%p >nul 2>&1
    if !errorlevel!==0 (
        echo   端口 3000 (PID %%p) 已终止
        set "PORT_FALLBACK=1"
    )
)

if !PORT_FALLBACK!==0 echo   端口均已释放, 无需清理

REM ---- 策略 3: 进程树兜底 (仅 uvicorn/node) ----
echo.
echo [策略3] 进程树清理 (兜底)...
set "TREE_FALLBACK=0"

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8001" ^| findstr "LISTENING"') do (
    taskkill /f /t /pid %%p >nul 2>&1
    if !errorlevel!==0 (
        echo   进程树 %%p 已终止
        set "TREE_FALLBACK=1"
    )
)

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    taskkill /f /t /pid %%p >nul 2>&1
    if !errorlevel!==0 (
        echo   进程树 %%p 已终止
        set "TREE_FALLBACK=1"
    )
)

if !TREE_FALLBACK!==0 echo   全部端口已释放

echo.
echo ================================================
echo   完成.
echo ================================================
timeout /t 2 >nul
