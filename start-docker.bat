@echo off
chcp 65001 >nul 2>&1
title BiddingQA-Docker

echo ============================================
echo   Bidding QA Chatbot - Docker 一键启动
echo ============================================
echo.

REM 检测 docker-compose 是否可用
where docker-compose >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 未找到 docker-compose，请先安装 Docker Desktop
    echo 下载: https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

REM 检测 Docker 引擎是否运行
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker 引擎未运行，请先启动 Docker Desktop
    pause
    exit /b 1
)

echo [1/3] 启动 Docker 服务...
docker-compose up -d
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] 启动失败，请检查 docker-compose.yml
    pause
    exit /b 1
)

echo.
echo [2/3] 等待后端就绪...
set "HEALTH_URL=http://localhost:8001/api/health"
set "RETRIES=30"
:wait_backend
powershell -Command "try { $r = Invoke-WebRequest -Uri '%HEALTH_URL%' -TimeoutSec 3 -UseBasicParsing; if ($r.StatusCode -eq 200) { exit 0 } } catch {} exit 1" >nul 2>&1
if %errorlevel% equ 0 (
    echo       后端已就绪
    goto :open_browser
)
set /a RETRIES-=1
if %RETRIES% gtr 0 (
    echo       等待中... (剩余 %RETRIES% 次)
    timeout /t 2 /nobreak >nul
    goto :wait_backend
)
echo       [WARN] 后端未在 60 秒内就绪，仍尝试打开浏览器
goto :open_browser

:open_browser
echo.
echo [3/3] 打开浏览器...
start "" "http://localhost:3000"

echo.
echo ============================================
echo   启动完成!
echo   前端:   http://localhost:3000
echo   后端:   http://localhost:8001
echo   API文档: http://localhost:8001/docs
echo   Qdrant:  http://localhost:6333/dashboard
echo   Neo4j:   http://localhost:7474
echo ============================================
echo.
echo 按任意键关闭此窗口（服务在后台继续运行）
echo 停止服务请运行 stop-docker.bat
pause >nul
