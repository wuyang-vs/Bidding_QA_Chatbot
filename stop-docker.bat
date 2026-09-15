@echo off
chcp 65001 >nul 2>&1
title BiddingQA-Docker-Stop

echo ============================================
echo   Bidding QA Chatbot - Docker 停止服务
echo ============================================
echo.

where docker-compose >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 未找到 docker-compose
    pause
    exit /b 1
)

echo 正在停止所有 Docker 服务...
docker-compose down
echo.
echo 所有服务已停止。
echo 数据卷 (qdrant_data / pg_data / neo4j_data) 已保留。
echo.
pause
