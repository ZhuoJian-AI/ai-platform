@echo off
setlocal EnableExtensions
chcp 65001 >nul
title AI Infra - One Click Start

rem Always run from the directory containing this script.
cd /d "%~dp0"

set "COMPOSE_FILES=--env-file .env.deploy -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.local.yml"
set "FRONTEND_DIR=%CD%\frontend"
set "DOCKER_DESKTOP=C:\Program Files\Docker\Docker\Docker Desktop.exe"

echo.
echo ============================================================
echo   AI Infra - Starting all local services
echo ============================================================
echo.

call :require_file ".env.deploy" || goto :failed
call :require_file "docker-compose.yml" || goto :failed
call :require_file "docker-compose.prod.yml" || goto :failed
call :require_file "docker-compose.local.yml" || goto :failed
call :require_file "frontend\package.json" || goto :failed

where docker.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker CLI was not found. Please install Docker Desktop first.
    goto :failed
)

docker info >nul 2>&1
if errorlevel 1 (
    if not exist "%DOCKER_DESKTOP%" (
        echo [ERROR] Docker is not running and Docker Desktop was not found at:
        echo         %DOCKER_DESKTOP%
        goto :failed
    )

    echo [1/4] Docker is not running. Starting Docker Desktop...
    start "" /min "%DOCKER_DESKTOP%"
    call :wait_for_docker 60
    if errorlevel 1 goto :failed
) else (
    echo [1/4] Docker is ready.
)

echo [2/4] Starting PostgreSQL, Redis, Mock API, Skill Runner and backend...
docker compose %COMPOSE_FILES% up -d
if errorlevel 1 (
    echo [INFO] Normal startup failed. Retrying with image build...
    docker compose %COMPOSE_FILES% up -d --build
    if errorlevel 1 (
        echo [ERROR] Docker Compose services failed to start.
        goto :failed
    )
)

echo [3/4] Starting frontend...
call :is_port_open 5173
if not errorlevel 1 (
    echo       Port 5173 is already in use; keeping the existing frontend process.
) else (
    where npm.cmd >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] npm.cmd was not found. Please install Node.js first.
        goto :failed
    )

    if not exist "%FRONTEND_DIR%\node_modules" (
        echo       Frontend dependencies are missing. Running npm ci...
        pushd "%FRONTEND_DIR%"
        set "HTTP_PROXY=http://127.0.0.1:7897"
        set "HTTPS_PROXY=http://127.0.0.1:7897"
        call npm.cmd ci
        set "HTTP_PROXY="
        set "HTTPS_PROXY="
        if errorlevel 1 (
            popd
            echo [ERROR] Frontend dependency installation failed.
            goto :failed
        )
        popd
    )

    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$work='%FRONTEND_DIR%'; $out=Join-Path $work 'vite.out.log'; $err=Join-Path $work 'vite.err.log'; Start-Process -FilePath $env:ComSpec -ArgumentList '/d','/c','npm.cmd run dev -- --host 127.0.0.1' -WorkingDirectory $work -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err"
    if errorlevel 1 (
        echo [ERROR] Frontend process could not be created.
        goto :failed
    )
)

echo [4/4] Waiting for service ports...
call :wait_for_port 5173 30 "Frontend"
call :wait_for_port 8000 45 "Backend"
call :wait_for_port 8010 30 "Mock API"
call :wait_for_port 5434 30 "PostgreSQL"
call :wait_for_port 6381 30 "Redis"
call :wait_for_port 8020 45 "Skill Runner"

echo.
echo ============================================================
echo   Startup finished
echo ============================================================
call :show_port 5173 "Frontend"
call :show_port 8000 "Backend"
call :show_port 8010 "Mock API"
call :show_port 5434 "PostgreSQL"
call :show_port 6381 "Redis"
call :show_port 8020 "Skill Runner"
echo.
echo   Admin console: http://localhost:5173
echo   Backend health: http://localhost:8000/health
echo   Mock API health: http://localhost:8010/health
echo   Skill Runner capabilities: http://localhost:8020/health
echo   Office preview: browser renders the authenticated original file by type
echo   Object storage: controlled by WORKSPACE_OBJECT_STORAGE_ENABLED in .env.deploy
echo.
echo   Frontend logs:
echo     %FRONTEND_DIR%\vite.out.log
echo     %FRONTEND_DIR%\vite.err.log
echo.

if not defined AI_INFRA_NO_OPEN start "" "http://localhost:5173"
if not defined AI_INFRA_NO_PAUSE pause
exit /b 0

:require_file
if exist "%~1" exit /b 0
echo [ERROR] Required file is missing: %~1
exit /b 1

:wait_for_docker
for /l %%I in (1,1,%~1) do (
    docker info >nul 2>&1
    if not errorlevel 1 (
        echo       Docker is ready.
        exit /b 0
    )
    if %%I==1 echo       Waiting for the Docker engine...
    timeout /t 2 /nobreak >nul
)
echo [ERROR] Docker did not become ready within %~1 attempts.
exit /b 1

:is_port_open
powershell.exe -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %~1 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:wait_for_port
for /l %%I in (1,1,%~2) do (
    call :is_port_open %~1
    if not errorlevel 1 exit /b 0
    timeout /t 1 /nobreak >nul
)
echo [WARN] %~3 did not listen on port %~1 within %~2 seconds.
exit /b 1

:show_port
call :is_port_open %~1
if errorlevel 1 (
    echo   [OFFLINE] %~2 - port %~1
) else (
    echo   [ONLINE ] %~2 - port %~1
)
exit /b 0

:failed
echo.
echo Startup failed. Review the error above and Docker logs.
echo You can inspect containers with: docker compose %COMPOSE_FILES% ps
echo.
if not defined AI_INFRA_NO_PAUSE pause
exit /b 1
