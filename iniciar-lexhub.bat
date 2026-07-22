@echo off
REM Atalho para iniciar o LexHub (Hub Juridico Condominial)
cd /d "%~dp0"
echo ============================================================
echo   LexHub esta iniciando...
echo   Quando aparecer "Application startup complete", abra:
echo.
echo        http://localhost:8000
echo.
echo   Para PARAR o servidor: feche esta janela ou aperte Ctrl+C
echo ============================================================
echo.
uv run uvicorn app.main:app --port 8000
pause
