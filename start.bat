@echo off
chcp 65001 >nul
echo ================================
echo  APS-HAP 系统启动
echo ================================
echo.

REM 设置项目根目录
set PROJECT_ROOT=%~dp0

REM 检查是否使用便携版Node.js
if exist "%PROJECT_ROOT%offline\runtime\nodejs\node.exe" (
    set PATH=%PROJECT_ROOT%offline\runtime\nodejs;%PATH%
    echo [INFO] 使用便携版 Node.js
) else (
    echo [INFO] 使用系统 Node.js
)

REM 检查Redis是否已运行
redis-cli ping >nul 2>&1
if errorlevel 1 (
    echo [1/3] 启动 Redis...
    if exist "%PROJECT_ROOT%offline\runtime\Redis-x64-5.0.14.1.zip" (
        echo [提示] 需先解压 Redis-x64-5.0.14.1.zip
    )
    start "Redis" redis-server.exe --port 6379
    timeout /t 2 >nul
) else (
    echo [1/3] Redis 已在运行
)

echo [2/3] 启动后端...
start "APS-Backend" cmd /k "cd /d %PROJECT_ROOT%backend && set PYTHONPATH=. && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"
timeout /t 3 >nul

echo [3/3] 启动前端...
start "APS-Frontend" cmd /k "cd /d %PROJECT_ROOT%frontend && npx vite --host 0.0.0.0 --port 3000"

echo.
echo ================================
echo  系统已启动！
echo  前端: http://localhost:3000
echo  后端: http://localhost:8001
echo  API文档: http://localhost:8001/docs
echo ================================
echo.
pause
