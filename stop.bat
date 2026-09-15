@echo off
chcp 65001 >nul
title Bidding QA Chatbot - 停止服务
echo ================================================
echo   停止 BiddingQA 后端与前端进程
echo ================================================
echo.

REM ---- 按窗口标题关闭 (最精准) ----
taskkill /fi "WINDOWTITLE eq BiddingQA-Backend*" /f >nul 2>&1
if not errorlevel 1 (
    echo   后端已停止
) else (
    echo   后端未运行
)

taskkill /fi "WINDOWTITLE eq BiddingQA-Frontend*" /f >nul 2>&1
if not errorlevel 1 (
    echo   前端已停止
) else (
    echo   前端未运行
)

echo.
echo 完成.
timeout /t 2 >nul
