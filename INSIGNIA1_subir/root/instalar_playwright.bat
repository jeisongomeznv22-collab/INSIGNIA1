@echo off
rem Descarga el navegador Chromium que usa Playwright (una sola vez por
rem equipo). Hace falta antes de poder correr run_test_legacy.bat (la
rem prueba del portal antiguo 4-72), que abre su propio Chromium via
rem Playwright en vez de conectarse al Chrome normal.
setlocal
cd /d "%~dp0"
python -m playwright install chromium
echo.
echo (Si no viste ningun error arriba, ya quedo instalado.)
echo (Vuelve a intentar run_test_legacy.bat)
pause
